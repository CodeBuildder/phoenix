import { useEffect, useState } from 'react'
import useSWR from 'swr'
import { fetchScenarios, stopScenario } from '../api/chaos'
import { fetchBlastRadius } from '../api/graph'
import { fetchRankings } from '../api/faultlib'
import { fetchRuns, fetchMemory, approveAction, rejectAction, type AgentRun, type AgentNode, type MemoryRecord } from '../api/agent'
import type { Scenario } from '../types/chaos'
import type { BlastRadiusResponse, AffectedNode } from '../types/graph'
import type { ComponentRanking } from '../types/faultlib'
import {
  Activity, AlertTriangle, CheckCircle2, ChevronRight, Clock,
  Loader2, RefreshCw, Shield, Square, Zap, ThumbsUp, ThumbsDown,
  Brain, Wrench, Database, TrendingDown, TrendingUp,
} from 'lucide-react'

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtSec(s: number) {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

function elapsed(iso: string | null): number {
  if (!iso) return 0
  return Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
}

function mttr(scenario: Scenario): number | null {
  if (!scenario.started_at || !scenario.stopped_at) return null
  return Math.floor(
    (new Date(scenario.stopped_at).getTime() - new Date(scenario.started_at).getTime()) / 1000,
  )
}

function incidentSeverity(affected: AffectedNode[]): 'critical' | 'high' | 'medium' | 'low' {
  if (affected.some(n => n.severity === 'high' && n.distance_hops === 1)) return 'critical'
  if (affected.some(n => n.severity === 'high'))   return 'high'
  if (affected.some(n => n.severity === 'medium')) return 'medium'
  return 'low'
}

function needsHuman(sev: string, affected: AffectedNode[]) {
  return sev === 'critical' || (sev === 'high' && affected.length >= 3)
}

// ── lane types ────────────────────────────────────────────────────────────────

type Lane = 'detect' | 'diagnose' | 'heal' | 'approve' | 'verify'

// Map real agent node → swim-lane column
const AGENT_NODE_TO_LANE: Record<AgentNode, Lane> = {
  detect:    'detect',
  diagnose:  'diagnose',
  heal_plan: 'heal',
  execute:   'heal',
  approve:   'approve',
  verify:    'verify',
  report:    'verify',
  done:      'verify',
  aborted:   'verify',
  error:     'verify',
}

function computeLane(
  scenario: Scenario,
  blast: BlastRadiusResponse | undefined,
  blastLoading: boolean,
  agentRun: AgentRun | null,
): Lane {
  // Real agent data takes priority over timing heuristic
  if (agentRun) return AGENT_NODE_TO_LANE[agentRun.node] ?? 'detect'

  // Heuristic fallback (no agent run yet)
  if (['completed', 'stopped', 'failed'].includes(scenario.status)) return 'verify'
  if (scenario.status !== 'running') return 'detect'
  if (blastLoading || blast === undefined) return 'detect'

  const affected = blast.affected_nodes ?? []
  const sev      = incidentSeverity(affected)
  if (needsHuman(sev, affected)) return 'approve'
  return elapsed(scenario.started_at) < 30 ? 'diagnose' : 'heal'
}

const LANE_META: Record<Lane, {
  label:    string
  sublabel: string
  color:    string
  border:   string
  dot:      string
}> = {
  detect: {
    label: 'Detect',
    sublabel: 'Scanning topology',
    color:  'text-slate-400',
    border: 'border-slate-700',
    dot:    'bg-slate-600',
  },
  diagnose: {
    label: 'Diagnose',
    sublabel: 'Analyzing impact',
    color:  'text-violet',
    border: 'border-violet/30',
    dot:    'bg-violet',
  },
  heal: {
    label: 'Heal',
    sublabel: 'Phoenix responding',
    color:  'text-accent',
    border: 'border-accent/30',
    dot:    'bg-accent',
  },
  approve: {
    label: 'Approve',
    sublabel: 'Human gate — action required',
    color:  'text-danger',
    border: 'border-danger/40',
    dot:    'bg-danger',
  },
  verify: {
    label: 'Verify',
    sublabel: 'Confirming recovery',
    color:  'text-cyan',
    border: 'border-cyan/30',
    dot:    'bg-cyan',
  },
}

const SEV_TEXT: Record<string, string> = {
  critical: 'text-danger', high: 'text-warning', medium: 'text-accent', low: 'text-slate-400',
}

function extractServiceName(scenario: Scenario): string {
  const labels = scenario.target.label_selector ?? {}
  const app = labels['app'] ?? labels['name'] ?? labels['component'] ?? null
  if (app) return app
  const parts = scenario.name.split('-')
  if (parts[0] === 'incident' && parts.length > 3)
    return parts.slice(1, -1).join('-').replace(/-\d{10,}$/, '')
  return scenario.name
}

function useTick(scenario: Scenario) {
  const [, forceUpdate] = useState(0)
  useEffect(() => {
    if (scenario.status !== 'running') return
    const id = setInterval(() => forceUpdate(n => n + 1), 1000)
    return () => clearInterval(id)
  }, [scenario.status])
}

// ── node → pipeline depth (0–4) ──────────────────────────────────────────────

const NODE_DEPTH: Record<AgentNode, number> = {
  detect: 0, diagnose: 1, heal_plan: 2, approve: 2,
  execute: 3, verify: 3, report: 4, done: 4, aborted: 2, error: -1,
}
const STAGE_LABELS = ['Detect', 'Diagnose', 'Heal', 'Verify', 'Done']

// ── command center ────────────────────────────────────────────────────────────

function CommandCenter({
  agentRuns,
  memoryRecords,
  running,
  agentOnline,
}: {
  agentRuns:     AgentRun[]
  memoryRecords: MemoryRecord[]
  running:       number
  agentOnline:   boolean
}) {
  const done    = agentRuns.filter(r => r.node === 'done')
  const failed  = agentRuns.filter(r => r.node === 'error' || r.node === 'aborted')
  const inFlight = agentRuns.filter(r => !['done', 'error', 'aborted'].includes(r.node))
  const total   = agentRuns.length

  const mttrs   = done.filter(r => r.mttr_seconds != null).map(r => r.mttr_seconds as number)
  const avgMttr = mttrs.length ? Math.round(mttrs.reduce((a,b) => a+b,0) / mttrs.length) : null
  const autoRate = total > 0 ? Math.round((done.length / total) * 100) : null

  // Last 12 completed runs for MTTR sparkline
  const sparkRuns = [...done.filter(r => r.mttr_seconds != null)]
    .sort((a,b) => (a.started_at > b.started_at ? 1 : -1))
    .slice(-12)
  const sparkMax  = Math.max(...sparkRuns.map(r => r.mttr_seconds as number), 1)

  // Memory intelligence: group by fault_type
  const memByFault = new Map<string, MemoryRecord[]>()
  for (const r of memoryRecords) {
    const list = memByFault.get(r.fault_type) ?? []
    list.push(r)
    memByFault.set(r.fault_type, list)
  }
  const intelRows = [...memByFault.entries()]
    .map(([ft, recs]) => {
      const success = recs.filter(r => r.outcome === 'success').length
      const conf    = Math.round((success / recs.length) * 100)
      const bestAction = recs.filter(r => r.outcome === 'success')[0]?.action_taken ?? recs[0]?.action_taken
      return { ft, count: recs.length, success, conf, bestAction }
    })
    .sort((a,b) => b.count - a.count)
    .slice(0, 4)

  return (
    <div className="grid grid-cols-3 gap-3">

      {/* ── left: live telemetry ──────────────────────────────────────── */}
      <div className="bg-card border border-border rounded-xl p-4 space-y-4">
        {/* status row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              {agentOnline && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
              )}
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${agentOnline ? 'bg-accent' : 'bg-slate-600'}`} />
            </span>
            <span className={`text-xs font-mono font-bold ${agentOnline ? 'text-accent' : 'text-slate-500'}`}>
              {agentOnline ? 'AGENT LIVE' : 'AGENT OFFLINE'}
            </span>
          </div>
          {inFlight.length > 0 && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-danger/10 border border-danger/20 text-[10px] font-mono text-danger">
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
              {inFlight.length} in flight
            </span>
          )}
        </div>

        {/* metrics grid */}
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: 'PIPELINE RUNS',   value: total,                           sub: `${running} scenarios active`,      color: 'text-slate-100' },
            { label: 'AUTO-RESOLVED',   value: autoRate != null ? `${autoRate}%` : '—', sub: `${done.length} of ${total} done`, color: autoRate != null && autoRate >= 80 ? 'text-accent' : autoRate != null && autoRate >= 50 ? 'text-warning' : 'text-slate-400' },
            { label: 'AVG MTTR',        value: avgMttr != null ? fmtSec(avgMttr) : '—', sub: `${mttrs.length} samples`,   color: 'text-violet' },
            { label: 'MEMORY DEPTH',    value: memoryRecords.length,            sub: `${memByFault.size} fault patterns`, color: 'text-cyan' },
          ].map(m => (
            <div key={m.label} className="bg-elevated/40 rounded-lg px-3 py-2.5">
              <p className="text-[9px] font-mono text-slate-600 uppercase tracking-widest">{m.label}</p>
              <p className={`text-lg font-mono font-bold mt-0.5 ${m.color}`}>{m.value}</p>
              <p className="text-[9px] font-mono text-slate-700 mt-0.5 truncate">{m.sub}</p>
            </div>
          ))}
        </div>

        {/* failed/aborted count */}
        {failed.length > 0 && (
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-danger/5 border border-danger/15 text-[10px] font-mono text-danger/80">
            <AlertTriangle className="w-3 h-3 shrink-0" />
            {failed.length} run{failed.length !== 1 ? 's' : ''} errored or aborted — check logs
          </div>
        )}
      </div>

      {/* ── middle: MTTR run history ──────────────────────────────────── */}
      <div className="bg-card border border-border rounded-xl p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">MTTR History</p>
            <p className="text-[9px] font-mono text-slate-700 mt-0.5">Time-to-recover per completed run</p>
          </div>
          {avgMttr != null && (
            <div className="flex items-center gap-1 text-[10px] font-mono text-violet">
              <Clock className="w-3 h-3" />
              avg {fmtSec(avgMttr)}
            </div>
          )}
        </div>

        {sparkRuns.length === 0 ? (
          <div className="flex-1 flex items-center justify-center h-24 text-[10px] font-mono text-slate-700">
            No completed runs yet
          </div>
        ) : (
          <div className="space-y-2">
            {/* bar chart */}
            <div className="flex items-end gap-1 h-20">
              {sparkRuns.map((r, i) => {
                const pct = ((r.mttr_seconds as number) / sparkMax) * 100
                const isLast = i === sparkRuns.length - 1
                return (
                  <div key={r.scenario_id} className="flex-1 flex flex-col items-center gap-0.5 group relative">
                    <div
                      className={`w-full rounded-sm transition-all ${isLast ? 'bg-accent' : 'bg-violet/40 group-hover:bg-violet/70'}`}
                      style={{ height: `${Math.max(pct, 4)}%` }}
                    />
                    {/* tooltip */}
                    <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:flex flex-col items-center z-10">
                      <div className="bg-elevated border border-border rounded px-1.5 py-1 text-[9px] font-mono text-slate-300 whitespace-nowrap">
                        {fmtSec(r.mttr_seconds as number)}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
            {/* x-axis labels */}
            <div className="flex justify-between text-[8px] font-mono text-slate-700">
              <span>oldest</span>
              <span className="text-accent">latest</span>
            </div>
          </div>
        )}

        {/* recent run pipeline pills */}
        <div className="space-y-1.5 border-t border-border/30 pt-2.5">
          <p className="text-[9px] font-mono text-slate-700 uppercase tracking-widest">Recent runs</p>
          {agentRuns.slice(0, 4).map(r => {
            const depth  = NODE_DEPTH[r.node] ?? -1
            const svc    = (r.scenario as { name?: string }).name?.replace(/^incident-/, '').replace(/-\d{10,}$/, '') ?? r.scenario_id.slice(0, 12)
            const isDone = r.node === 'done'
            const isErr  = r.node === 'error' || r.node === 'aborted'
            return (
              <div key={r.scenario_id} className="flex items-center gap-2">
                <p className="text-[9px] font-mono text-slate-500 truncate w-24 shrink-0">{svc}</p>
                {/* stage dots */}
                <div className="flex items-center gap-0.5 flex-1">
                  {STAGE_LABELS.map((_, i) => (
                    <div
                      key={i}
                      className={`flex-1 h-1 rounded-full ${
                        isErr && depth === i ? 'bg-danger' :
                        i <= depth ? (isDone ? 'bg-accent' : 'bg-violet') : 'bg-elevated'
                      }`}
                    />
                  ))}
                </div>
                <span className={`text-[9px] font-mono shrink-0 ${isDone ? 'text-accent' : isErr ? 'text-danger' : 'text-slate-600 animate-pulse'}`}>
                  {r.node}
                </span>
              </div>
            )
          })}
          {agentRuns.length === 0 && (
            <p className="text-[10px] font-mono text-slate-700">No runs yet</p>
          )}
        </div>
      </div>

      {/* ── right: Phoenix intelligence ───────────────────────────────── */}
      <div className="bg-card border border-border rounded-xl p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Brain className="w-3.5 h-3.5 text-violet" />
          <div>
            <p className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">Phoenix Intelligence</p>
            <p className="text-[9px] font-mono text-slate-700 mt-0.5">Learned from {memoryRecords.length} past incident{memoryRecords.length !== 1 ? 's' : ''}</p>
          </div>
        </div>

        {intelRows.length === 0 ? (
          <div className="flex-1 flex items-center justify-center h-24 text-center text-[10px] font-mono text-slate-700 leading-relaxed">
            Memory builds as Phoenix resolves incidents.<br />
            Inject faults to start learning.
          </div>
        ) : (
          <div className="space-y-2">
            {intelRows.map(row => (
              <div key={row.ft} className="bg-elevated/30 rounded-lg px-3 py-2 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-slate-300 font-semibold">{row.ft}</span>
                  <div className="flex items-center gap-1">
                    {row.conf >= 80 ? (
                      <TrendingUp className="w-3 h-3 text-accent" />
                    ) : row.conf >= 50 ? (
                      <TrendingDown className="w-3 h-3 text-warning" />
                    ) : (
                      <TrendingDown className="w-3 h-3 text-danger" />
                    )}
                    <span className={`text-[10px] font-mono font-bold ${
                      row.conf >= 80 ? 'text-accent' : row.conf >= 50 ? 'text-warning' : 'text-danger'
                    }`}>{row.conf}%</span>
                  </div>
                </div>
                {/* confidence bar */}
                <div className="h-1 bg-elevated rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      row.conf >= 80 ? 'bg-accent' : row.conf >= 50 ? 'bg-warning' : 'bg-danger'
                    }`}
                    style={{ width: `${row.conf}%` }}
                  />
                </div>
                <div className="flex items-center justify-between text-[9px] font-mono text-slate-600">
                  <span>{row.count}× seen · {row.success}/{row.count} resolved</span>
                  <span className="text-slate-500 truncate ml-2">{row.bestAction}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {memoryRecords.length > 0 && (
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-violet/5 border border-violet/15 text-[9px] font-mono text-slate-600">
            <Database className="w-3 h-3 text-violet shrink-0" />
            Confidence scores fed into OpenAI's diagnose prompt on every new incident
          </div>
        )}
      </div>
    </div>
  )
}

// ── lane card ─────────────────────────────────────────────────────────────────

function LaneCard({
  scenario,
  column,
  agentRun,
  onMutate,
}: {
  scenario:  Scenario
  column:    Lane
  agentRun:  AgentRun | null
  onMutate:  () => void
}) {
  const [expanded, setExpanded]   = useState(false)
  const [stopping, setStopping]   = useState(false)
  const [approving, setApproving] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  useTick(scenario)

  const target = scenario.target
  const { data: blast, isLoading: blastLoading } = useSWR(
    target.namespace ? `blast-agent/${scenario.id}/${target.namespace}` : null,
    () => fetchBlastRadius(target.namespace!, scenario.fault_type, target.label_selector ?? {}),
    { refreshInterval: scenario.status === 'running' ? 10_000 : 0, dedupingInterval: 5_000 },
  )

  const currentLane = computeLane(scenario, blast, blastLoading, agentRun)
  if (currentLane !== column) return null

  const affected  = blast?.affected_nodes ?? []
  const matched   = blast?.matched_nodes  ?? []
  const sev       = affected.length > 0 ? incidentSeverity(affected) : 'low'
  const human     = needsHuman(sev, affected)
  const age       = elapsed(scenario.started_at)
  const remaining = scenario.duration_seconds ? Math.max(scenario.duration_seconds - age, 0) : null
  const service   = extractServiceName(scenario)
  const m         = agentRun?.mttr_seconds ?? mttr(scenario)
  const meta      = LANE_META[column]

  const diagnosis  = agentRun?.diagnosis
  const isPending  = agentRun?.approval_status === 'pending'

  async function handleApprove() {
    setApproving(true)
    try { await approveAction(scenario.id); onMutate() } finally { setApproving(false) }
  }
  async function handleReject() {
    setRejecting(true)
    try { await rejectAction(scenario.id); onMutate() } finally { setRejecting(false) }
  }

  const endedAt = scenario.stopped_at
    ? new Date(scenario.stopped_at).toLocaleTimeString()
    : null

  return (
    <div className={`rounded-lg border bg-card text-[11px] font-mono ${meta.border}`}>
      {/* header — clickable to expand */}
      <div
        className="flex items-start gap-2 p-3 cursor-pointer select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="relative flex h-2 w-2 mt-0.5 shrink-0">
          {scenario.status === 'running' && (
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${meta.dot} opacity-50`} />
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${meta.dot}`} />
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-slate-200 font-semibold truncate">{service}</p>
          <p className="text-slate-600 text-[10px] truncate">{scenario.fault_type} · {scenario.domain}</p>
        </div>
        {sev !== 'low' && (
          <span className={`text-[10px] font-bold uppercase shrink-0 ${SEV_TEXT[sev]}`}>{sev}</span>
        )}
        <span className="text-slate-700 text-[10px] shrink-0 ml-1">{expanded ? '▲' : '▼'}</span>
      </div>

      {/* collapsed summary */}
      {!expanded && (
        <div className="px-3 pb-2.5 text-[10px] text-slate-600 border-t border-border/20 pt-2">
          {scenario.status === 'running' ? `${fmtSec(age)} elapsed` : endedAt ? `ended ${endedAt}` : scenario.status}
          {m !== null && <span className="ml-2 text-slate-700">MTTR {fmtSec(m)}</span>}
          {agentRun && <span className="ml-2 text-accent/50">{agentRun.node}</span>}
        </div>
      )}

      {/* expanded detail */}
      {expanded && (
      <div className="px-3 pb-3 space-y-2.5 border-t border-border/20 pt-2.5">

      {/* ── DETECT ──────────────────────────────────────────────────── */}
      {column === 'detect' && (
        <div className="flex items-center gap-1.5 text-slate-600">
          <Loader2 className="w-3 h-3 animate-spin" />
          {agentRun ? 'Phoenix Agent detecting…' : 'Scanning topology for blast radius…'}
        </div>
      )}

      {/* ── DIAGNOSE ────────────────────────────────────────────────── */}
      {column === 'diagnose' && (
        <div className="space-y-1.5">
          {diagnosis ? (
            <>
              <div className="flex items-center gap-1.5 text-violet">
                <Brain className="w-3 h-3" />
                Causal chain
              </div>
              <p className="text-slate-400 text-[10px] leading-relaxed border-l-2 border-violet/30 pl-2">
                {diagnosis.causal_chain}
              </p>
              <div className="flex items-center gap-1.5 pt-1 border-t border-border/40">
                <span className="text-slate-600">→</span>
                <span className="text-accent">{diagnosis.recommended_action}</span>
                <span className={`ml-auto text-[9px] uppercase font-bold ${
                  diagnosis.risk === 'high' ? 'text-danger' : 'text-accent'
                }`}>
                  {diagnosis.risk}-risk
                </span>
              </div>
            </>
          ) : (
            <>
              <p className="text-violet/80">Blast radius mapped</p>
              {affected.length > 0 ? (
                <>
                  <p className="text-slate-500">
                    {affected.length} downstream service{affected.length !== 1 ? 's' : ''} at risk:
                  </p>
                  {affected.slice(0, 3).map(n => (
                    <div key={n.node_id} className="flex items-center gap-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        n.severity === 'high' ? 'bg-danger' : n.severity === 'medium' ? 'bg-warning' : 'bg-accent'
                      }`} />
                      <span className="text-slate-400 truncate">{n.name}</span>
                      <span className={`ml-auto shrink-0 ${SEV_TEXT[n.severity]}`}>{n.severity}</span>
                    </div>
                  ))}
                </>
              ) : (
                <p className="text-accent text-[10px]">✓ No downstream impact — fault contained</p>
              )}
              <div className="flex items-center gap-1.5 text-slate-700 border-t border-border/40 pt-1.5 mt-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                OpenAI analyzing causal chain…
              </div>
            </>
          )}
        </div>
      )}

      {/* ── HEAL ────────────────────────────────────────────────────── */}
      {column === 'heal' && (
        <div className="space-y-1.5">
          {agentRun?.node === 'execute' ? (
            <>
              <div className="flex items-center gap-1.5 text-accent">
                <Wrench className="w-3 h-3 animate-pulse" />
                Executing remediation…
              </div>
              {diagnosis && (
                <p className="text-slate-500">
                  Action: <span className="text-accent">{diagnosis.recommended_action}</span>
                  {' → '}<span className="text-slate-400">{diagnosis.action_target}</span>
                </p>
              )}
            </>
          ) : agentRun?.action_result ? (
            <>
              <div className="flex items-center gap-1.5 text-accent">
                <CheckCircle2 className="w-3 h-3" />
                Action complete
              </div>
              <p className="text-slate-500 text-[10px] leading-relaxed border-l-2 border-accent/30 pl-2">
                {agentRun.action_result}
              </p>
            </>
          ) : (
            <>
              <div className="flex items-center gap-1.5 text-accent">
                <Activity className="w-3 h-3" />
                Phoenix Agent monitoring
              </div>
              {diagnosis && (
                <p className="text-slate-500">
                  Planned: <span className="text-accent">{diagnosis.recommended_action}</span>
                </p>
              )}
              {remaining !== null && (
                <p className="text-slate-600">Auto-stops in {fmtSec(remaining)}</p>
              )}
              {matched.length > 0 && (
                <p className="text-slate-600">{matched.length} service{matched.length !== 1 ? 's' : ''} targeted</p>
              )}
            </>
          )}
        </div>
      )}

      {/* ── APPROVE ─────────────────────────────────────────────────── */}
      {column === 'approve' && (
        <div className="space-y-2">
          {isPending && diagnosis ? (
            <>
              <div className="flex items-center gap-1.5 text-danger">
                <AlertTriangle className="w-3 h-3" />
                High-risk action — approval required
              </div>
              <div className="space-y-1 text-[10px] text-slate-500 border-l-2 border-danger/30 pl-2">
                <p>Action: <span className="text-slate-300">{diagnosis.recommended_action}</span></p>
                <p>Target: <span className="text-slate-300">{diagnosis.action_target}</span></p>
                <p className="text-slate-600">{diagnosis.rationale}</p>
              </div>
              <div className="flex gap-1.5 pt-1">
                <button
                  onClick={handleApprove}
                  disabled={approving}
                  className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 transition-colors disabled:opacity-50"
                >
                  {approving ? <Loader2 className="w-3 h-3 animate-spin" /> : <ThumbsUp className="w-3 h-3" />}
                  Approve
                </button>
                <button
                  onClick={handleReject}
                  disabled={rejecting}
                  className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded bg-danger/10 border border-danger/30 text-danger hover:bg-danger/20 transition-colors disabled:opacity-50"
                >
                  {rejecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <ThumbsDown className="w-3 h-3" />}
                  Reject
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center gap-1.5 text-danger">
                <AlertTriangle className="w-3 h-3" />
                {agentRun ? 'Awaiting approval decision' : `Blast radius is ${sev} — operator required`}
              </div>
              {affected.length > 0 && (
                <p className="text-slate-500">
                  {affected.length} service{affected.length !== 1 ? 's' : ''} at risk
                </p>
              )}
              {!agentRun && human && (
                <button
                  onClick={async () => {
                    setStopping(true)
                    await stopScenario(scenario.id)
                    setStopping(false)
                  }}
                  disabled={stopping}
                  className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded bg-danger/10 border border-danger/30 text-danger hover:bg-danger/20 transition-colors disabled:opacity-50"
                >
                  {stopping ? <Loader2 className="w-3 h-3 animate-spin" /> : <Square className="w-3 h-3" />}
                  Stop fault
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* ── VERIFY ──────────────────────────────────────────────────── */}
      {column === 'verify' && (
        <div className="space-y-1.5">
          {agentRun?.verify_result ? (
            <>
              <div className="flex items-center gap-1.5 text-cyan">
                <Shield className="w-3 h-3" />
                Verification complete
              </div>
              <p className="text-slate-500 text-[10px] leading-relaxed border-l-2 border-cyan/30 pl-2">
                {agentRun.verify_result}
              </p>
            </>
          ) : (
            <>
              {scenario.status === 'completed' && (
                <div className="flex items-center gap-1.5 text-accent">
                  <CheckCircle2 className="w-3 h-3" />
                  Fault expired — services recovering
                </div>
              )}
              {scenario.status === 'stopped' && (
                <div className="flex items-center gap-1.5 text-slate-400">
                  <CheckCircle2 className="w-3 h-3" />
                  Stopped — verifying
                </div>
              )}
              {scenario.status === 'failed' && (
                <div className="flex items-center gap-1.5 text-danger">
                  <AlertTriangle className="w-3 h-3" />
                  Scenario failed — review logs
                </div>
              )}
              {agentRun?.node === 'aborted' && (
                <div className="flex items-center gap-1.5 text-warning">
                  <AlertTriangle className="w-3 h-3" />
                  Aborted — approval rejected or timed out
                </div>
              )}
            </>
          )}
          {m !== null && (
            <div className="flex items-center gap-1.5 text-slate-600">
              <Clock className="w-3 h-3" />
              MTTR: {fmtSec(m)}
            </div>
          )}
          {affected.length > 0 && (
            <p className="text-slate-600 text-[10px]">
              Recover: {affected.slice(0, 2).map(n=>n.name).join(', ')}
              {affected.length > 2 ? ` +${affected.length - 2} more` : ''}
            </p>
          )}

          {/* full detail rows */}
          <div className="space-y-1 text-[10px] border-t border-border/30 pt-1.5 mt-0.5">
            <div className="flex justify-between text-slate-600">
              <span>Fault injected</span>
              <span className="text-slate-400">{scenario.fault_type}</span>
            </div>
            <div className="flex justify-between text-slate-600">
              <span>Domain</span>
              <span className="text-slate-400">{scenario.domain}</span>
            </div>
            {scenario.duration_seconds && (
              <div className="flex justify-between text-slate-600">
                <span>Duration</span>
                <span className="text-slate-400">{fmtSec(scenario.duration_seconds)}</span>
              </div>
            )}
            <div className="flex justify-between text-slate-600">
              <span>How it ended</span>
              <span className="text-slate-400">{
                scenario.status === 'completed' ? 'auto (duration)' :
                scenario.status === 'stopped'   ? 'manual stop' :
                scenario.status === 'failed'    ? 'error' : scenario.status
              }</span>
            </div>
            {affected.length > 0 && (
              <div className="mt-1 space-y-0.5">
                <p className="text-slate-700 uppercase tracking-widest text-[9px]">Affected services</p>
                {affected.map(n => (
                  <div key={n.node_id} className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      n.severity === 'high' ? 'bg-danger' : n.severity === 'medium' ? 'bg-warning' : 'bg-accent'
                    }`} />
                    <span className="text-slate-400 truncate flex-1">{n.name}</span>
                    <span className={`shrink-0 ${SEV_TEXT[n.severity]}`}>{n.severity}</span>
                    <span className="text-slate-700">{n.distance_hops}h</span>
                  </div>
                ))}
              </div>
            )}
            {agentRun?.diagnosis && (
              <div className="mt-1 pt-1 border-t border-border/30 space-y-0.5">
                <p className="text-slate-700 uppercase tracking-widest text-[9px]">Phoenix diagnosis</p>
                <p className="text-slate-500 leading-relaxed">{agentRun.diagnosis.causal_chain}</p>
                <p className="text-slate-600">
                  Action: <span className="text-accent">{agentRun.diagnosis.recommended_action}</span>
                  {' → '}<span className="text-slate-400">{agentRun.diagnosis.action_target}</span>
                </p>
                {agentRun.action_result && (
                  <p className="text-accent/70">{agentRun.action_result}</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* footer */}
      <div className="text-[10px] text-slate-700 border-t border-border/30 pt-1.5 mt-1">
        {scenario.started_at && (
          scenario.status === 'running'
            ? `${fmtSec(age)} elapsed`
            : endedAt ? `ended ${endedAt}` : scenario.status
        )}
        {m !== null && <span className="ml-2 text-slate-600">MTTR {fmtSec(m)}</span>}
        {agentRun && <span className="ml-2 text-accent/60">agent: {agentRun.node}</span>}
      </div>

      </div>
      )}
    </div>
  )
}

// ── swim lane column ──────────────────────────────────────────────────────────

function LaneColumn({
  lane,
  scenarios,
  agentRunMap,
  onMutate,
}: {
  lane:         Lane
  scenarios:    Scenario[]
  agentRunMap:  Map<string, AgentRun>
  onMutate:     () => void
}) {
  const meta = LANE_META[lane]

  return (
    <div className="flex flex-col min-w-0">
      <div className={`flex items-center gap-2 px-3 py-2.5 rounded-t-lg border-t border-l border-r bg-elevated/40 ${meta.border}`}>
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${meta.dot}`} />
        <div className="min-w-0">
          <p className={`text-xs font-mono font-bold ${meta.color}`}>{meta.label}</p>
          <p className="text-[10px] font-mono text-slate-700 truncate">{meta.sublabel}</p>
        </div>
      </div>
      <div className={`flex-1 border-l border-r border-b rounded-b-lg p-2 space-y-2 min-h-[120px] ${meta.border} bg-surface/30`}>
        {scenarios.map(s => (
          <LaneCard
            key={s.id}
            scenario={s}
            column={lane}
            agentRun={agentRunMap.get(s.id) ?? null}
            onMutate={onMutate}
          />
        ))}
      </div>
    </div>
  )
}

// ── failure-mode rankings ─────────────────────────────────────────────────────

function FailureModeRankings({ rankings, total }: { rankings: ComponentRanking[]; total: number }) {
  const sorted = [...rankings]
    .filter(r => r.tallies != null)
    .sort((a, b) => (b.tallies?.total ?? 0) - (a.tallies?.total ?? 0))
  const maxTotal = sorted[0]?.tallies?.total ?? 1

  const CATEGORY_COLOR: Record<string, string> = {
    cascading:           'bg-danger/60',
    network_partition:   'bg-warning/60',
    resource_exhaustion: 'bg-violet/60',
    transient:           'bg-accent/60',
    quota_limit:         'bg-cyan/60',
  }
  const CATEGORY_LABEL: Record<string, string> = {
    cascading:           'Cascading',
    network_partition:   'Net partition',
    resource_exhaustion: 'Resource exhaustion',
    transient:           'Transient',
    quota_limit:         'Quota',
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest">Fleet Weakness Map</p>
          <p className="text-[10px] font-mono text-slate-700 mt-0.5">
            Ranked by fault exposure · {total} scenario{total !== 1 ? 's' : ''} analyzed
          </p>
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono text-slate-700 flex-wrap justify-end">
          {Object.entries(CATEGORY_LABEL).map(([k, v]) => (
            <span key={k} className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-sm ${CATEGORY_COLOR[k]}`} />
              {v}
            </span>
          ))}
        </div>
      </div>

      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <table className="w-full table-fixed">
          <colgroup>
            <col style={{ width: '5%' }} />
            <col style={{ width: '22%' }} />
            <col style={{ width: '43%' }} />
            <col style={{ width: '15%' }} />
            <col style={{ width: '15%' }} />
          </colgroup>
          <thead>
            <tr className="border-b border-border bg-elevated/30">
              <th className="text-left py-2.5 px-3 text-[10px] font-mono text-slate-600 uppercase tracking-widest">#</th>
              <th className="text-left py-2.5 px-3 text-[10px] font-mono text-slate-600 uppercase tracking-widest">Component</th>
              <th className="text-left py-2.5 px-3 text-[10px] font-mono text-slate-600 uppercase tracking-widest">Fault distribution</th>
              <th className="text-left py-2.5 px-3 text-[10px] font-mono text-slate-600 uppercase tracking-widest">Domain</th>
              <th className="text-center py-2.5 px-3 text-[10px] font-mono text-slate-600 uppercase tracking-widest">Total</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => {
              const t = r.tallies ?? {}
              const segments = [
                { key: 'cascading',           val: t.cascading           ?? 0 },
                { key: 'network_partition',    val: t.network_partition    ?? 0 },
                { key: 'resource_exhaustion',  val: t.resource_exhaustion  ?? 0 },
                { key: 'transient',            val: t.transient            ?? 0 },
                { key: 'quota_limit',          val: t.quota_limit          ?? 0 },
              ].filter(s => s.val > 0)

              return (
                <tr key={`${r.component}-${r.domain}`} className="border-b border-border/50 hover:bg-elevated/20">
                  <td className="py-3 px-3">
                    <span className={`text-[11px] font-mono font-bold ${
                      i === 0 ? 'text-danger' : i === 1 ? 'text-warning' : 'text-slate-500'
                    }`}>{i + 1}</span>
                  </td>
                  <td className="py-3 px-3">
                    <p className="text-[11px] font-mono text-slate-200 font-semibold truncate">{r.component}</p>
                  </td>
                  <td className="py-3 px-3">
                    <div className="flex items-center gap-1">
                      <div className="flex-1 h-3 rounded overflow-hidden bg-elevated flex">
                        {segments.map(s => (
                          <div
                            key={s.key}
                            className={`h-full ${CATEGORY_COLOR[s.key]} transition-all`}
                            style={{ width: `${(s.val / maxTotal) * 100}%` }}
                            title={`${CATEGORY_LABEL[s.key]}: ${s.val}`}
                          />
                        ))}
                      </div>
                      <div className="flex gap-1.5 ml-2 text-[9px] font-mono text-slate-600 shrink-0">
                        {segments.map(s => (
                          <span key={s.key} title={CATEGORY_LABEL[s.key]}>{s.val}</span>
                        ))}
                      </div>
                    </div>
                  </td>
                  <td className="py-3 px-3">
                    <span className="text-[10px] font-mono text-slate-500">{r.domain}</span>
                  </td>
                  <td className="py-3 px-3 text-center">
                    <span className={`text-[11px] font-mono font-bold ${
                      i === 0 ? 'text-danger' : i === 1 ? 'text-warning' : 'text-slate-400'
                    }`}>{t.total}</span>
                  </td>
                </tr>
              )
            })}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-[11px] font-mono text-slate-600">
                  No scenarios yet. Inject faults from the Incidents page to build the fleet weakness map.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

const LANES: Lane[] = ['detect', 'diagnose', 'heal', 'approve', 'verify']

export default function Agent() {
  const { data: scenarios = [], isLoading, isValidating, mutate: mutateScenarios } = useSWR(
    'scenarios', fetchScenarios, { refreshInterval: 5_000 },
  )
  const { data: agentRuns = [], error: agentError, mutate: mutateRuns } = useSWR(
    'agent-runs', fetchRuns,
    { refreshInterval: 5_000, onErrorRetry: (_, __, ___, revalidate, { retryCount }) => {
      if (retryCount >= 2) return
      setTimeout(() => revalidate({ retryCount }), 5000)
    }},
  )
  const { data: rankingsData, error: rankingsError } = useSWR(
    'rankings', fetchRankings, { revalidateOnFocus: false },
  )
  const { data: memoryRecords = [] } = useSWR(
    'agent-memory', fetchMemory, { refreshInterval: 30_000,
      onErrorRetry: (_, __, ___, revalidate, { retryCount }) => {
        if (retryCount >= 2) return
        setTimeout(() => revalidate({ retryCount }), 10_000)
      },
    },
  )

  const agentRunMap = new Map<string, AgentRun>(agentRuns.map(r => [r.scenario_id, r]))
  const agentOnline = !agentError

  function onMutate() { mutateRuns(); mutateScenarios() }

  const running  = scenarios.filter(s => s.status === 'running').length
  const resolved = scenarios.filter(s => ['completed', 'stopped'].includes(s.status)).length
  const allMttrs = [
    ...agentRuns.filter(r => r.mttr_seconds !== null).map(r => r.mttr_seconds as number),
    ...scenarios.filter(s => !agentRunMap.has(s.id)).map(mttr).filter((m): m is number => m !== null),
  ]
  const avgMttr  = allMttrs.length > 0
    ? Math.round(allMttrs.reduce((a, b) => a + b, 0) / allMttrs.length)
    : null

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-base font-semibold text-slate-100">Phoenix Agent</h1>
          <p className="text-[11px] text-slate-600 mt-0.5 font-mono">
            LangGraph healing pipeline · detect → diagnose → heal → approve → verify
          </p>
        </div>
        <button
          onClick={() => { mutateRuns(); mutateScenarios() }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-elevated border border-border text-slate-400 hover:text-slate-200 text-xs font-mono transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isValidating ? 'animate-spin text-accent' : ''}`} />
          {isValidating ? 'Syncing…' : 'Refresh'}
        </button>
      </div>

      {/* agent status banner */}
      {agentOnline ? (
        <div className="flex items-start gap-3 px-4 py-3 rounded-xl border border-accent/25 bg-accent/5">
          <Zap className="w-4 h-4 text-accent shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-mono font-semibold text-accent">Phoenix Agent — live</p>
            <p className="text-[11px] font-mono text-slate-500 mt-0.5">
              Agent picks up every running scenario within {10}s. Cards in
              {' '}<span className="text-violet">Diagnose</span> show OpenAI's real causal chain,
              {' '}<span className="text-accent">Heal</span> shows the remediation action in flight,
              and {' '}<span className="text-danger">Approve</span> surfaces the human-approval gate for high-risk actions.
            </p>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3 px-4 py-3 rounded-xl border border-slate-700/40 bg-elevated/30">
          <AlertTriangle className="w-4 h-4 text-slate-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-mono font-semibold text-slate-500">Phoenix Agent — offline</p>
            <p className="text-[11px] font-mono text-slate-600 mt-0.5">
              Agent API unreachable. Start port-forward:{' '}
              <span className="text-slate-400 font-mono">kubectl port-forward -n phoenix-system svc/phoenix-agent 8084:80</span>
            </p>
          </div>
        </div>
      )}

      {/* command center */}
      <CommandCenter
        agentRuns={agentRuns}
        memoryRecords={memoryRecords}
        running={running}
        agentOnline={agentOnline}
      />

      {/* pipeline breadcrumb */}
      <div className="flex items-center gap-2 text-[10px] font-mono text-slate-700">
        {LANES.map((lane, i) => (
          <span key={lane} className="flex items-center gap-2">
            <span className={LANE_META[lane].color}>{LANE_META[lane].label}</span>
            {i < LANES.length - 1 && <ChevronRight className="w-3 h-3 text-slate-800" />}
          </span>
        ))}
        <span className="ml-auto text-slate-800">cards move right as Phoenix responds</span>
      </div>

      {/* swim lanes */}
      {isLoading ? (
        <div className="grid grid-cols-5 gap-3">
          {LANES.map(lane => (
            <div key={lane} className="skeleton rounded-lg h-48" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-5 gap-3">
          {LANES.map(lane => (
            <LaneColumn
              key={lane}
              lane={lane}
              scenarios={scenarios}
              agentRunMap={agentRunMap}
              onMutate={onMutate}
            />
          ))}
        </div>
      )}

      {!isLoading && scenarios.length === 0 && (
        <p className="text-center text-[11px] font-mono text-slate-700 py-4">
          No scenarios yet — inject a fault from the{' '}
          <span className="text-accent">Incidents</span> page to watch the pipeline.
        </p>
      )}

      {/* fleet weakness map */}
      <div className="pt-2 border-t border-border/40">
        {rankingsError ? (
          <div className="flex items-center gap-2 text-[11px] font-mono text-danger">
            <AlertTriangle className="w-3.5 h-3.5" />
            Faultlib rankings unavailable — start port-forward for /api/faultlib
          </div>
        ) : !rankingsData ? (
          <div className="flex items-center gap-2 text-[11px] font-mono text-slate-600">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Loading fleet weakness map…
          </div>
        ) : (
          <FailureModeRankings
            rankings={rankingsData.rankings}
            total={rankingsData.scenarios_considered}
          />
        )}
      </div>
    </div>
  )
}
