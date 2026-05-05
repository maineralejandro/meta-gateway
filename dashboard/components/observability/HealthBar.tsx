import { Activity, RefreshCw } from 'lucide-react'

interface TraceStats {
  total: number
  llm: number
  fallback: number
  error: number
}

interface HealthDetail {
  llm: {
    available: boolean
    model: string
    base_url: string
    key_prefix: string
  }
  trace_stats_24h: TraceStats
  last_error: any
}

interface Props {
  health: HealthDetail | null
  lastRefresh: Date | null
  onRefresh: () => void
  loading: boolean
}

function formatTime(d: Date | null): string {
  if (!d) return '—'
  return d.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function HealthBar({ health, lastRefresh, onRefresh, loading }: Props) {
  const llm = health?.llm
  const stats = health?.trace_stats_24h

  return (
    <div className="h-12 border-b border-gray-800 bg-gray-900 flex items-center px-4 gap-4 flex-shrink-0">
      <div className="flex items-center gap-2">
        <Activity size={14} className="text-gray-500" />
        <span className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">LLM</span>
        {llm ? (
          <span className={`flex items-center gap-1.5 text-xs font-medium ${llm.available ? 'text-emerald-400' : 'text-red-400'}`}>
            <span className={`w-2 h-2 rounded-full ${llm.available ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
            {llm.available ? 'Disponible' : 'NO DISPONIBLE'}
          </span>
        ) : (
          <span className="text-gray-600 text-xs">cargando...</span>
        )}
      </div>

      {llm && (
        <>
          <div className="h-4 w-px bg-gray-700" />
          <span className="text-[10px] text-gray-500 font-mono truncate max-w-[200px]" title={llm.model}>
            {llm.model}
          </span>
          <div className="h-4 w-px bg-gray-700" />
          <span className="text-[10px] text-gray-500 font-mono">{llm.key_prefix}</span>
        </>
      )}

      {stats && (
        <>
          <div className="h-4 w-px bg-gray-700" />
          <div className="flex items-center gap-2 text-[10px] font-mono">
            <span className="text-gray-500">24h:</span>
            <span className="text-emerald-400">{stats.llm}</span>
            <span className="text-gray-600">/</span>
            <span className="text-yellow-400">{stats.fallback}</span>
            <span className="text-gray-600">/</span>
            <span className="text-red-400">{stats.error}</span>
          </div>
        </>
      )}

      <div className="flex-1" />

      <span className="text-[10px] text-gray-600 font-mono">
        {formatTime(lastRefresh)}
      </span>
      <button
        onClick={onRefresh}
        disabled={loading}
        className="p-1 hover:bg-gray-800 rounded transition-colors disabled:opacity-30"
      >
        <RefreshCw size={13} className={`text-gray-400 ${loading ? 'animate-spin' : ''}`} />
      </button>
    </div>
  )
}
