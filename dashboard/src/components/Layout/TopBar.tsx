import useSWR from 'swr'
import { Activity, Network, Shield } from 'lucide-react'
import { fetchHealth as graphHealth } from '../../api/graph'
import { fetchHealth as chaosHealth } from '../../api/chaos'
import { fetchHealth as faultlibHealth } from '../../api/faultlib'

interface ServiceDot {
  label: string
  fetcher: () => Promise<{ status: string }>
}

const SERVICES: ServiceDot[] = [
  { label: 'graph',    fetcher: graphHealth    },
  { label: 'chaos',    fetcher: chaosHealth    },
  { label: 'faultlib', fetcher: faultlibHealth },
]

const ARGUS_URL = import.meta.env.VITE_ARGUS_URL
const SENTINEL_URL = import.meta.env.VITE_SENTINEL_URL

function ConsoleLink({ href, label, title, className, icon: Icon }: {
  href?: string
  label: string
  title: string
  className: string
  icon: typeof Shield
}) {
  const styles = `flex items-center gap-1.5 rounded-md px-2.5 py-1.5 transition-colors ${className}`
  return href
    ? <a href={href} title={title} className={styles}><Icon className="w-3 h-3" />{label}</a>
    : <span aria-disabled="true" title={`${label} URL is not configured`} className={`${styles} cursor-not-allowed opacity-35`}><Icon className="w-3 h-3" />{label}</span>
}

function ProductSwitcher() {
  return (
    <nav aria-label="Sentinel platform consoles" className="flex items-center rounded-lg border border-border bg-card/70 p-0.5 font-mono text-[10px]">
      <ConsoleLink href={ARGUS_URL} label="Argus" title="Open Argus Security Console" icon={Shield} className="text-cyan hover:bg-cyan/10 hover:text-cyan-200" />
      <span aria-current="page" title="Current console: Phoenix Resilience" className="flex items-center gap-1.5 rounded-md border border-accent/25 bg-accent/10 px-2.5 py-1.5 font-bold text-accent shadow-[0_0_12px_rgba(0,230,118,.08)]"><Activity className="w-3 h-3" />Phoenix</span>
      <ConsoleLink href={SENTINEL_URL} label="Sentinel" title="Open Sentinel Command Center" icon={Network} className="text-violet hover:bg-violet/10 hover:text-violet-200" />
    </nav>
  )
}

function HealthDot({ label, fetcher }: ServiceDot) {
  const { data, error, isValidating } = useSWR(`health/${label}`, fetcher, {
    refreshInterval: 8_000,
    shouldRetryOnError: false,
  })

  const ok = !error && data?.status === 'ok'
  const dotColor = error ? 'bg-danger' : !data ? 'bg-slate-600' : ok ? 'bg-accent' : 'bg-warning'

  return (
    <div className="flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full ${dotColor} ${ok ? 'animate-pulse' : ''}`} />
      <span className={`text-xs font-mono ${ok ? 'text-accent/80' : 'text-slate-500'}`}>
        {label}
      </span>
      {isValidating && (
        <span className="w-1 h-1 rounded-full bg-accent/40 animate-ping" />
      )}
    </div>
  )
}

export default function TopBar() {
  return (
    <header className="h-12 border-b border-border bg-surface/80 backdrop-blur-sm flex items-center justify-between px-6 sticky top-0 z-20">
      <div className="flex items-center gap-4"><p className="hidden xl:block text-[10px] text-slate-600 font-mono tracking-widest uppercase">self-healing k8s</p><ProductSwitcher /></div>

      <div className="flex items-center gap-6">
        {/* Service health */}
        <div className="flex items-center gap-4">
          {SERVICES.map(s => <HealthDot key={s.label} {...s} />)}
        </div>

        {/* Divider */}
        <span className="w-px h-4 bg-border" />

        {/* LIVE indicator */}
        <div className="flex items-center gap-1.5">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-50" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-accent" />
          </span>
          <span className="text-[11px] font-mono font-bold tracking-widest text-accent uppercase">
            Live
          </span>
        </div>
      </div>
    </header>
  )
}
