interface TraceStats {
  total: number
  llm: number
  fallback: number
  error: number
  avg_llm_latency: number
  avg_latency: number
}

interface Props {
  stats: TraceStats | null
}

function pct(part: number, total: number): string {
  if (total === 0) return '—'
  return ((part / total) * 100).toFixed(1) + '%'
}

function pctColor(rate: number, thresholds: [number, number]): string {
  if (rate <= thresholds[0]) return 'text-emerald-400'
  if (rate <= thresholds[1]) return 'text-yellow-400'
  return 'text-red-400'
}

function latencyColor(ms: number): string {
  if (ms < 1000) return 'text-emerald-400'
  if (ms < 3000) return 'text-yellow-400'
  return 'text-red-400'
}

export default function MetricCards({ stats }: Props) {
  if (!stats) {
    return (
      <div className="grid grid-cols-4 gap-3 p-3">
        {[0, 1, 2, 3].map(i => (
          <div key={i} className="bg-gray-800/50 border border-gray-700 rounded-xl p-3 animate-pulse">
            <div className="h-7 bg-gray-700 rounded mb-1" />
            <div className="h-3 bg-gray-700/50 rounded w-16" />
          </div>
        ))}
      </div>
    )
  }

  const fbRate = stats.total > 0 ? (stats.fallback / stats.total) * 100 : 0
  const errRate = stats.total > 0 ? (stats.error / stats.total) * 100 : 0

  const cards = [
    {
      value: String(stats.llm),
      label: 'RESP LLM',
      color: stats.llm > 0 ? 'text-emerald-400' : 'text-gray-500',
    },
    {
      value: stats.total > 0 ? pct(stats.fallback, stats.total) : '—',
      label: 'FALLBACK (24H)',
      color: pctColor(fbRate, [5, 15]),
    },
    {
      value: stats.total > 0 ? pct(stats.error, stats.total) : '—',
      label: 'ERROR (24H)',
      color: pctColor(errRate, [2, 5]),
    },
    {
      value: stats.avg_llm_latency > 0 ? `${stats.avg_llm_latency}ms` : '—',
      label: 'AVG LAT LLM',
      color: stats.avg_llm_latency > 0 ? latencyColor(stats.avg_llm_latency) : 'text-gray-500',
    },
  ]

  return (
    <div className="grid grid-cols-4 gap-3 p-3">
      {cards.map(c => (
        <div key={c.label} className="bg-gray-800/50 border border-gray-700 rounded-xl p-3">
          <div className={`text-2xl font-mono font-bold ${c.color}`}>{c.value}</div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mt-1">{c.label}</div>
        </div>
      ))}
    </div>
  )
}
