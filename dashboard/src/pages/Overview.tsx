import { useRef, useState } from 'react'
import useSWR from 'swr'
import { fetchTopology } from '../api/graph'
import { fetchScenarios } from '../api/chaos'
import { fetchHealth as graphHealth } from '../api/graph'
import { fetchHealth as chaosHealth } from '../api/chaos'
import { fetchHealth as faultlibHealth } from '../api/faultlib'
import { useLiveAge } from '../hooks/useLiveAge'
import ExplainerPanel from '../components/ExplainerPanel'
import {
  explainService, explainFlow, explainScenario,
  type ExplainTarget, type ExplainerContent,
} from '../components/ExplainerPanel/explain'
import type { GraphEdge, GraphNode } from '../types/graph'
import type { Scenario } from '../types/chaos'
import {
  CheckCircle2, AlertTriangle, Activity, Zap, Network,
  GitBranch, FlaskConical, Library, BarChart3, ArrowRight, RefreshCw,
} from 'lucide-react'

// ── skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} />
}

function PanelSkeleton() {
  return (
    <div className="bg-card border border-border rounded-xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Skeleton className="w-4 h-4 rounded" />
        <Skeleton className="w-28 h-3" />
      </div>
      {[80, 55, 70, 40, 60].map((w, i) => (
        <div key={i} className="space-y-1.5">
          <div className="flex justify-between">
            <Skeleton className={`${w > 60 ? 'w-32' : 'w-24'} h-3`} />
            <Skeleton className="w-10 h-3" />
          </div>
          <Skeleton className="h-1.5 w-full" />
        </div>
      ))}
    </div>
  )
}

// ── service health cards ──────────────────────────────────────────────────────

const SERVICE_DEFS = [
  { key: 'graph',    label: 'Graph',    icon: GitBranch,    fetcher: graphHealth,    desc: 'k8s topology + Hubble eBPF' },
  { key: 'chaos',    label: 'Chaos',    icon: FlaskConical, fetcher: chaosHealth,    desc: 'fault injection engine'       },
  { key: 'faultlib', label: 'Faultlib', icon: Library,      fetcher: faultlibHealth, desc: 'taxonomy classifier'          },
]

function ServiceCard({
  icon: Icon, label, desc, fetcher, onClick,
}: {
  icon: React.ElementType; label: string; desc: string
  fetcher: () => Promise<{ status: string }>; onClick?: () => void
}) {
  const { data, error, isValidating } = useSWR(`health/${label}`, fetcher, {
    refreshInterval: 8_000, shouldRetryOnError: false,
  })
  const ok = !error && data?.status === 'ok'
  const loading = !data && !error

  return (
    <div
      onClick={onClick}
      className={`clickable rounded-xl border p-4 flex flex-col gap-2.5 transition-all duration-500 ${
        loading ? 'border-border bg-card' :
        ok      ? 'border-accent/25 bg-accent/5 shadow-[0_0_20px_rgba(0,230,118,0.05)]' :
                  'border-danger/30 bg-danger/5'
      }`}
    >
      {/* Top row: label + syncing + status */}
      <div className="flex items-center gap-2">
        <Icon className={`w-4 h-4 shrink-0 ${ok ? 'text-accent' : loading ? 'text-slate-600' : 'text-danger'}`} />
        <span className="font-mono text-sm font-semibold text-slate-200 flex-1">{label}</span>
        {isValidating && (
          <RefreshCw className="w-3 h-3 animate-spin text-accent/60 shrink-0" />
        )}
        <span className={`flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded-full border shrink-0 ${
          loading ? 'border-border text-slate-600' :
          ok      ? 'border-accent/30 text-accent bg-accent/10' :
                    'border-danger/30 text-danger bg-danger/10'
        }`}>
          <span className={`w-1 h-1 rounded-full ${loading ? 'bg-slate-600' : ok ? 'bg-accent animate-pulse' : 'bg-danger'}`} />
          {loading ? '—' : ok ? 'online' : 'down'}
        </span>
      </div>
      <p className="text-[11px] text-slate-500 leading-relaxed">{desc}</p>
      <p className="text-[10px] text-accent/40 font-mono">↗ click to explain</p>
    </div>
  )
}

