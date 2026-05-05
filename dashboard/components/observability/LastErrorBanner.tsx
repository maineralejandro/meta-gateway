import { useState, useEffect } from 'react'
import { X } from 'lucide-react'

interface LastError {
  id: number
  phone: string
  correlation_id: string
  error_type: string
  error_message: string
  created_at: string
}

interface Props {
  error: LastError | null
}

export default function LastErrorBanner({ error }: Props) {
  const [dismissed, setDismissed] = useState(false)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    setDismissed(false)
  }, [error?.id])

  useEffect(() => {
    if (!error) return
    const timer = setTimeout(() => setDismissed(true), 60000)
    return () => clearTimeout(timer)
  }, [error])

  if (!error || dismissed) return null

  const time = new Date(error.created_at).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

  return (
    <div
      className="mx-3 mt-2 bg-red-900/20 border border-red-700/40 rounded-lg px-3 py-2 cursor-pointer hover:bg-red-900/30 transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-red-500 text-xs font-bold flex-shrink-0">ERROR</span>
          <span className="text-red-300 text-xs font-mono truncate">{error.error_type}</span>
          <span className="text-gray-600 text-xs">—</span>
          <span className="text-red-200/80 text-xs truncate">{error.error_message}</span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-2">
          <span className="text-gray-500 text-[10px] font-mono">{error.phone}</span>
          <span className="text-gray-600 text-[10px] font-mono">{time}</span>
          <button
            onClick={e => { e.stopPropagation(); setDismissed(true) }}
            className="p-0.5 hover:bg-red-800 rounded"
          >
            <X size={12} className="text-red-400" />
          </button>
        </div>
      </div>
      {expanded && (
        <div className="mt-1.5 pt-1.5 border-t border-red-800/50 text-[10px] text-gray-400 font-mono">
          corr_id: {error.correlation_id} | trace_id: {error.id}
        </div>
      )}
    </div>
  )
}
