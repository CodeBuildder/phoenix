import { useState } from 'react'
import useSWR from 'swr'
import { fetchTopology, fetchBlastRadius } from '../api/graph'
import type { GraphNode } from '../types/graph'
import { AlertCircle, ArrowRight, ChevronDown, ChevronUp, Loader2, RefreshCw, Search } from 'lucide-react'

// ── namespace colors ──────────────────────────────────────────────────────────

const NS_COLORS: Record<string, string> = {
  'phoenix-system': '#00e676',
  'kube-system':    '#22d3ee',
  'monitoring':     '#c084fc',
  'argus-system':   '#f59e0b',
  'kyverno':        '#4ade80',
}
function nsColor(ns: string) { return NS_COLORS[ns] ?? '#475569' }

// ── blast radius mini-panel ───────────────────────────────────────────────────

function BlastRadiusInline({ node }: { node: GraphNode }) {
  const { data, isLoading, error } = useSWR(
    `blast-inline/${node.id}`,
    () => fetchBlastRadius(node.namespace, 'custom', node.labels),
    { revalidateOnFocus: false },
  )

  if (isLoading) return (
    <div className="flex items-center gap-1.5 text-[11px] text-slate-600 font-mono">
      <Loader2 className="w-3 h-3 animate-spin" /> computing…
    </div>
  )
  if (error) return <p className="text-[11px] text-danger font-mono">blast radius unavailable</p>

  const affected = data?.affected_nodes ?? []
  if (affected.length === 0) return (
    <p className="text-[11px] text-accent font-mono">✓ No downstream impact</p>
  )

  const high   = affected.filter(n => n.severity === 'high').length
  const medium = affected.filter(n => n.severity === 'medium').length
  const low    = affected.filter(n => n.severity === 'low').length

  return (
    <div className="space-y-2">
      <p className="text-[11px] text-slate-400 font-mono">
        {affected.length} service{affected.length !== 1 ? 's' : ''} impacted if this fails:
      </p>
      {affected.slice(0, 5).map(n => (
        <div key={n.node_id} className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
            n.severity === 'high' ? 'bg-danger' : n.severity === 'medium' ? 'bg-warning' : 'bg-accent'
          }`} />
          <span className="text-[11px] font-mono text-slate-300">{n.name}</span>
          <span className={`ml-auto text-[10px] font-mono font-bold uppercase ${
            n.severity === 'high' ? 'text-danger' : n.severity === 'medium' ? 'text-warning' : 'text-accent'
          }`}>{n.severity}</span>
          <span className="text-[10px] text-slate-600 font-mono">{n.distance_hops}h</span>
        </div>
      ))}
      {affected.length > 5 && (
        <p className="text-[10px] text-slate-600 font-mono">+{affected.length - 5} more</p>
      )}
      <div className="flex gap-3 text-[10px] font-mono pt-1">
        {high   > 0 && <span className="text-danger">{high} critical</span>}
        {medium > 0 && <span className="text-warning">{medium} medium</span>}
        {low    > 0 && <span className="text-accent">{low} low</span>}
      </div>
    </div>
  )
}

// ── service row ───────────────────────────────────────────────────────────────

function ServiceRow({
  node, allNodes, inEdgeIds, outEdgeNames, flowIn, flowOut, isExpanded, onToggle,
}: {
  node: GraphNode
  allNodes: Map<string, GraphNode>
  inEdgeIds: string[]
  outEdgeNames: string[]
  flowIn: number
  flowOut: number
  isExpanded: boolean
  onToggle: () => void
}) {
  const inNodes = inEdgeIds.map(id => allNodes.get(id)?.name ?? id.split('/')[1])
  const color = nsColor(node.namespace)

  return (
    <>
      <tr
        className="border-b border-border/50 hover:bg-elevated/30 transition-colors cursor-pointer"
        onClick={onToggle}
      >
        {/* Name */}
        <td className="py-3 px-5">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
            <span className="text-sm font-mono font-semibold text-slate-200 truncate">{node.name}</span>
          </div>
        </td>

        {/* Namespace */}
        <td className="py-3 px-4">
          <span
            className="text-[10px] font-mono px-1.5 py-0.5 rounded inline-block truncate max-w-full"
            style={{ color, backgroundColor: color + '18' }}
          >
            {node.namespace}
          </span>
        </td>

        {/* Kind */}
        <td className="py-3 px-4">
          <span className="text-[11px] font-mono text-slate-500">{node.kind}</span>
        </td>

        {/* Relies on (outgoing) */}
        <td className="py-3 px-4">
          {outEdgeNames.length > 0
            ? <div className="flex flex-wrap gap-1">
                {outEdgeNames.slice(0, 3).map(n => (
                  <span key={n} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-elevated border border-border text-slate-400 truncate max-w-[7rem]">{n}</span>
                ))}
                {outEdgeNames.length > 3 && (
                  <span className="text-[10px] font-mono text-slate-600">+{outEdgeNames.length - 3}</span>
                )}
              </div>
            : <span className="text-[11px] text-slate-700 font-mono">—</span>
          }
        </td>

        {/* Depended on by (incoming) */}
        <td className="py-3 px-4">
          {inNodes.length > 0
            ? <div className="flex flex-wrap gap-1">
                {inNodes.slice(0, 3).map(n => (
                  <span key={n} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-danger/10 border border-danger/20 text-danger/80 truncate max-w-[7rem]">{n}</span>
                ))}
                {inNodes.length > 3 && (
                  <span className="text-[10px] font-mono text-slate-600">+{inNodes.length - 3}</span>
                )}
              </div>
            : <span className="text-[11px] text-accent font-mono text-xs">✓ leaf</span>
          }
        </td>

        {/* Live flows */}
        <td className="py-3 px-4 text-center">
          {flowIn + flowOut > 0
            ? <span className="text-[11px] font-mono text-accent">{flowIn + flowOut}</span>
            : <span className="text-[11px] text-slate-700 font-mono">—</span>
          }
        </td>

        {/* Expand toggle */}
        <td className="py-3 px-3 text-right">
          {isExpanded
            ? <ChevronUp className="w-3.5 h-3.5 text-slate-500 inline" />
            : <ChevronDown className="w-3.5 h-3.5 text-slate-500 inline" />
          }
        </td>
      </tr>

      {/* Expanded: blast radius */}
      {isExpanded && (
        <tr className="border-b border-border/50 bg-elevated/20">
          <td colSpan={7} className="px-5 py-4 fade-in">
            <div className="grid grid-cols-2 gap-8">
              <div>
                <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-3">
                  If {node.name} fails…
                </p>
                <BlastRadiusInline node={node} />
              </div>
              <div>
                <p className="text-[10px] font-mono text-slate-600 uppercase tracking-widest mb-3">Labels</p>
                {Object.keys(node.labels).length > 0
                  ? Object.entries(node.labels).map(([k, v]) => (
                      <p key={k} className="text-[11px] font-mono text-slate-400">{k}=<span className="text-slate-300">{v}</span></p>
                    ))
                  : <p className="text-[11px] text-slate-600 font-mono">No labels</p>
                }
                {node.cluster_ip && (
                  <p className="text-[11px] font-mono text-slate-500 mt-2">ClusterIP: {node.cluster_ip}</p>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function Topology() {
  const [search, setSearch] = useState('')
  const [nsFilter, setNsFilter] = useState('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: topo, error, isLoading, isValidating, mutate } = useSWR('topology', fetchTopology, {
    refreshInterval: 30_000,
  })

  const nodes = topo?.nodes ?? []
  const edges = topo?.edges ?? []

  const namespaces = [...new Set(nodes.map(n => n.namespace))].sort()
  const nodeMap = new Map(nodes.map(n => [n.id, n]))

  // Per-node edge analysis
  const inEdges  = new Map<string, string[]>()  // nodeId → [source ids]
  const outEdges = new Map<string, string[]>()  // nodeId → [target names]
  const flowsIn  = new Map<string, number>()
  const flowsOut = new Map<string, number>()

  edges.forEach(e => {
    if (!inEdges.has(e.target))  inEdges.set(e.target, [])
    if (!outEdges.has(e.source)) outEdges.set(e.source, [])
    inEdges.get(e.target)!.push(e.source)
    outEdges.get(e.source)!.push(e.target.split('/')[1])

    if (e.edge_type === 'flow_observed') {
      flowsIn.set(e.target,  (flowsIn.get(e.target)   ?? 0) + e.flow_count)
      flowsOut.set(e.source, (flowsOut.get(e.source)  ?? 0) + e.flow_count)
    }
  })

  const filtered = nodes
    .filter(n => nsFilter === 'all' || n.namespace === nsFilter)
    .filter(n => !search || n.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      const aIn = inEdges.get(a.id)?.length ?? 0
      const bIn = inEdges.get(b.id)?.length ?? 0
      return bIn - aIn  // most depended-on first
    })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-slate-100">Topology</h1>
          <p className="text-[11px] text-slate-600 mt-0.5 font-mono">
            {nodes.length} services · {edges.length} connections — sorted by blast risk (most critical first)
          </p>
        </div>
        <button
          onClick={() => mutate()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-elevated border border-border text-slate-400 hover:text-slate-200 text-xs font-mono transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isValidating ? 'animate-spin text-accent' : ''}`} />
          {isValidating ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] font-mono text-slate-600 flex-wrap">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded bg-danger/20 border border-danger/30 inline-block" />
          relied on by others = blast risk
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded bg-accent/10 border border-accent/20 inline-block" />
          leaf = safe to fault-test
        </span>
        <span className="flex items-center gap-1.5">
          <span className="text-accent">✓ leaf</span> = no dependents
        </span>
        <span>click a row → blast radius</span>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-600" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search services…"
            className="input w-full pl-8 text-xs"
          />
        </div>
        <select
          value={nsFilter}
          onChange={e => setNsFilter(e.target.value)}
          className="input text-xs"
        >
          <option value="all">All namespaces</option>
          {namespaces.map(ns => (
            <option key={ns} value={ns}>{ns}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-4 py-3">
          <AlertCircle className="w-4 h-4 shrink-0" />
          Graph service unreachable. Start port-forward: kubectl port-forward -n phoenix-system svc/phoenix-graph 8080:80
        </div>
      )}

      {/* Flow edge legend */}
      {!isLoading && edges.length > 0 && (
        <div className="flex items-center gap-6 text-[10px] font-mono text-slate-600 bg-card border border-border rounded-lg px-4 py-2.5">
          <span className="text-slate-400 font-semibold uppercase tracking-wider">Connection types:</span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-px bg-violet inline-block" />
            env_ref — hardcoded in deployment config
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-px bg-accent inline-block" />
            flow_observed — live Hubble eBPF packets
          </span>
          <span className="flex items-center gap-1.5">
            <ArrowRight className="w-3 h-3 text-slate-500" />
            direction = source depends on target
          </span>
        </div>
      )}

      {/* Table */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-8 space-y-3">
            {[1,2,3,4,5].map(i => (
              <div key={i} className="skeleton h-10 w-full rounded-lg" />
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full table-fixed">
              <colgroup>
                <col style={{ width: '18%' }} />  {/* Service */}
                <col style={{ width: '14%' }} />  {/* Namespace */}
                <col style={{ width: '9%'  }} />  {/* Kind */}
                <col style={{ width: '25%' }} />  {/* Depends on */}
                <col style={{ width: '25%' }} />  {/* Relied on by */}
                <col style={{ width: '6%'  }} />  {/* Flows */}
                <col style={{ width: '3%'  }} />  {/* Expand */}
              </colgroup>
              <thead>
                <tr className="border-b border-border bg-elevated/30">
                  <th className="text-left py-3 px-5 text-[10px] font-mono text-slate-500 uppercase tracking-widest">Service</th>
                  <th className="text-left py-3 px-4 text-[10px] font-mono text-slate-500 uppercase tracking-widest">Namespace</th>
                  <th className="text-left py-3 px-4 text-[10px] font-mono text-slate-500 uppercase tracking-widest">Kind</th>
                  <th className="text-left py-3 px-4 text-[10px] font-mono text-slate-500 uppercase tracking-widest">Depends on</th>
                  <th className="text-left py-3 px-4 text-[10px] font-mono text-slate-500 uppercase tracking-widest">Relied on by</th>
                  <th className="text-center py-3 px-4 text-[10px] font-mono text-slate-500 uppercase tracking-widest">Flows</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center py-10 text-slate-600 text-sm font-mono">
                      No services match your filter.
                    </td>
                  </tr>
                ) : (
                  filtered.map(node => (
                    <ServiceRow
                      key={node.id}
                      node={node}
                      allNodes={nodeMap}
                      inEdgeIds={inEdges.get(node.id) ?? []}
                      outEdgeNames={outEdges.get(node.id) ?? []}
                      flowIn={flowsIn.get(node.id) ?? 0}
                      flowOut={flowsOut.get(node.id) ?? 0}
                      isExpanded={expandedId === node.id}
                      onToggle={() => setExpandedId(expandedId === node.id ? null : node.id)}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="text-[10px] text-slate-700 font-mono text-right">
        {filtered.length} of {nodes.length} services shown · data from k8s API + Cilium Hubble
      </p>
    </div>
  )
}