// ── status banner ─────────────────────────────────────────────────────────────

function StatusBanner({
  nodes, edges, scenarios, loading, validating,
}: {
  nodes: GraphNode[]; edges: GraphEdge[]; scenarios: Scenario[]
  loading: boolean; validating: boolean
}) {
  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-elevated/20 px-5 py-4">
        <div className="flex items-center gap-3">
          <Skeleton className="w-5 h-5 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="w-48 h-4" />
            <Skeleton className="w-72 h-3" />
          </div>
        </div>
      </div>
    )
  }

  const running   = scenarios.filter(s => s.status === 'running')
  const flowCount = edges.filter(e => e.edge_type === 'flow_observed').length
  const nsCount   = new Set(nodes.map(n => n.namespace)).size
  const isHealthy = running.length === 0

  return (
    <div className={`rounded-xl border px-5 py-4 flex items-center justify-between transition-colors duration-500 ${
      isHealthy ? 'border-accent/30 bg-accent/5' : 'border-danger/40 bg-danger/5'
    }`}>
      <div className="flex items-center gap-3">
        {isHealthy
          ? <CheckCircle2 className="w-5 h-5 text-accent shrink-0" />
          : <AlertTriangle className="w-5 h-5 text-danger shrink-0 animate-pulse" />
        }
        <div>
          <p className="font-semibold text-slate-100">
            {isHealthy ? 'All systems operational' : `${running.length} fault injection${running.length !== 1 ? 's' : ''} active`}
          </p>
          <p className="text-[11px] text-slate-500 mt-0.5 font-mono">
            {nodes.length} services · {nsCount} namespaces · {flowCount} live flows · {scenarios.length} scenarios
            {validating && <span className="text-accent ml-2">· syncing…</span>}
          </p>
        </div>
      </div>
      {running.map(s => (
        <span key={s.id} className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-danger/10 border border-danger/30 text-danger text-xs font-mono">
          <span className="w-1.5 h-1.5 rounded-full bg-danger animate-ping" />
          {s.name}
        </span>
      ))}
    </div>
  )
}

// ── blast risk panel ──────────────────────────────────────────────────────────

function BlastRiskPanel({
  nodes, edges, loading, validating, age, onClickNode,
}: {
  nodes: GraphNode[]; edges: GraphEdge[]; loading: boolean
  validating: boolean; age: string | null
  onClickNode: (n: GraphNode) => void
}) {
  if (loading) return <PanelSkeleton />

  const incoming: Record<string, number> = {}
  edges.forEach(e => { incoming[e.target] = (incoming[e.target] ?? 0) + 1 })
  const ranked = nodes
    .filter(n => (incoming[n.id] ?? 0) > 0)
    .map(n => ({ node: n, deps: incoming[n.id] }))
    .sort((a, b) => b.deps - a.deps)
    .slice(0, 6)
  const max = ranked[0]?.deps ?? 1

  return (
    <div className="bg-card border border-border rounded-xl p-5 flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Zap className="w-4 h-4 text-warning" />
        <span className="text-[11px] font-mono font-semibold text-slate-400 uppercase tracking-widest">Blast Risk</span>
        <span className="ml-auto flex items-center gap-2">
          {validating && <RefreshCw className="w-2.5 h-2.5 animate-spin text-accent" />}
          {age && <span className="text-[10px] font-mono text-slate-600">{age}</span>}
        </span>
      </div>

      <p className="text-[10px] text-slate-600 -mt-2">
        Click a service to understand its risk and get recommendations.
      </p>

      {ranked.length === 0
        ? <p className="text-slate-600 text-xs">No dependency edges observed yet.</p>
        : <div className="space-y-2">
          {ranked.map(({ node, deps }) => {
            const pct  = Math.round((deps / max) * 100)
            const color = pct === 100 ? '#ff4d4d' : pct >= 50 ? '#f59e0b' : '#00e676'
            const text  = pct === 100 ? 'text-danger' : pct >= 50 ? 'text-warning' : 'text-accent'
            return (
              <div
                key={node.id}
                className="clickable p-2 -mx-2"
                onClick={() => onClickNode(node)}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-mono text-slate-200">{node.name}</span>
                  <span className={`text-[10px] font-mono font-bold ${text}`}>{deps} dep{deps !== 1 ? 's' : ''}</span>
                </div>
                <div className="h-1.5 rounded-full bg-elevated overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{ width: `${pct}%`, backgroundColor: color, boxShadow: `0 0 6px ${color}60` }}
                  />
                </div>
                <p className="text-[10px] text-slate-600 mt-0.5 font-mono">{node.namespace}</p>
              </div>
            )
          })}
        </div>
      }
    </div>
  )
}

