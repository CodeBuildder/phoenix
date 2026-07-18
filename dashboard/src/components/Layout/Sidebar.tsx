import { NavLink } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  Library,
  Zap,
} from 'lucide-react'

const links = [
  { to: '/overview',  icon: LayoutDashboard, label: 'Overview' },
  { to: '/incidents', icon: AlertTriangle,    label: 'Incidents' },
  { to: '/topology',  icon: GitBranch,        label: 'Topology' },
  { to: '/chaos',     icon: FlaskConical,     label: 'Chaos Lab' },
  { to: '/faultlib',  icon: Library,          label: 'Fault Library' },
  { to: '/agent',     icon: Zap,              label: 'Agent' },
]

export default function Sidebar() {
  return (
    <aside className="flex flex-col w-56 min-h-screen bg-surface border-r border-border shrink-0">
      <div className="flex items-center gap-2 px-5 h-14 border-b border-border">
        <Activity className="w-5 h-5 text-accent" />
        <span className="font-mono text-sm font-bold tracking-widest uppercase" style={{ color: '#00e676' }}>
          Phoenix
        </span>
      </div>

      <nav className="flex flex-col gap-1 p-3 flex-1">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              [
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                isActive
                  ? 'bg-elevated text-accent font-medium'
                  : 'text-slate-400 hover:text-slate-100 hover:bg-elevated',
              ].join(' ')
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-4 pb-4">
        <p className="text-xs text-slate-600 font-mono">argus / phoenix</p>
      </div>
    </aside>
  )
}
