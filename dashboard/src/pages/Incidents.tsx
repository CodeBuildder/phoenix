import { useEffect, useRef, useState } from 'react'
import useSWR, { useSWRConfig } from 'swr'
import { fetchScenarios, stopScenario } from '../api/chaos'
import { fetchTopology, fetchBlastRadius } from '../api/graph'
import { fetchCatalog } from '../api/faultlib'
import { executeInjection, prepareInjection, type InjectionMode, type InjectionPreview } from '../api/incidents'
import type { Scenario } from '../types/chaos'
import type { AffectedNode } from '../types/graph'
import type { FaultCatalogEntry } from '../types/faultlib'
import {
  AlertTriangle, Bell, CheckCircle2, ChevronDown, ChevronUp,
  Clock, Loader2, Shield, Square, Zap, X, Copy, RefreshCw,
} from 'lucide-react'

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtHMS(iso: string) { return new Date(iso).toLocaleTimeString('en-US', { hour12: false }) }
function fmtSec(s: number) { if (s < 60) return `${s}s`; return `${Math.floor(s / 60)}m ${s % 60}s` }

function incidentSeverity(affected: AffectedNode[]): 'critical' | 'high' | 'medium' | 'low' {
  if (affected.some(n => n.severity === 'high' && n.distance_hops === 1)) return 'critical'
  if (affected.some(n => n.severity === 'high'))   return 'high'
  if (affected.some(n => n.severity === 'medium')) return 'medium'
  return 'low'
}

// Derive impact level from catalog taxonomy_category — what kind of fault it is,
// independent of how far the blast radius actually propagated.
function catalogImpact(faultType: string, catalog: FaultCatalogEntry[]): 'critical' | 'high' | 'medium' | 'low' {
  const entry = catalog.find(e => e.fault_type === faultType)
  if (!entry) return 'low'
  const cat = entry.taxonomy_category
  if (cat === 'cascading' || cat === 'network-partition') return 'high'
  if (cat === 'resource-exhaustion') return 'medium'
  return 'low'
}
function needsHuman(sev: string, affected: AffectedNode[]) {
  return sev === 'critical' || (sev === 'high' && affected.length >= 3)
}

const NOTIF_KEY = 'phoenix_notif_channels'
function loadChannels() {
  try { return JSON.parse(localStorage.getItem(NOTIF_KEY) ?? '{}') as { slack?: string; pd?: string; email?: string }
  } catch { return {} }
}

// ── live timer ────────────────────────────────────────────────────────────────

function useLiveTimer(startedAt: string | null, durationSeconds: number | null) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!startedAt) return
    const tick = () => setElapsed(Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000))
    tick(); const id = setInterval(tick, 1000); return () => clearInterval(id)
  }, [startedAt])
  const pct       = durationSeconds ? Math.min((elapsed / durationSeconds) * 100, 100) : null
  const remaining = durationSeconds ? Math.max(durationSeconds - elapsed, 0) : null
  return { elapsed, remaining, pct }
}

// ── activity log ──────────────────────────────────────────────────────────────

type LogTag =
  | 'INIT' | 'ACTIVATE' | 'SCAN' | 'ASSESS' | 'SEVERITY'
  | 'AGENT' | 'BLOCK' | 'NOTIFY' | 'MONITOR' | 'STOP' | 'RESOLVED'

type LogEntry = {
  id:      string
  ts:      Date
  tag:     LogTag
  msg:     string
  detail?: string
}

const TAG_COLOR: Record<LogTag, string> = {
  INIT:     'text-slate-500',
  ACTIVATE: 'text-warning',
  SCAN:     'text-violet',
  ASSESS:   'text-violet',
  SEVERITY: 'text-danger',
  AGENT:    'text-accent',
  BLOCK:    'text-danger',
  NOTIFY:   'text-cyan',
  MONITOR:  'text-slate-600',
  STOP:     'text-slate-400',
  RESOLVED: 'text-accent',
}
const TAG_BG: Record<LogTag, string> = {
  INIT:     'bg-slate-800/60',
  ACTIVATE: 'bg-warning/10',
  SCAN:     'bg-violet/10',
  ASSESS:   'bg-violet/10',
  SEVERITY: 'bg-danger/15',
  AGENT:    'bg-accent/10',
  BLOCK:    'bg-danger/15',
  NOTIFY:   'bg-cyan/10',
  MONITOR:  'bg-elevated/40',
  STOP:     'bg-elevated/40',
  RESOLVED: 'bg-accent/10',
}