// ── live flows panel ──────────────────────────────────────────────────────────

function LiveFlowsPanel({
  edges, loading, validating, age, onClickEdge,
}: {
  edges: GraphEdge[]; loading: boolean
  validating: boolean; age: string | null
  onClickEdge: (e: GraphEdge) => void
}) {
  if (loading) return <PanelSkeleton />

  const flows = edges
    .filter(e => e.edge_type === 'flow_observed')
    .sort((a, b) => b.flow_count - a.flow_count)
  const max = flows[0]?.flow_count ?? 1

  return (
    <div className="bg-card border border-border rounded-xl p-5 flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Activity className="w-4 h-4 text-accent" />
        <span className="text-[11px] font-mono font-semibold text-slate-400 uppercase tracking-widest">Live Traffic</span>
        <span className="ml-auto flex items-center gap-2">
          {validating && <RefreshCw className="w-2.5 h-2.5 animate-spin text-accent" />}
          {age && <span className="text-[10px] font-mono text-slate-600">{age}</span>}
        </span>
      </div>

      <p className="text-[10px] text-slate-600 -mt-2">
        Cilium Hubble eBPF flows. Click any row to understand what's flowing and why.
      </p>

      {flows.length === 0
        ? <p className="text-slate-600 text-xs">No Hubble flows observed yet.</p>
        : <div className="space-y-3">
          {flows.map((e, i) => {
            const pct = Math.round((e.flow_count / max) * 100)
            const src = e.source.split('/')[1]
            const dst = e.target.split('/')[1]
            return (
              <div key={i} className="clickable p-2 -mx-2" onClick={() => onClickEdge(e)}>
                <div className="flex items-center gap-2 mb-1.5 text-[11px] font-mono">
                  <span className="text-accent truncate max-w-[36%]">{src}</span>
                  <ArrowRight className="w-3 h-3 text-slate-600 shrink-0" />
                  <span className="text-slate-300 truncate max-w-[36%]">{dst}</span>
                  <span className="ml-auto text-accent font-bold shrink-0 tabular-nums">{e.flow_count}</span>
                </div>
                <div className="h-1 rounded-full bg-elevated overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{ width: `${pct}%`, backgroundColor: '#00e676', boxShadow: '0 0 4px rgba(0,230,118,0.5)' }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      }
    </div>
  )
}

// ── namespace panel ───────────────────────────────────────────────────────────

function NamespacePanel({
  nodes, loading, validating, age,
}: {
  nodes: GraphNode[]; loading: boolean; validating: boolean; age: string | null
}) {
  if (loading) return <PanelSkeleton />

  const ns: Record<string, number> = {}
  nodes.forEach(n => { ns[n.namespace] = (ns[n.namespace] ?? 0) + 1 })
  const sorted = Object.entries(ns).sort((a, b) => b[1] - a[1])
  const max = sorted[0]?.[1] ?? 1

  const nsColor: Record<string, string> = {
    'phoenix-system': '#00e676',
    'kube-system':    '#22d3ee',
    'monitoring':     '#c084fc',
    'argus-system':   '#f59e0b',
    'kyverno':        '#4ade80',
  }

  return (
    <div className="bg-card border border-border rounded-xl p-5 flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Network className="w-4 h-4 text-cyan" />
        <span className="text-[11px] font-mono font-semibold text-slate-400 uppercase tracking-widest">Namespaces</span>
        <span className="ml-auto flex items-center gap-2">
          {validating && <RefreshCw className="w-2.5 h-2.5 animate-spin text-accent" />}
          {age && <span className="text-[10px] font-mono text-slate-600">{age}</span>}
        </span>
      </div>

      <p className="text-[10px] text-slate-600 -mt-2">
        Logical groupings of services. Phoenix-system is where all chaos components run.
      </p>

      <div className="space-y-3">
        {sorted.map(([name, count]) => {
          const pct   = Math.round((count / max) * 100)
          const color = nsColor[name] ?? '#475569'
          return (
            <div key={name}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-mono text-slate-300">{name}</span>
                <span className="text-[10px] font-mono text-slate-500">{count} svcs</span>
              </div>
              <div className="h-1.5 rounded-full bg-elevated overflow-hidden">
                <div
                  className="h-full rounded-full opacity-75 transition-all duration-700"
                  style={{ width: `${pct}%`, backgroundColor: color }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── env deps panel ────────────────────────────────────────────────────────────

function EnvDepsPanel({
  edges, nodes, loading, onClickEdge,
}: {
  edges: GraphEdge[]; nodes: GraphNode[]; loading: boolean; onClickEdge: (e: GraphEdge) => void
}) {
  if (loading) return null

  const nodeMap  = new Map(nodes.map(n => [n.id, n.name]))
  const envEdges = edges.filter(e => e.edge_type === 'env_ref')
  if (envEdges.length === 0) return null

  const grouped: Record<string, GraphEdge[]> = {}
  envEdges.forEach(e => {
    const src = nodeMap.get(e.source) ?? e.source.split('/')[1]
    grouped[src] = [...(grouped[src] ?? []), e]
  })

  return (
    <div className="bg-card border border-border rounded-xl p-5">
      <div className="flex items-center gap-2 mb-2">
        <BarChart3 className="w-4 h-4 text-violet" />
        <span className="text-[11px] font-mono font-semibold text-slate-400 uppercase tracking-widest">
          Configured Dependencies
        </span>
        <span className="ml-auto text-[10px] text-slate-600 font-mono">env-var DNS refs</span>
      </div>
      <p className="text-[10px] text-slate-600 mb-4">
        These services were deployed with hardcoded references to each other via environment variables. Click any row to understand the connection.
      </p>
      <div className="space-y-2">
        {Object.entries(grouped).map(([src, edgeList]) => (
          <div key={src} className="flex items-center gap-3">
            <span className="text-[11px] font-mono text-violet shrink-0 w-36">{src}</span>
            <ArrowRight className="w-3 h-3 text-slate-700 shrink-0" />
            <div className="flex flex-wrap gap-1.5">
              {edgeList.map((e, i) => {
                const dst = nodeMap.get(e.target) ?? e.target.split('/')[1]
                return (
                  <span
                    key={i}
                    className="clickable px-2 py-0.5 rounded bg-elevated border border-border text-[11px] font-mono text-slate-400"
                    onClick={() => onClickEdge(e)}
                  >
                    {dst}
                  </span>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function Overview() {
  const topoFetchedAt = useRef<number | null>(null)

  const { data: topo, isLoading, isValidating: topoValidating } = useSWR('topology', fetchTopology, {
    refreshInterval: 15_000,
    onSuccess: () => { topoFetchedAt.current = Date.now() },
  })
  const { data: scenarios = [], isValidating: scenariosValidating } = useSWR('scenarios', fetchScenarios, {
    refreshInterval: 5_000,
  })

  const topoAge = useLiveAge(topoFetchedAt.current)
  const nodes   = topo?.nodes ?? []
  const edges   = topo?.edges ?? []

  // Explainer state
  const [explainer, setExplainer] = useState<{
    target: ExplainTarget; content: ExplainerContent
  } | null>(null)

  function openService(node: GraphNode) {
    setExplainer({
      target:  { kind: 'service', node },
      content: explainService(node, edges, scenarios),
    })
  }
  function openFlow(edge: GraphEdge) {
    setExplainer({
      target:  { kind: 'flow', edge },
      content: explainFlow(edge, nodes),
    })
  }
  function openScenario(scenario: Scenario) {
    setExplainer({
      target:  { kind: 'scenario', scenario },
      content: explainScenario(scenario, nodes, edges),
    })
  }

  const anyValidating = topoValidating || scenariosValidating

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-slate-100">Overview</h1>
          <p className="text-[11px] text-slate-600 mt-0.5 font-mono">
            k8s API · Cilium Hubble eBPF · fault taxonomy · auto-refreshes every 15s
          </p>
        </div>
        {anyValidating && (
          <span className="flex items-center gap-1.5 text-xs font-mono text-accent animate-pulse">
            <RefreshCw className="w-3 h-3 animate-spin" />
            syncing…
          </span>
        )}
      </div>

      <StatusBanner
        nodes={nodes} edges={edges} scenarios={scenarios}
        loading={isLoading} validating={anyValidating}
      />

      {/* Service health — click to explain */}
      <div className="grid grid-cols-3 gap-3">
        {SERVICE_DEFS.map(s => {
          const fakeNode = nodes.find(n => n.name === `phoenix-${s.key.toLowerCase()}`)
          return (
            <ServiceCard
              key={s.key}
              icon={s.icon} label={s.label} desc={s.desc} fetcher={s.fetcher}
              onClick={fakeNode ? () => openService(fakeNode) : undefined}
            />
          )
        })}
      </div>

      {/* Analytics — all clickable */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <BlastRiskPanel
          nodes={nodes} edges={edges} loading={isLoading}
          validating={topoValidating} age={topoAge}
          onClickNode={openService}
        />
        <LiveFlowsPanel
          edges={edges} loading={isLoading}
          validating={topoValidating} age={topoAge}
          onClickEdge={openFlow}
        />
        <NamespacePanel
          nodes={nodes} loading={isLoading}
          validating={topoValidating} age={topoAge}
        />
      </div>

      <EnvDepsPanel
        edges={edges} nodes={nodes} loading={isLoading}
        onClickEdge={openFlow}
      />

      {/* Scenario list — clickable */}
      {scenarios.length > 0 && (
        <div className="bg-card border border-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-2">
            <FlaskConical className="w-4 h-4 text-violet" />
            <span className="text-[11px] font-mono font-semibold text-slate-400 uppercase tracking-widest">
              Recent Scenarios
            </span>
          </div>
          <p className="text-[10px] text-slate-600 mb-4">Click any scenario to understand what fault it's injecting and what's at risk.</p>
          <div className="space-y-1">
            {scenarios.map(s => {
              const dotColor = s.status === 'running' ? 'bg-danger animate-ping'
                : s.status === 'completed' ? 'bg-accent'
                : s.status === 'failed'    ? 'bg-warning'
                : 'bg-slate-600'
              const textColor = s.status === 'running' ? 'text-danger'
                : s.status === 'completed' ? 'text-accent'
                : s.status === 'failed'    ? 'text-warning'
                : 'text-slate-500'
              return (
                <div
                  key={s.id}
                  className="clickable flex items-center gap-3 px-3 py-2"
                  onClick={() => openScenario(s)}
                >
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
                  <span className="text-sm font-mono text-slate-200 flex-1">{s.name}</span>
                  <span className="text-[11px] font-mono text-slate-500">{s.fault_type}</span>
                  <span className={`text-[10px] font-mono font-bold uppercase ${textColor}`}>{s.status}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Explainer panel */}
      {explainer && (
        <ExplainerPanel
          content={explainer.content}
          targetKind={explainer.target.kind}
          onClose={() => setExplainer(null)}
        />
      )}
    </div>
  )
}
