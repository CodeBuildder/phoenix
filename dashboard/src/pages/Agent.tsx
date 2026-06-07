import { useEffect, useRef, useState } from 'react'
import useSWR from 'swr'
import { fetchScenarios, stopScenario } from '../api/chaos'
import { fetchBlastRadius } from '../api/graph'
import { fetchRankings } from '../api/faultlib'
import type { Scenario } from '../types/chaos'
import type { BlastRadiusResponse, AffectedNode } from '../types/graph'
import type { ComponentRanking } from '../types/faultlib'
import {
  Activity, AlertTriangle, CheckCircle2, ChevronRight, Clock,
  Eye, Loader2, RefreshCw, Shield, Square, Zap,
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

function computeLane(
  scenario: Scenario,
  blast: BlastRadiusResponse | undefined,
  blastLoading: boolean,
): Lane {
  if (['completed', 'stopped', 'failed'].includes(scenario.status)) return 'verify'
  if (scenario.status !== 'running') return 'detect'
  if (blastLoading || blast === undefined) return 'detect'

  const affected = blast.affected_nodes ?? []
  const sev      = incidentSeverity(affected)
  const human    = needsHuman(sev, affected)

  if (human) return 'approve'

  // Diagnose for first 30s (Phoenix is analyzing), then Heal
  const age = elapsed(scenario.started_at)
  return age < 30 ? 'diagnose' : 'heal'
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

// ── service name extraction ───────────────────────────────────────────────────

function extractServiceName(scenario: Scenario): string {
  const labels = scenario.target.label_selector ?? {}
  const app = labels['app'] ?? labels['name'] ?? labels['component'] ?? null
  if (app) return app
  const parts = scenario.name.split('-')
  if (parts[0] === 'incident' && parts.length > 3)
    return parts.slice(1, -1).join('-').replace(/-\d{10,}$/, '')
  return scenario.name
}

// ── live elapsed ticker ───────────────────────────────────────────────────────

function useTick(scenario: Scenario) {
  const [, forceUpdate] = useState(0)
  useEffect(() => {
    if (scenario.status !== 'running') return
    const id = setInterval(() => forceUpdate(n => n + 1), 1000)
    return () => clearInterval(id)
  }, [scenario.status])
}

// ── lane card ─────────────────────────────────────────────────────────────────

function LaneCard({ scenario, column }: { scenario: Scenario; column: Lane }) {
  const [stopping, setStopping] = useState(false)
  useTick(scenario)

  const target = scenario.target
  const { data: blast, isLoading: blastLoading } = useSWR(
    target.namespace ? `blast-agent/${scenario.id}/${target.namespace}` : null,
    () => fetchBlastRadius(target.namespace!, scenario.fault_type, target.label_selector ?? {}),
    { refreshInterval: scenario.status === 'running' ? 10_000 : 0, dedupingInterval: 5_000 },
  )

  const currentLane = computeLane(scenario, blast, blastLoading)
  if (currentLane !== column) return null

  const affected = blast?.affected_nodes ?? []
  const matched  = blast?.matched_nodes  ?? []
  const sev      = affected.length > 0 ? incidentSeverity(affected) : 'low'
  const human    = needsHuman(sev, affected)
  const age      = elapsed(scenario.started_at)
  const remaining = scenario.duration_seconds ? Math.max(scenario.duration_seconds - age, 0) : null
  const service  = extractServiceName(scenario)
  const m        = mttr(scenario)

  const meta = LANE_META[column]

  return (
    <div className={`rounded-lg border bg-card p-3 space-y-2.5 text-[11px] font-mono ${meta.border}`}>
      {/* header */}
      <div className="flex items-start gap-2">
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
      </div>

      {/* lane-specific content */}

      {column === 'detect' && (
        <div className="flex items-center gap-1.5 text-slate-600">
          <Loader2 className="w-3 h-3 animate-spin" />
          Scanning topology for blast radius…
        </div>
      )}

      {column === 'diagnose' && (
        <div className="space-y-1.5">
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
            <Zap className="w-3 h-3" />
            M2: Causal chain analysis will appear here
          </div>
        </div>
      )}

      {column === 'heal' && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-accent">
            <Activity className="w-3 h-3" />
            Phoenix Agent monitoring
          </div>
          {matched.length > 0 && (
            <p className="text-slate-600">
              {matched.length} service{matched.length !== 1 ? 's' : ''} targeted · blast contained
            </p>
          )}
          {remaining !== null && (
            <p className="text-slate-600">Auto-stops in {fmtSec(remaining)}</p>
          )}
          <div className="flex items-center gap-1.5 text-slate-700 border-t border-border/40 pt-1.5 mt-1">
            <Zap className="w-3 h-3" />
            M2: Remediation actions will appear here
          </div>
        </div>
      )}

      {column === 'approve' && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-danger">
            <AlertTriangle className="w-3 h-3" />
            Blast radius is {sev} — operator required
          </div>
          {affected.length > 0 && (
            <p className="text-slate-500">
              {affected.length} service{affected.length !== 1 ? 's' : ''} at risk
            </p>
          )}
          {human && (
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
        </div>
      )}

      {column === 'verify' && (
        <div className="space-y-1.5">
          {scenario.status === 'completed' && (
            <div className="flex items-center gap-1.5 text-accent">
              <CheckCircle2 className="w-3 h-3" />
              Fault expired — services recovering
            </div>
          )}
          {scenario.status === 'stopped' && (
            <div className="flex items-center gap-1.5 text-slate-400">
              <CheckCircle2 className="w-3 h-3" />
              Stopped by operator
            </div>
          )}
          {scenario.status === 'failed' && (
            <div className="flex items-center gap-1.5 text-danger">
              <AlertTriangle className="w-3 h-3" />
              Scenario failed — review logs
            </div>
          )}
          {m !== null && (
            <div className="flex items-center gap-1.5 text-slate-600">
              <Clock className="w-3 h-3" />
              MTTR: {fmtSec(m)}
            </div>
          )}
          {affected.length > 0 && (
            <p className="text-slate-600 text-[10px]">
              Verify recovery of: {affected.slice(0, 2).map(n=>n.name).join(', ')}
              {affected.length > 2 ? ` +${affected.length - 2} more` : ''}
            </p>
          )}
        </div>
      )}

      {/* elapsed/status footer */}
      <div className="text-[10px] text-slate-700 border-t border-border/30 pt-1.5">
        {scenario.started_at && (
          scenario.status === 'running'
            ? `${fmtSec(age)} elapsed`
            : `ended ${new Date(scenario.stopped_at ?? '').toLocaleTimeString()}`
        )}
      </div>
    </div>
  )
}

// ── swim lane column ──────────────────────────────────────────────────────────

function LaneColumn({ lane, scenarios }: { lane: Lane; scenarios: Scenario[] }) {
  const meta = LANE_META[lane]

  return (
    <div className="flex flex-col min-w-0">
      {/* column header */}
      <div className={`flex items-center gap-2 px-3 py-2.5 rounded-t-lg border-t border-l border-r bg-elevated/40 ${meta.border}`}>
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${meta.dot}`} />
        <div className="min-w-0">
          <p className={`text-xs font-mono font-bold ${meta.color}`}>{meta.label}</p>
          <p className="text-[10px] font-mono text-slate-700 truncate">{meta.sublabel}</p>
        </div>
      </div>

      {/* cards */}
      <div className={`flex-1 border-l border-r border-b rounded-b-lg p-2 space-y-2 min-h-[120px] ${meta.border} bg-surface/30`}>
        {scenarios.map(s => (
          <LaneCard key={s.id} scenario={s} column={lane} />
        ))}
      </div>
    </div>
  )
}

// ── failure-mode rankings ─────────────────────────────────────────────────────

function FailureModeRankings({ rankings, total }: { rankings: ComponentRanking[]; total: number }) {
  const sorted = [...rankings].sort((a, b) => b.tallies.total - a.tallies.total)
  const maxTotal = sorted[0]?.tallies.total ?? 1

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
          <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest">
            Fleet Weakness Map
          </p>
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
              const t = r.tallies
              const segments = [
                { key: 'cascading',           val: t.cascading },
                { key: 'network_partition',    val: t.network_partition },
                { key: 'resource_exhaustion',  val: t.resource_exhaustion },
                { key: 'transient',            val: t.transient },
                { key: 'quota_limit',          val: t.quota_limit },
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
                      {/* stacked bar */}
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
                  No scenarios in the rankings yet. Inject faults from the Incidents page to build the fleet weakness map.
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
  const { data: scenarios = [], isLoading, isValidating, mutate } = useSWR(
    'scenarios', fetchScenarios, { refreshInterval: 5_000 },
  )
  const { data: rankingsData, error: rankingsError } = useSWR(
    'rankings', fetchRankings, { revalidateOnFocus: false },
  )

  const running   = scenarios.filter(s => s.status === 'running').length
  const resolved  = scenarios.filter(s => ['completed', 'stopped'].includes(s.status)).length
  const allMttrs  = scenarios.map(mttr).filter((m): m is number => m !== null)
  const avgMttr   = allMttrs.length > 0 ? Math.round(allMttrs.reduce((a, b) => a + b, 0) / allMttrs.length) : null

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-base font-semibold text-slate-100">Phoenix Agent</h1>
          <p className="text-[11px] text-slate-600 mt-0.5 font-mono">
            Healing pipeline · live scenario tracking · M2 agent activates this pipeline fully
          </p>
        </div>
        <button
          onClick={() => mutate()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-elevated border border-border text-slate-400 hover:text-slate-200 text-xs font-mono transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isValidating ? 'animate-spin text-accent' : ''}`} />
          {isValidating ? 'Syncing…' : 'Refresh'}
        </button>
      </div>

      {/* M2 status banner */}
      <div className="flex items-start gap-3 px-4 py-3 rounded-xl border border-violet/25 bg-violet/5">
        <Zap className="w-4 h-4 text-violet shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-mono font-semibold text-violet">M2 Agent — not yet deployed</p>
          <p className="text-[11px] font-mono text-slate-500 mt-0.5">
            The swim lanes below show live data from the chaos API (scenarios, blast radius, timing).
            When M2 lands: the <span className="text-violet">Diagnose</span> lane fills with Claude's causal chain,
            <span className="text-accent"> Heal</span> shows active remediation actions,
            and <span className="text-danger"> Approve</span> surfaces the human-approval gate with predicted outcomes.
          </p>
        </div>
      </div>

      {/* stats bar */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Total scenarios', value: scenarios.length, color: 'text-slate-200' },
          { label: 'Active faults', value: running, color: running > 0 ? 'text-danger' : 'text-slate-400' },
          { label: 'Resolved', value: resolved, color: 'text-accent' },
          { label: 'Avg MTTR', value: avgMttr !== null ? fmtSec(avgMttr) : '—', color: 'text-slate-300' },
        ].map(stat => (
          <div key={stat.label} className="bg-card border border-border rounded-lg px-4 py-3">
            <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest">{stat.label}</p>
            <p className={`text-xl font-mono font-bold mt-1 ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* pipeline label */}
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
            <LaneColumn key={lane} lane={lane} scenarios={scenarios} />
          ))}
        </div>
      )}

      {!isLoading && scenarios.length === 0 && (
        <p className="text-center text-[11px] font-mono text-slate-700 py-4">
          No scenarios yet — inject a fault from the{' '}
          <span className="text-accent">Incidents</span> page to watch cards move through the pipeline.
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