function buildBaseLog(
  scenario: Scenario,
  affected: AffectedNode[],
  matched:  string[],
  blastLoaded: boolean,
  severity: string,
  human: boolean,
  channels: ReturnType<typeof loadChannels>,
): LogEntry[] {
  const entries: LogEntry[] = []
  const ts0 = new Date(scenario.created_at)
  const ts1 = scenario.started_at ? new Date(scenario.started_at) : null

  entries.push({
    id: 'init', ts: ts0, tag: 'INIT',
    msg: `Fault scenario registered: ${scenario.fault_type} via ${scenario.domain}`,
    detail: `ID ${scenario.id.slice(0, 8)}…`,
  })

  if (ts1) {
    entries.push({
      id: 'activate', ts: ts1, tag: 'ACTIVATE',
      msg: `Fault injected: ${scenario.fault_type}`,
      detail: scenario.target.namespace
        ? `namespace: ${scenario.target.namespace} · labels: ${Object.entries(scenario.target.label_selector ?? {}).map(([k,v])=>`${k}=${v}`).join(', ')}`
        : undefined,
    })

    if (blastLoaded) {
      const scanTs = new Date(ts1.getTime() + 800)
      entries.push({
        id: 'scan', ts: scanTs, tag: 'SCAN',
        msg: 'Topology scan complete',
        detail: `${matched.length} service${matched.length !== 1 ? 's' : ''} matched · blast radius computed`,
      })

      const assessTs = new Date(ts1.getTime() + 900)
      if (affected.length > 0) {
        entries.push({
          id: 'assess', ts: assessTs, tag: 'ASSESS',
          msg: `Blast radius: ${affected.length} downstream service${affected.length !== 1 ? 's' : ''} at risk`,
          detail: affected.slice(0, 4).map(n => `${n.name} (${n.severity}, ${n.distance_hops}-hop)`).join(' · '),
        })
        entries.push({
          id: 'severity', ts: new Date(assessTs.getTime() + 50), tag: 'SEVERITY',
          msg: `Severity elevated to ${severity.toUpperCase()}`,
          detail: severity === 'critical'
            ? 'Direct 1-hop high-severity impact detected'
            : `${affected.filter(n=>n.severity==='high').length} high-severity downstream services`,
        })
      } else {
        entries.push({
          id: 'assess', ts: assessTs, tag: 'ASSESS',
          msg: 'Blast radius: fault is fully contained',
          detail: 'No downstream services depend on the target — zero cascade risk',
        })
      }

      // Phoenix Agent activates
      entries.push({
        id: 'agent-on', ts: new Date(assessTs.getTime() + 100), tag: 'AGENT',
        msg: 'Phoenix Agent activated — beginning incident response',
        detail: affected.length > 0
          ? `Monitoring ${affected.length} at-risk services · evaluating healing options`
          : 'Watching for degradation · no action required yet',
      })

      if (human) {
        entries.push({
          id: 'block', ts: new Date(assessTs.getTime() + 150), tag: 'BLOCK',
          msg: 'Auto-heal blocked — blast radius exceeds safe threshold',
          detail: 'Critical cascading risk: human operator decision required before any healing action',
        })
        const notifEntries: string[] = []
        if (channels.slack) notifEntries.push('Slack')
        if (channels.pd)    notifEntries.push('PagerDuty')
        if (channels.email) notifEntries.push('Email')
        if (notifEntries.length > 0) {
          entries.push({
            id: 'notify', ts: new Date(assessTs.getTime() + 200), tag: 'NOTIFY',
            msg: `Alert dispatched → ${notifEntries.join(', ')}`,
            detail: 'Channels: ' + notifEntries.join(' · ') + ' (delivery via M2 agent backend)',
          })
        } else {
          entries.push({
            id: 'notify', ts: new Date(assessTs.getTime() + 200), tag: 'NOTIFY',
            msg: 'No notification channels configured — alert suppressed',
            detail: 'Configure Slack / PagerDuty / Email via the Notify button',
          })
        }
      }
    }
  }

  if (scenario.stopped_at) {
    const stopTs = new Date(scenario.stopped_at)
    if (scenario.status === 'completed') {
      entries.push({
        id: 'stop', ts: stopTs, tag: 'STOP',
        msg: `Fault expired — chaos engine auto-stopped after ${fmtSec(scenario.duration_seconds ?? 0)}`,
      })
      entries.push({
        id: 'agent-heal', ts: new Date(stopTs.getTime() + 200), tag: 'AGENT',
        msg: 'Phoenix Agent closing incident — services recovering',
        detail: 'Monitoring recovery convergence · postmortem generated below',
      })
      entries.push({
        id: 'resolved', ts: new Date(stopTs.getTime() + 500), tag: 'RESOLVED',
        msg: 'Incident resolved ✓',
        detail: affected.length > 0
          ? `${affected.length} affected service${affected.length !== 1 ? 's' : ''} should be recovering now`
          : 'Fault was fully isolated — no recovery action needed',
      })
    } else if (scenario.status === 'stopped') {
      entries.push({
        id: 'stop', ts: stopTs, tag: 'STOP',
        msg: 'Fault manually stopped by operator',
        detail: `Ran for ${fmtSec(Math.floor((stopTs.getTime() - new Date(scenario.started_at!).getTime()) / 1000))}`,
      })
      entries.push({
        id: 'agent-stop', ts: new Date(stopTs.getTime() + 200), tag: 'AGENT',
        msg: 'Phoenix Agent acknowledged manual stop — incident closed',
      })
    }
  }

  return entries.sort((a, b) => a.ts.getTime() - b.ts.getTime())
}

// ── activity stream component ─────────────────────────────────────────────────

