import useSWR from 'swr'
import { fetchCatalog, fetchRankings } from '../api/faultlib'
import type { FaultCatalogEntry, TaxonomyCategory } from '../types/faultlib'
import { AlertCircle, Loader2 } from 'lucide-react'

const CATEGORY_COLORS: Record<TaxonomyCategory, string> = {
  transient: 'bg-success/10 text-success border-success/20',
  cascading: 'bg-danger/10 text-danger border-danger/20',
  'resource-exhaustion': 'bg-warning/10 text-warning border-warning/20',
  'network-partition': 'bg-cyan/10 text-cyan border-cyan/20',
  'quota-limit': 'bg-violet/10 text-violet border-violet/20',
}

function CatalogCard({ entry }: { entry: FaultCatalogEntry }) {
  const colorClass = CATEGORY_COLORS[entry.taxonomy_category] ?? 'bg-elevated text-slate-400 border-border'

  return (
    <div className="bg-card border border-border rounded-xl p-4 space-y-3 hover:border-accent/30 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-sm font-semibold text-slate-200">{entry.fault_type}</p>
          <p className="text-xs text-slate-500 mt-0.5">{entry.domain}</p>
        </div>
        <span className={`shrink-0 px-2 py-0.5 rounded border text-[10px] font-mono uppercase tracking-wide ${colorClass}`}>
          {entry.taxonomy_category}
        </span>
      </div>

      <p className="text-xs text-slate-400 leading-relaxed">{entry.description}</p>

      <div>
        <p className="text-[10px] text-slate-600 uppercase tracking-wider font-mono mb-1">Symptoms</p>
        <ul className="space-y-0.5">
          {entry.typical_symptoms.map((s, i) => (
            <li key={i} className="text-xs text-slate-500 flex items-start gap-1.5">
              <span className="text-accent mt-0.5">·</span>
              {s}
            </li>
          ))}
        </ul>
      </div>

      <div className="pt-1 border-t border-border">
        <p className="text-[10px] text-slate-600 uppercase tracking-wider font-mono mb-1">Blast Shape</p>
        <p className="text-xs text-slate-400">{entry.blast_radius_shape}</p>
      </div>
    </div>
  )
}

export default function FaultLibrary() {
  const { data: catalog, error: catErr, isLoading: catLoading } = useSWR('catalog', fetchCatalog, {
    refreshInterval: 60_000,
  })
  const { data: rankings, error: rankErr, isLoading: rankLoading } = useSWR('rankings', fetchRankings, {
    refreshInterval: 60_000,
  })

  const domainGroups = catalog
    ? catalog.reduce<Record<string, FaultCatalogEntry[]>>((acc, e) => {
        acc[e.domain] = [...(acc[e.domain] ?? []), e]
        return acc
      }, {})
    : {}

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Fault Library</h1>
        <p className="text-sm text-slate-500 mt-1">
          Taxonomy-classified fault catalog + component rankings from observed scenarios
        </p>
      </div>

      {/* Rankings */}
      <div className="bg-card border border-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider font-mono">
          Component Rankings
        </h2>
        {rankLoading && <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>}
        {rankErr && (
          <div className="flex items-center gap-2 text-sm text-danger">
            <AlertCircle className="w-4 h-4" /> Fault library service unreachable
          </div>
        )}
        {rankings && rankings.rankings.length === 0 && (
          <p className="text-slate-500 text-sm">No ranked components yet — trigger scenarios to populate.</p>
        )}
        {rankings && rankings.rankings.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-slate-500 border-b border-border">
                  <th className="text-left pb-2 pr-4">#</th>
                  <th className="text-left pb-2 pr-4">Component</th>
                  <th className="text-left pb-2 pr-4">Domain</th>
                  <th className="text-right pb-2 pr-4">Transient</th>
                  <th className="text-right pb-2 pr-4">Cascading</th>
                  <th className="text-right pb-2 pr-4">Resource</th>
                  <th className="text-right pb-2 pr-4">Network</th>
                  <th className="text-right pb-2">Total</th>
                </tr>
              </thead>
              <tbody>
                {rankings.rankings.map((r, i) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-elevated/40 transition-colors">
                    <td className="py-1.5 pr-4 text-slate-600">{i + 1}</td>
                    <td className="py-1.5 pr-4 text-slate-200">{r.component}</td>
                    <td className="py-1.5 pr-4 text-slate-500">{r.domain}</td>
                    <td className="py-1.5 pr-4 text-right text-success">{r.tallies.transient}</td>
                    <td className="py-1.5 pr-4 text-right text-danger">{r.tallies.cascading}</td>
                    <td className="py-1.5 pr-4 text-right text-warning">{r.tallies.resource_exhaustion}</td>
                    <td className="py-1.5 pr-4 text-right text-cyan">{r.tallies.network_partition}</td>
                    <td className="py-1.5 text-right font-semibold text-slate-200">{r.tallies.total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[10px] text-slate-600 font-mono mt-3">
              {rankings.scenarios_considered} scenarios considered · {rankings.scenarios_excluded} excluded · {new Date(rankings.generated_at).toLocaleString()}
            </p>
          </div>
        )}
      </div>

      {/* Catalog */}
      <div>
        <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider font-mono">
          Fault Catalog
        </h2>
        {catLoading && <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>}
        {catErr && (
          <div className="flex items-center gap-2 text-sm text-danger">
            <AlertCircle className="w-4 h-4" /> Could not load catalog
          </div>
        )}
        {Object.entries(domainGroups).map(([domain, entries]) => (
          <div key={domain} className="mb-6">
            <p className="text-xs text-slate-500 font-mono uppercase tracking-widest mb-3">{domain}</p>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {entries.map(e => (
                <CatalogCard key={`${e.domain}/${e.fault_type}`} entry={e} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
