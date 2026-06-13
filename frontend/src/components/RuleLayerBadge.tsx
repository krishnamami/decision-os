import type { RuleLayer } from '../config/ruleLabels'

const LAYER_CONFIG: Record<RuleLayer, { emoji: string; label: string; colors: string }> = {
  federal: {
    emoji: '🔒',
    label: 'Federal',
    colors: 'bg-red-50 text-red-700 border border-red-200',
  },
  agency: {
    emoji: '📋',
    label: 'Agency',
    colors: 'bg-blue-50 text-blue-700 border border-blue-200',
  },
  lender: {
    emoji: '🔧',
    label: 'Your Policy',
    colors: 'bg-green-50 text-green-700 border border-green-200',
  },
  // Engine fallbacks / cross-check routing that aren't a federal, agency, or
  // lender rule (e.g. "default escalate", "Combined underwriting routing decision").
  system: {
    emoji: '⚙️',
    label: 'System',
    colors: 'bg-slate-50 text-slate-700 border border-slate-200',
  },
}

export function RuleLayerBadge({ layer }: { layer: RuleLayer }) {
  const cfg = LAYER_CONFIG[layer]
  return (
    <span className={`mr-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.colors}`}>
      {cfg.emoji} {cfg.label}
    </span>
  )
}