function ActivityStream({
  scenario, affected, matched, blastLoaded, severity, human, channels,
}: {
  scenario:    Scenario
  affected:    AffectedNode[]
  matched:     string[]
  blastLoaded: boolean
  severity:    string
  human:       boolean
  channels:    ReturnType<typeof loadChannels>
}) {
  const [heartbeats, setHeartbeats] = useState<LogEntry[]>([])
  const streamRef = useRef<HTMLDivElement>(null)

  const base = buildBaseLog(scenario, affected, matched, blastLoaded, severity, human, channels)
  const all  = [...base, ...heartbeats].sort((a, b) => a.ts.getTime() - b.ts.getTime())

  // Live heartbeats while running
  useEffect(() => {
    if (scenario.status !== 'running') return
    const id = setInterval(() => {
      setHeartbeats(prev => [...prev.slice(-20), {
        id:     `hb-${Date.now()}`,
        ts:     new Date(),
        tag:    'MONITOR' as LogTag,
        msg:    affected.length > 0
          ? `♥  monitoring — ${affected.length} service${affected.length !== 1 ? 's' : ''} at risk · no recovery yet`
          : '♥  monitoring — no downstream impact detected · all clear',
        detail: undefined,
      }])
    }, 5000)
    return () => clearInterval(id)
  }, [scenario.status, affected.length])

  // Auto-scroll to bottom when new entries arrive
  useEffect(() => {
    if (streamRef.current) streamRef.current.scrollTop = streamRef.current.scrollHeight
  }, [all.length])

  return (
    <div>
      <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-2">
        Live Activity Stream
        {scenario.status === 'running' && (
          <span className="ml-2 inline-flex items-center gap-1 text-accent">
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent" />
            </span>
            LIVE
          </span>
        )}
      </p>
      <div
        ref={streamRef}
        className="bg-base border border-border/60 rounded-lg font-mono text-[11px] overflow-y-auto"
        style={{ maxHeight: '280px' }}
      >
        {all.map((entry, i) => (
          <div
            key={entry.id}
            className={`flex gap-3 px-3 py-2 border-b border-border/30 last:border-0 ${
              i === all.length - 1 && scenario.status === 'running' ? 'bg-elevated/20' : ''
            }`}
          >
            {/* timestamp */}
            <span className="text-slate-700 shrink-0 pt-0.5 tabular-nums w-[72px]">
              {fmtHMS(entry.ts.toISOString())}
            </span>
            {/* tag */}
            <span className={`shrink-0 font-bold text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded self-start ${TAG_COLOR[entry.tag]} ${TAG_BG[entry.tag]}`}>
              {entry.tag}
            </span>
            {/* message */}
            <div className="min-w-0 flex-1">
              <span className={`${entry.tag === 'RESOLVED' ? 'text-accent font-semibold' : entry.tag === 'AGENT' ? 'text-accent/90' : 'text-slate-300'}`}>
                {entry.msg}
              </span>
              {entry.detail && (
                <p className="text-slate-600 text-[10px] mt-0.5 leading-relaxed">{entry.detail}</p>
              )}
            </div>
          </div>
        ))}
        {/* typing indicator while agent is working */}
        {scenario.status === 'running' && blastLoaded && (
          <div className="flex gap-3 px-3 py-2">
            <span className="text-slate-700 shrink-0 w-[72px]" />
            <span className={`shrink-0 font-bold text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded self-start text-accent bg-accent/10`}>AGENT</span>
            <div className="flex items-center gap-1.5 text-accent/60">
              <span className="animate-pulse">Phoenix Agent holding — watching for cascading failures</span>
              <span className="inline-flex gap-0.5">
                {[0,1,2].map(i => (
                  <span key={i} className="w-1 h-1 rounded-full bg-accent/50 animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── fault details panel (live — NOT root cause, that's postmortem) ────────────

function FaultDetailsPanel({ scenario, catalog, isRunning }: {
  scenario:  Scenario
  catalog:   FaultCatalogEntry[]
  isRunning: boolean
}) {
  const entry = catalog.find(e => e.fault_type === scenario.fault_type)
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest">Fault Details</p>
        {isRunning && (
          <span className="text-[10px] font-mono text-slate-700">
            — RCA generated after incident closes
          </span>
        )}
      </div>
      <div className="bg-elevated/40 rounded-lg p-3 space-y-2.5">
        <div className="flex flex-wrap gap-2">
          <span className="px-2 py-0.5 rounded bg-warning/10 border border-warning/20 text-warning text-[10px] font-mono">{scenario.fault_type}</span>
          <span className="px-2 py-0.5 rounded bg-elevated border border-border text-slate-400 text-[10px] font-mono">{scenario.domain}</span>
          {entry && <span className="px-2 py-0.5 rounded bg-violet/10 border border-violet/20 text-violet text-[10px] font-mono">{entry.taxonomy_category}</span>}
        </div>
        {entry ? (
          <>
            <p className="text-[11px] text-slate-300 leading-relaxed">{entry.description}</p>
            <div>
              <span className="text-[10px] text-slate-600">Mechanism: </span>
              <span className="text-[11px] text-slate-400">{entry.mechanism}</span>
            </div>
            {entry.typical_symptoms.length > 0 && (
              <div>
                <p className="text-[10px] text-slate-600 mb-1.5">
                  {isRunning ? 'What to watch for right now:' : 'Symptoms observed:'}
                </p>
                <ul className="space-y-1">
                  {entry.typical_symptoms.map(s => (
                    <li key={s} className="text-[11px] text-slate-400 flex items-start gap-1.5">
                      <span className="text-slate-600 shrink-0">›</span>{s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className="text-[11px] text-slate-600 animate-pulse">Looking up {scenario.fault_type} in fault catalog…</p>
        )}
        {isRunning && (
          <p className="text-[10px] font-mono text-slate-700 border-t border-border/40 pt-2 mt-1">
            Phoenix Agent is investigating contributing factors. Root cause analysis and prevention recommendations will appear in the postmortem when this incident closes.
          </p>
        )}
      </div>
    </div>
  )
}

// ── impact panel ──────────────────────────────────────────────────────────────

function ImpactPanel({ affected, matched, isLoading }: { affected: AffectedNode[]; matched: string[]; isLoading: boolean }) {
  if (isLoading) return (
    <div>
      <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-2">Impact</p>
      <p className="text-[11px] font-mono text-slate-600 animate-pulse">Computing blast radius from live topology…</p>
    </div>
  )

  return (
    <div>
      <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-2">
        Impact · {affected.length === 0 ? 'contained' : `${affected.length} service${affected.length !== 1 ? 's' : ''} at risk`}
      </p>
      {affected.length === 0 ? (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-accent/5 border border-accent/20 text-[11px] font-mono text-accent">
          <Shield className="w-3.5 h-3.5 shrink-0" />
          Fault fully contained — no downstream cascade detected
        </div>
      ) : (
        <div className="space-y-1.5">
          {matched.length > 0 && (
            <p className="text-[10px] font-mono text-slate-600 mb-2">
              Directly targeted: {matched.join(', ')}
            </p>
          )}
          {affected.map(n => {
            const color = n.severity === 'high' ? 'text-danger' : n.severity === 'medium' ? 'text-warning' : 'text-accent'
            const border = n.severity === 'high' ? 'border-danger/30 bg-danger/5' : n.severity === 'medium' ? 'border-warning/30 bg-warning/5' : 'border-accent/20 bg-accent/5'
            return (
              <div key={n.node_id} className={`flex items-center gap-2 px-3 py-2 rounded-lg border font-mono text-[11px] ${border}`}>
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${n.severity === 'high' ? 'bg-danger' : n.severity === 'medium' ? 'bg-warning' : 'bg-accent'}`} />
                <span className="text-slate-200 flex-1 truncate">{n.name}</span>
                <span className={`font-bold uppercase text-[10px] shrink-0 ${color}`}>{n.severity}</span>
                <span className="text-slate-600 shrink-0">{n.distance_hops} hop{n.distance_hops !== 1 ? 's' : ''}</span>
                <span className="text-slate-700 shrink-0 text-[10px]">{n.via_edge_types.join(', ')}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── call to action panel ──────────────────────────────────────────────────────

function CallToAction({
  scenario, severity, affected, onStop, stopping,
}: {
  scenario:  Scenario
  severity:  string
  affected:  AffectedNode[]
  onStop:    () => Promise<void>
  stopping:  boolean
}) {
  const [copied, setCopied] = useState(false)
  const channels = loadChannels()
  const notifList = [channels.slack && 'Slack', channels.pd && 'PagerDuty', channels.email && 'Email'].filter(Boolean)

  const kubectlCmd = `kubectl get pods -n ${scenario.target.namespace ?? 'phoenix-system'} -l ${Object.entries(scenario.target.label_selector ?? {}).map(([k,v])=>`${k}=${v}`).join(',')}`

  function copy() {
    navigator.clipboard.writeText(kubectlCmd)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div>
      <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-2">Call to Action</p>
      <div className="bg-danger/5 border border-danger/30 rounded-lg p-4 space-y-3">
        <div className="flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-mono font-bold text-danger">Human intervention required</p>
            <p className="text-[11px] font-mono text-danger/70 mt-0.5">
              {severity.toUpperCase()} severity · {affected.length} downstream service{affected.length !== 1 ? 's' : ''} at risk.
              Phoenix Agent has blocked auto-heal. You must decide.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-start gap-2.5">
            <span className="text-[11px] font-mono text-danger/60 font-bold shrink-0">1.</span>
            <div className="flex-1">
              <p className="text-[11px] font-mono text-slate-300">Stop the fault immediately</p>
              <button
                onClick={onStop}
                disabled={stopping}
                className="mt-1.5 flex items-center gap-1.5 px-3 py-1.5 rounded bg-danger/15 border border-danger/40 text-danger text-xs font-mono hover:bg-danger/25 transition-colors disabled:opacity-50"
              >
                {stopping ? <Loader2 className="w-3 h-3 animate-spin" /> : <Square className="w-3 h-3" />}
                Stop Fault Now
              </button>
            </div>
          </div>

          <div className="flex items-start gap-2.5">
            <span className="text-[11px] font-mono text-danger/60 font-bold shrink-0">2.</span>
            <div className="flex-1">
              <p className="text-[11px] font-mono text-slate-300">Check affected pods in your cluster</p>
              <div className="mt-1.5 flex items-center gap-2 bg-base rounded px-2 py-1.5 border border-border/60">
                <code className="text-[10px] font-mono text-slate-400 flex-1 truncate">{kubectlCmd}</code>
                <button onClick={copy} className="shrink-0 text-slate-600 hover:text-accent transition-colors">
                  {copied ? <CheckCircle2 className="w-3.5 h-3.5 text-accent" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
          </div>

          <div className="flex items-start gap-2.5">
            <span className="text-[11px] font-mono text-danger/60 font-bold shrink-0">3.</span>
            <div className="flex-1">
              <p className="text-[11px] font-mono text-slate-300">Notify your on-call team</p>
              {notifList.length > 0 ? (
                <p className="text-[10px] font-mono text-slate-600 mt-0.5">
                  Channels configured: {notifList.join(', ')} — alert queued for delivery via M2 agent
                </p>
              ) : (
                <p className="text-[10px] font-mono text-slate-700 mt-0.5">
                  No channels configured. Click Notify at the top to add Slack / PagerDuty / Email.
                </p>
              )}
            </div>
          </div>

          <div className="flex items-start gap-2.5">
            <span className="text-[11px] font-mono text-danger/60 font-bold shrink-0">4.</span>
            <div className="flex-1">
              <p className="text-[11px] font-mono text-slate-300">Verify recovery after stopping</p>
              <p className="text-[10px] font-mono text-slate-600 mt-0.5">
                Monitor: {affected.map(n=>n.name).slice(0, 3).join(', ')}{affected.length > 3 ? ` +${affected.length - 3} more` : ''}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── blameless postmortem ──────────────────────────────────────────────────────

const PREVENTION: Record<string, string[]> = {
  'transient': [
    'Add liveness and readiness probes to all affected services',
    'Implement graceful degradation — services should return partial results, not fail hard',
    'Add retry logic with jitter at call sites to handle transient errors',
  ],
  'cascading': [
    'Add circuit breakers between services with direct flow_observed edges',
    'Implement bulkhead isolation so one service failure cannot cascade',
    'Set explicit timeouts on all inter-service calls — never rely on defaults',
  ],
  'resource-exhaustion': [
    'Set CPU and memory resource limits on all deployments in the affected namespace',
    'Add Horizontal Pod Autoscaler (HPA) to scale under load',
    'Implement backpressure — services should shed load before exhausting resources',
  ],
  'network-partition': [
    'Implement retry with exponential backoff and jitter on all network calls',
    'Add service mesh timeout policies (Istio / Linkerd) to bound request duration',
    'Test network partition scenarios regularly to validate resilience posture',
  ],
  'quota-limit': [
    'Set ResourceQuota on the namespace to prevent runaway consumption',
    'Add alerting on quota usage at 70% / 90% thresholds',
    'Review resource requests vs limits — misconfigured requests cause quota exhaustion',
  ],
}

function PostmortemPanel({
  scenario, catalog, affected,
}: {
  scenario: Scenario
  catalog:  FaultCatalogEntry[]
  affected: AffectedNode[]
}) {
  const entry     = catalog.find(e => e.fault_type === scenario.fault_type)
  const severity  = affected.length > 0 ? incidentSeverity(affected) : 'low'
  const startedAt = scenario.started_at ? new Date(scenario.started_at) : null
  const stoppedAt = scenario.stopped_at ? new Date(scenario.stopped_at) : null
  const duration  = startedAt && stoppedAt ? Math.floor((stoppedAt.getTime() - startedAt.getTime()) / 1000) : null
  const category  = entry?.taxonomy_category ?? null
  const prevention = category ? (PREVENTION[category] ?? []) : []

  return (
    <div className="mt-6 border-t border-border/40 pt-5 space-y-5">
      <p className="text-[10px] font-mono text-slate-500 uppercase tracking-widest flex items-center gap-2">
        <span>Blameless Postmortem</span>
        <span className="px-1.5 py-0.5 rounded bg-elevated border border-border text-slate-600 text-[10px]">generated from live incident data</span>
      </p>

      {/* Timeline */}
      <div>
        <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-2">Timeline</p>
        <div className="space-y-1.5 font-mono text-[11px]">
          {scenario.created_at && (
            <div className="flex gap-3"><span className="text-slate-600 w-20 shrink-0">{fmtHMS(scenario.created_at)}</span><span className="text-slate-400">Scenario registered in chaos engine</span></div>
          )}
          {scenario.started_at && (
            <div className="flex gap-3"><span className="text-slate-600 w-20 shrink-0">{fmtHMS(scenario.started_at)}</span><span className="text-slate-300">Fault injected: <span className="text-warning">{scenario.fault_type}</span></span></div>
          )}
          {affected.length > 0 && scenario.started_at && (
            <div className="flex gap-3"><span className="text-slate-600 w-20 shrink-0">+&lt;1s</span><span className="text-slate-400">Blast radius computed — {affected.length} services at risk</span></div>
          )}
          {scenario.stopped_at && (
            <div className="flex gap-3"><span className="text-slate-600 w-20 shrink-0">{fmtHMS(scenario.stopped_at)}</span><span className="text-slate-400">{scenario.status === 'completed' ? 'Fault auto-expired' : 'Fault manually stopped'}</span></div>
          )}
          {duration !== null && (
            <div className="flex gap-3 pt-1 border-t border-border/30 mt-1">
              <span className="text-slate-600 w-20 shrink-0">Duration</span>
              <span className="text-slate-300">{fmtSec(duration)}</span>
            </div>
          )}
        </div>
      </div>

      {/* Root Cause Analysis — only generated post-incident */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest">Root Cause Analysis</p>
          <span className="text-[10px] font-mono text-slate-700 px-1.5 py-0.5 rounded bg-elevated border border-border">
            generated after incident closed at {scenario.stopped_at ? fmtHMS(scenario.stopped_at) : '—'}
          </span>
        </div>
        <div className="bg-elevated/40 rounded-lg p-3 space-y-2.5 text-[11px] font-mono">
          <div>
            <span className="text-slate-600">Direct cause: </span>
            <span className="text-slate-300">{scenario.fault_type} fault injected via {scenario.domain}</span>
            {entry && <span className="text-slate-500"> — {entry.description}</span>}
          </div>
          {affected.length > 0 && (
            <div>
              <span className="text-slate-600">Contributing factors: </span>
              <span className="text-slate-400">
                {affected.slice(0, 3).map(n=>n.name).join(', ')} depend on the target via{' '}
                {[...new Set(affected.flatMap(n=>n.via_edge_types))].join(' and ')} connections —
                identified from live Hubble topology snapshot taken during the incident
              </span>
            </div>
          )}
          <div>
            <span className="text-slate-600">Detection latency: </span>
            <span className="text-accent">{'<1s — Hubble eBPF captured network impact in real time'}</span>
          </div>
          {duration !== null && (
            <div>
              <span className="text-slate-600">Impact window: </span>
              <span className="text-slate-400">
                {fmtSec(duration)} total — {affected.length} downstream service{affected.length !== 1 ? 's' : ''} at {severity} risk
              </span>
            </div>
          )}
          {entry && (
            <div>
              <span className="text-slate-600">Propagation shape: </span>
              <span className="text-slate-400">{entry.blast_radius_shape}</span>
            </div>
          )}
        </div>
      </div>

      {/* What Phoenix did */}
      <div>
        <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-2">What Phoenix Agent did</p>
        <div className="space-y-1.5">
          {[
            'Detected fault via continuous topology monitoring (<1s detection)',
            `Scanned ${scenario.target.namespace ?? 'cluster'} topology and computed full blast radius`,
            affected.length > 0
              ? `Identified ${affected.length} downstream service${affected.length !== 1 ? 's' : ''} at risk — propagation path mapped`
              : 'Confirmed fault is isolated — no downstream cascade detected',
            needsHuman(severity, affected)
              ? 'Blocked auto-heal — cascade severity exceeded safe threshold — escalated to human'
              : 'Monitored continuously — no intervention required — fault ran to completion safely',
            scenario.status === 'completed'
              ? 'Fault expired naturally — acknowledged recovery and closed the incident'
              : 'Acknowledged manual stop — verified operator action — closed the incident',
          ].map((action, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px] font-mono">
              <CheckCircle2 className="w-3.5 h-3.5 text-accent/60 shrink-0 mt-0.5" />
              <span className="text-slate-400">{action}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Prevention */}
      {prevention.length > 0 && (
        <div>
          <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-2">
            Recommendations — prevent recurrence
          </p>
          <div className="space-y-2">
            {prevention.map((rec, i) => (
              <div key={i} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-elevated/40 border border-border/60">
                <span className="text-[11px] font-mono text-accent/60 font-bold shrink-0">{i + 1}.</span>
                <p className="text-[11px] font-mono text-slate-300">{rec}</p>
              </div>
            ))}
          </div>
          {entry && (
            <p className="text-[10px] font-mono text-slate-700 mt-2">
              Recommendations derived from fault category: {entry.taxonomy_category} · {entry.category_rationale}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── incident card ─────────────────────────────────────────────────────────────

function IncidentCard({ scenario, catalog, onStop }: {
  scenario: Scenario
  catalog:  FaultCatalogEntry[]
  onStop:   () => Promise<void>
}) {
  const [expanded, setExpanded] = useState(scenario.status === 'running')
  const [stopping, setStopping] = useState(false)
  const autoStopped = useRef(false)

  const { elapsed, remaining, pct } = useLiveTimer(scenario.started_at, scenario.duration_seconds)

  // Auto-stop when duration expires (backend doesn't always fire completion)
  useEffect(() => {
    if (scenario.status !== 'running') return
    if (!scenario.duration_seconds || elapsed === 0) return
    if (elapsed >= scenario.duration_seconds && !autoStopped.current) {
      autoStopped.current = true
      onStop()
    }
  }, [elapsed, scenario.status, scenario.duration_seconds])

  const target = scenario.target
  const { data: blastData, isLoading: blastLoading } = useSWR(
    target.namespace ? `blast/${scenario.id}/${target.namespace}` : null,
    () => fetchBlastRadius(target.namespace!, scenario.fault_type, target.label_selector ?? {}),
    { refreshInterval: scenario.status === 'running' ? 10_000 : 0 },
  )

  const affected    = blastData?.affected_nodes ?? []
  const matched     = blastData?.matched_nodes  ?? []
  const severity    = affected.length > 0 ? incidentSeverity(affected) : 'low'
  const faultImpact = catalogImpact(scenario.fault_type, catalog)
  const human       = needsHuman(severity, affected)
  const blastLoaded = !blastLoading && blastData !== undefined
  const channels    = loadChannels()

  const isRunning   = scenario.status === 'running'
  const isDone      = scenario.status === 'completed' || scenario.status === 'stopped'

  const SEV_DOT: Record<string, string> = { critical: 'bg-danger', high: 'bg-warning', medium: 'bg-accent', low: 'bg-slate-600' }
  const SEV_CARD: Record<string, string> = { critical: 'border-danger/40 bg-danger/5', high: 'border-warning/30 bg-warning/5', medium: 'border-accent/20 bg-accent/5', low: 'border-border bg-card' }
  const SEV_BADGE: Record<string, string> = { critical: 'text-danger border-danger/40 bg-danger/10', high: 'text-warning border-warning/40 bg-warning/10', medium: 'text-accent border-accent/30 bg-accent/10', low: 'text-slate-400 border-border bg-elevated' }
  const SEV_BAR: Record<string, string> = { critical: '#ff4d4d', high: '#f59e0b', medium: '#00e676', low: '#475569' }

  // Readable service name from target labels
  const targetService = (() => {
    const labels = target.label_selector ?? {}
    const app = labels['app'] ?? labels['name'] ?? labels['component'] ?? null
    if (app) return app
    const parts = scenario.name.split('-')
    if (parts[0] === 'incident' && parts.length > 3) return parts.slice(1, -1).join('-').replace(/-\d{10,}$/, '')
    return scenario.name
  })()

  async function handleStop() {
    setStopping(true)
    await onStop()
    setStopping(false)
  }

  return (
    <div className={`rounded-xl border overflow-hidden transition-all duration-200 ${SEV_CARD[severity]}`}>
      {/* ── header ─────────────────────────────────────────────────── */}
      <div className="px-4 pt-4 pb-3 cursor-pointer" onClick={() => setExpanded(e => !e)}>
        <div className="flex items-start gap-3">
          <div className="mt-1 shrink-0">
            <span className="relative flex h-2.5 w-2.5">
              {isRunning && <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${SEV_DOT[severity]} opacity-60`} />}
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${SEV_DOT[severity]}`} />
            </span>
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-mono font-bold text-slate-100">{targetService}</span>
              <span className="text-slate-600">·</span>
              <span className="text-sm font-mono text-slate-300">{scenario.fault_type}</span>
              <span className={`px-1.5 py-0.5 rounded border text-[10px] font-mono uppercase tracking-wide ${SEV_BADGE[faultImpact]}`}>{faultImpact}</span>
              <span className="px-1.5 py-0.5 rounded bg-elevated border border-border text-[10px] font-mono text-slate-500">{scenario.status}</span>
              {human && isRunning && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-danger/15 border border-danger/30 text-[10px] font-mono text-danger font-bold">
                  <AlertTriangle className="w-3 h-3" />
                  action required
                </span>
              )}
              {isDone && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-accent/10 border border-accent/20 text-[10px] font-mono text-accent">
                  <CheckCircle2 className="w-3 h-3" />
                  postmortem available
                </span>
              )}
            </div>
            <p className="text-[11px] text-slate-500 font-mono mt-1">
              {scenario.domain}
              {target.namespace && ` · ${target.namespace}`}
              {isRunning && elapsed > 0 && ` · ${fmtSec(elapsed)} elapsed`}
              {isRunning && remaining !== null && ` · ${fmtSec(remaining)} remaining`}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {isRunning && (
              <button
                onClick={async e => { e.stopPropagation(); await handleStop() }}
                disabled={stopping}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-danger/10 border border-danger/30 text-danger text-xs font-mono hover:bg-danger/20 transition-colors disabled:opacity-50"
              >
                {stopping ? <Loader2 className="w-3 h-3 animate-spin" /> : <Square className="w-3 h-3" />}
                Stop
              </button>
            )}
            {expanded ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
          </div>
        </div>

        {/* slim progress bar — only when running */}
        {isRunning && pct !== null && (
          <div className="mt-3">
            <div className="h-1 rounded-full bg-elevated overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-1000"
                style={{ width: `${pct}%`, backgroundColor: SEV_BAR[severity] }}
              />
            </div>
          </div>
        )}
      </div>

      {/* ── expanded ───────────────────────────────────────────────── */}
      {expanded && (
        <div className="border-t border-border/40 p-4 space-y-5 fade-in">
          <ActivityStream
            scenario={scenario}
            affected={affected}
            matched={matched}
            blastLoaded={blastLoaded}
            severity={severity}
            human={human}
            channels={channels}
          />

          <div className="grid grid-cols-2 gap-4">
            <FaultDetailsPanel scenario={scenario} catalog={catalog} isRunning={isRunning} />
            <ImpactPanel affected={affected} matched={matched} isLoading={blastLoading} />
          </div>

          {human && isRunning && (
            <CallToAction
              scenario={scenario}
              severity={severity}
              affected={affected}
              onStop={handleStop}
              stopping={stopping}
            />
          )}

          {isDone && (
            <PostmortemPanel scenario={scenario} catalog={catalog} affected={affected} />
          )}
        </div>
      )}
    </div>
  )
}

// ── inject impact modal ────────────────────────────────────────────────────────

function InjectionConfirmModal({ preview, onConfirm, onClose, executing }: {
  preview: InjectionPreview
  onConfirm: () => void
  onClose: () => void
  executing: boolean
}) {
  const [confirmation, setConfirmation] = useState('')
  const live = preview.mode === 'live'
  const allowed = !live || confirmation === 'INJECT LIVE FAULT'
  const selector = Object.entries(preview.selector).map(([key, value]) => `${key}=${value}`).join(', ')
  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className={`bg-surface border rounded-xl w-full max-w-xl shadow-2xl ${live ? 'border-danger/50' : 'border-accent/40'}`}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className={`w-9 h-9 rounded-lg grid place-items-center ${live ? 'bg-danger/15 text-danger' : 'bg-accent/15 text-accent'}`}>{live ? <AlertTriangle className="w-5 h-5" /> : <Shield className="w-5 h-5" />}</div>
            <div><p className={`font-mono text-[10px] font-bold tracking-widest ${live ? 'text-danger' : 'text-accent'}`}>{live ? 'LIVE K3S CHANGE' : 'SAFE SIMULATION'}</p><p className="font-semibold text-slate-200 text-sm">Review before execution</p></div>
          </div>
          <button onClick={onClose} disabled={executing} className="text-slate-500 hover:text-slate-300"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          <div className={`rounded-lg border px-4 py-3 text-xs leading-relaxed ${live ? 'border-danger/30 bg-danger/5 text-red-200' : 'border-accent/25 bg-accent/5 text-slate-300'}`}>{live ? 'This creates a genuine Chaos Mesh resource and temporarily affects a running workload. Phoenix will monitor, remediate, verify, and automatically clean it up.' : 'This registers a synthetic fault rule. It exercises detection and recovery logic without creating a Chaos Mesh resource or disrupting a Kubernetes workload.'}</div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border font-mono text-[11px]">
            {[
              ['Execution', live ? 'Chaos Mesh · observed' : 'Simulator · synthetic'],
              ['Fault', preview.faultType], ['Target', preview.targetName], ['Namespace', preview.namespace],
              ['Selector', selector || 'none'], ['Duration', `${preview.durationSeconds}s · automatic cleanup`],
              ['Blast radius', `${preview.affectedServices} downstream service${preview.affectedServices === 1 ? '' : 's'}`], ['Taxonomy', preview.taxonomy],
            ].map(([label, value]) => <div key={label} className="bg-card p-3"><span className="block text-slate-600 mb-1">{label}</span><b className="text-slate-300 break-all">{value}</b></div>)}
          </div>
          <p className="text-[11px] text-slate-500 leading-relaxed">{preview.description}</p>
          {live && <div><label className="block text-[10px] text-danger font-mono mb-1.5">Type INJECT LIVE FAULT to authorize this bounded cluster change</label><input autoFocus value={confirmation} onChange={event => setConfirmation(event.target.value)} className="input w-full font-mono text-xs" placeholder="INJECT LIVE FAULT" /></div>}
          <div className="flex gap-3 pt-1"><button onClick={onClose} disabled={executing} className="flex-1 btn-secondary text-xs">Cancel</button><button onClick={onConfirm} disabled={!allowed || executing} className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg border text-xs font-mono font-bold disabled:opacity-35 ${live ? 'bg-danger/15 border-danger/40 text-danger' : 'bg-accent/15 border-accent/30 text-accent'}`}>{executing ? <Loader2 className="w-4 h-4 animate-spin" /> : live ? <Zap className="w-4 h-4" /> : <Shield className="w-4 h-4" />}{executing ? 'Starting…' : live ? 'Inject Live Fault' : 'Run Safe Simulation'}</button></div>
        </div>
      </div>
    </div>
  )
}

function NotifyModal({ onClose }: { onClose: () => void }) {
  const saved = loadChannels()
  const [slack, setSlack] = useState(saved.slack ?? '')
  const [pd, setPd]       = useState(saved.pd ?? '')
  const [email, setEmail] = useState(saved.email ?? '')
  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-surface border border-border rounded-xl w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-2"><Bell className="w-4 h-4 text-accent" /><p className="font-semibold text-slate-200 text-sm">Notification Channels</p></div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          <p className="text-xs text-slate-500">
            Channels are saved locally and shown in each incident report. Live delivery requires the M2 agent backend.
          </p>
          {[
            { label: 'Slack Webhook URL', val: slack, set: setSlack, placeholder: 'https://hooks.slack.com/services/…' },
            { label: 'PagerDuty Integration Key', val: pd, set: setPd, placeholder: 'pdxxxxxxxxxxxxxx' },
            { label: 'Alert Email', val: email, set: setEmail, placeholder: 'oncall@yourorg.com' },
          ].map(({ label, val, set, placeholder }) => (
            <div key={label}>
              <label className="block text-[11px] text-slate-400 font-mono mb-1">{label}</label>
              <input value={val} onChange={e => set(e.target.value)} placeholder={placeholder} className="input w-full text-xs" />
            </div>
          ))}
          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 btn-secondary text-xs">Cancel</button>
            <button onClick={() => { localStorage.setItem(NOTIF_KEY, JSON.stringify({ slack, pd, email })); onClose() }} className="flex-1 btn-primary text-xs">Save channels</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function Incidents() {
  const { mutate }                       = useSWRConfig()
  const [injecting, setInjecting]        = useState(false)
  const [injectErr, setInjectErr]        = useState<string | null>(null)
  const [showNotify, setShowNotify]      = useState(false)
  const [preview, setPreview]            = useState<InjectionPreview | null>(null)
  const [preparing, setPreparing]        = useState<InjectionMode | null>(null)

  const { data: topo }                   = useSWR('topology',  fetchTopology, { refreshInterval: 30_000 })
  const { data: catalog = [] }           = useSWR('catalog',   fetchCatalog,  { revalidateOnFocus: false })
  const { data: scenarios = [], isLoading, isValidating } = useSWR('scenarios', fetchScenarios, { refreshInterval: 5_000 })

  const running = scenarios.filter(s => s.status === 'running')
  const past    = scenarios.filter(s => s.status !== 'running')
  const sorted  = [...running, ...past]

  async function openInjection(mode: InjectionMode) {
    setPreparing(mode); setInjectErr(null)
    try { setPreview(await prepareInjection(mode)) }
    catch (e) { setInjectErr(e instanceof Error ? e.message : String(e)) }
    finally { setPreparing(null) }
  }

  async function handleInject() {
    if (!preview) return
    setInjecting(true); setInjectErr(null)
    try { await executeInjection(preview); setPreview(null); mutate('scenarios') }
    catch (e) { setInjectErr(e instanceof Error ? e.message : String(e)) }
    finally { setInjecting(false) }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            Incident Feed
            {isValidating && !isLoading && <RefreshCw className="w-3.5 h-3.5 text-accent animate-spin" />}
          </h1>
          <p className="text-[11px] text-slate-600 mt-0.5 font-mono">
            Live fault detection · Phoenix Agent response · {topo ? `${topo.nodes.length} services in topology` : 'connecting to topology…'}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button onClick={() => setShowNotify(true)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-elevated border border-border text-slate-400 hover:text-slate-200 text-xs font-mono transition-colors">
            <Bell className="w-3.5 h-3.5" />
            Notify
          </button>
          <button onClick={() => openInjection('safe')} disabled={Boolean(preparing)||injecting} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 text-xs font-mono font-semibold transition-colors disabled:opacity-50">{preparing==='safe'?<Loader2 className="w-3.5 h-3.5 animate-spin"/>:<Shield className="w-3.5 h-3.5"/>}Run Safe Simulation</button>
          <button onClick={() => openInjection('live')} disabled={Boolean(preparing)||injecting} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-danger/10 border border-danger/30 text-danger hover:bg-danger/20 text-xs font-mono font-semibold transition-colors disabled:opacity-50">{preparing==='live'?<Loader2 className="w-3.5 h-3.5 animate-spin"/>:<Zap className="w-3.5 h-3.5"/>}Inject Live k3s Fault</button>
        </div>
      </div>

      {injectErr && (
        <div className="flex items-center gap-2 text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-4 py-3">
          <AlertTriangle className="w-4 h-4 shrink-0" />{injectErr}
        </div>
      )}

      {running.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-danger/40 bg-danger/5">
          <span className="relative flex h-2.5 w-2.5 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger opacity-60" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-danger" />
          </span>
          <p className="text-sm text-danger font-mono font-semibold">
            {running.length} active fault{running.length !== 1 ? 's' : ''} — Phoenix Agent is responding
          </p>
        </div>
      )}

      {isLoading && (
        <div className="space-y-3">
          {[1, 2].map(i => (
            <div key={i} className="rounded-xl border border-border bg-card p-4 space-y-3">
              <div className="skeleton h-4 w-64 rounded" /><div className="skeleton h-3 w-48 rounded" />
            </div>
          ))}
        </div>
      )}

      {!isLoading && sorted.length === 0 && (
        <div className="rounded-xl border border-border bg-card p-10 flex flex-col items-center gap-4 text-center">
          <div className="w-12 h-12 rounded-xl bg-elevated flex items-center justify-center">
            <Zap className="w-6 h-6 text-slate-600" />
          </div>
          <div>
            <p className="text-slate-300 font-semibold">No incidents yet</p>
            <p className="text-xs text-slate-600 mt-1 max-w-sm">
              Start with <span className="text-accent font-mono">Run Safe Simulation</span> for a synthetic incident, or explicitly preview and authorize a <span className="text-danger font-mono">Live k3s Fault</span>.
              Phoenix opens the incident here with a live activity stream, blast radius, response, and verified outcome.
            </p>
          </div>
        </div>
      )}

      {!isLoading && (
        <div className="space-y-3">
          {sorted.map(s => (
            <IncidentCard
              key={s.id}
              scenario={s}
              catalog={catalog}
              onStop={async () => { await stopScenario(s.id); mutate('scenarios') }}
            />
          ))}
        </div>
      )}

      {showNotify      && <NotifyModal onClose={() => setShowNotify(false)} />}
      {preview && <InjectionConfirmModal preview={preview} onConfirm={handleInject} onClose={() => !injecting&&setPreview(null)} executing={injecting} />}
    </div>
  )
}
