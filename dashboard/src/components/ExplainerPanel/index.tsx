import { X, Zap, Activity, FlaskConical, ChevronRight } from 'lucide-react'
import type { ExplainerContent } from './explain'

const BADGE_STYLES: Record<string, string> = {
  green:  'bg-accent/10 text-accent border-accent/30',
  yellow: 'bg-warning/10 text-warning border-warning/30',
  red:    'bg-danger/10 text-danger border-danger/30',
  cyan:   'bg-cyan/10 text-cyan border-cyan/30',
  violet: 'bg-violet/10 text-violet border-violet/30',
}

const ICONS: Record<string, React.ElementType> = {
  service:  Zap,
  flow:     Activity,
  scenario: FlaskConical,
}

export default function ExplainerPanel({
  content,
  targetKind,
  onClose,
}: {
  content: ExplainerContent
  targetKind: 'service' | 'flow' | 'scenario'
  onClose: () => void
}) {
  const Icon = ICONS[targetKind] ?? Zap
  const badgeStyle = BADGE_STYLES[content.badgeColor] ?? BADGE_STYLES.green

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 backdrop-blur-[2px] z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="panel-slide-in fixed right-0 top-0 bottom-0 w-[420px] bg-surface border-l border-border z-50 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-4 border-b border-border">
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center shrink-0 mt-0.5">
              <Icon className="w-4 h-4 text-accent" />
            </div>
            <div className="min-w-0">
              <h2 className="font-mono font-bold text-slate-100 text-sm leading-snug truncate">
                {content.title}
              </h2>
              <p className="text-[11px] text-slate-500 font-mono mt-0.5">{content.subtitle}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className={`px-2 py-0.5 rounded-full border text-[10px] font-mono uppercase tracking-wide ${badgeStyle}`}>
              {content.badge}
            </span>
            <button
              onClick={onClose}
              className="w-7 h-7 rounded-lg flex items-center justify-center text-slate-500 hover:text-slate-200 hover:bg-elevated transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Agent label */}
        <div className="flex items-center gap-2 px-5 py-2.5 bg-accent/5 border-b border-border/50">
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent" />
          </span>
          <span className="text-[10px] font-mono text-accent/80 uppercase tracking-widest">
            Phoenix Agent · live analysis from cluster data
          </span>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5 fade-in">
          {content.sections.map((section, i) => (
            <div key={i} className="space-y-2">
              <p className="text-[10px] font-mono font-semibold text-slate-500 uppercase tracking-widest">
                {section.heading}
              </p>
              <div className="space-y-1.5">
                {section.lines.map((line, j) => (
                  <p key={j} className="text-xs text-slate-300 leading-relaxed">
                    {line}
                  </p>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Recommended actions */}
        {content.actions.length > 0 && (
          <div className="border-t border-border px-5 py-4 space-y-2 bg-elevated/30">
            <p className="text-[10px] font-mono font-semibold text-accent/70 uppercase tracking-widest">
              Recommended actions
            </p>
            {content.actions.map((action, i) => (
              <div key={i} className="flex items-start gap-2">
                <ChevronRight className="w-3 h-3 text-accent shrink-0 mt-0.5" />
                <p className="text-xs text-slate-300 leading-relaxed">{action}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
