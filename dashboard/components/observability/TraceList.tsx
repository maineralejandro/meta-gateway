interface TraceSummary {
  id: number
  phone: string
  correlation_id: string
  response_source: 'llm' | 'fallback' | 'error'
  error_type: string | null
  token_usage_prompt: number
  token_usage_completion: number
  latency_ms: number
  created_at: string
}

interface Props {
  traces: TraceSummary[]
  selectedTraceId: number | null
  onSelect: (id: number) => void
  loading: boolean
  filter: 'all' | 'llm' | 'fallback' | 'error'
  onFilterChange: (f: 'all' | 'llm' | 'fallback' | 'error') => void
  sortKey: 'created_at' | 'latency_ms'
  sortDir: 'asc' | 'desc'
  onSort: (key: 'created_at' | 'latency_ms') => void
}

const SOURCE_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  llm: { bg: 'bg-emerald-900/40', text: 'text-emerald-400', label: 'LLM' },
  fallback: { bg: 'bg-yellow-900/40', text: 'text-yellow-400', label: 'FB' },
  error: { bg: 'bg-red-900/40', text: 'text-red-400', label: 'ERR' },
}

function formatTime(ts: string): string {
  return new Date(ts).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function latencyColor(ms: number): string {
  if (ms < 1000) return 'text-emerald-400'
  if (ms < 3000) return 'text-yellow-400'
  return 'text-red-400'
}

export default function TraceList({ traces, selectedTraceId, onSelect, loading, filter, onFilterChange, sortKey, sortDir, onSort }: Props) {
  const filters: { value: Props['filter']; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'llm', label: 'LLM' },
    { value: 'fallback', label: 'Fallback' },
    { value: 'error', label: 'Error' },
  ]

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 px-3 py-2 border-b border-gray-800">
        {filters.map(f => (
          <button
            key={f.value}
            onClick={() => onFilterChange(f.value)}
            className={`px-2 py-1 rounded text-[10px] font-semibold uppercase tracking-wider transition-colors ${
              filter === f.value ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800'
            }`}
          >
            {f.label}
          </button>
        ))}
        <div className="flex-1" />
        <span className="text-[10px] text-gray-600 font-mono">{traces.length} traces</span>
      </div>

      <div className="flex items-center px-3 py-1 border-b border-gray-800 text-[10px] uppercase tracking-wider text-gray-500">
        <span className="w-28">Telefono</span>
        <span className="w-14">Source</span>
        <button onClick={() => onSort('latency_ms')} className="w-16 text-left hover:text-gray-300 transition-colors">
          Lat {sortKey === 'latency_ms' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
        </button>
        <span className="w-20">Tokens</span>
        <button onClick={() => onSort('created_at')} className="flex-1 text-right hover:text-gray-300 transition-colors">
          Time {sortKey === 'created_at' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {loading && traces.length === 0 && (
          <div className="p-4 text-center text-gray-600 text-xs">Cargando traces...</div>
        )}
        {!loading && traces.length === 0 && (
          <div className="p-4 text-center text-gray-600 text-xs">No hay traces recientes</div>
        )}
        {traces.map(t => {
          const src = SOURCE_CONFIG[t.response_source] || SOURCE_CONFIG.error
          const isSelected = t.id === selectedTraceId
          return (
            <div
              key={t.id}
              onClick={() => onSelect(t.id)}
              className={`flex items-center px-3 py-1.5 border-b border-gray-800/50 cursor-pointer transition-colors h-8 ${
                isSelected ? 'bg-blue-900/20 border-l-2 border-l-blue-500' : 'hover:bg-gray-800/50'
              }`}
            >
              <span className="w-28 text-[11px] font-mono text-gray-300 truncate">{t.phone}</span>
              <span className="w-14">
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${src.bg} ${src.text}`}>
                  {src.label}
                </span>
              </span>
              <span className={`w-16 text-[11px] font-mono ${latencyColor(t.latency_ms)}`}>
                {t.latency_ms}ms
              </span>
              <span className="w-20 text-[10px] text-gray-500 font-mono">
                {t.token_usage_prompt}/{t.token_usage_completion}
              </span>
              <span className="flex-1 text-right text-[10px] text-gray-500 font-mono">
                {formatTime(t.created_at)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
