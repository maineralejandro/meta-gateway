import { useState, useRef, useCallback } from 'react'
import { Copy, ChevronDown, ChevronRight } from 'lucide-react'
import JsonViewer from './JsonViewer'

interface TraceFull {
  id: number
  phone: string
  correlation_id: string
  agent_id: number | null
  request_messages: string
  response_raw: string | null
  response_source: 'llm' | 'fallback' | 'error'
  error_type: string | null
  error_message: string | null
  token_usage_prompt: number
  token_usage_completion: number
  latency_ms: number
  created_at: string
}

interface Props {
  trace: TraceFull | null
  width: number
}

const SOURCE_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  llm: { bg: 'bg-emerald-900/40', text: 'text-emerald-400', label: 'LLM' },
  fallback: { bg: 'bg-yellow-900/40', text: 'text-yellow-400', label: 'FALLBACK' },
  error: { bg: 'bg-red-900/40', text: 'text-red-400', label: 'ERROR' },
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button onClick={handleCopy} className="p-1 hover:bg-gray-700 rounded transition-colors" title="Copiar">
      <Copy size={11} className={copied ? 'text-emerald-400' : 'text-gray-500'} />
    </button>
  )
}

function Section({ title, defaultOpen = true, children, copyText }: { title: string; defaultOpen?: boolean; children: React.ReactNode; copyText?: string }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-gray-800/50 hover:bg-gray-800 transition-colors text-left"
      >
        {open ? <ChevronDown size={12} className="text-gray-500" /> : <ChevronRight size={12} className="text-gray-500" />}
        <span className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold flex-1">{title}</span>
        {copyText && open && <CopyButton text={copyText} />}
      </button>
      {open && <div className="p-2">{children}</div>}
    </div>
  )
}

function latencyColor(ms: number): string {
  if (ms < 1000) return 'text-emerald-400'
  if (ms < 3000) return 'text-yellow-400'
  return 'text-red-400'
}

export default function TraceDetail({ trace, width }: Props) {
  if (!trace) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-xs">
        Selecciona un trace para ver el detalle
      </div>
    )
  }

  const src = SOURCE_CONFIG[trace.response_source] || SOURCE_CONFIG.error
  const time = new Date(trace.created_at).toLocaleString('es-CL')

  const requestSize = trace.request_messages?.length || 0
  const responseSize = trace.response_raw?.length || 0

  return (
    <div className="flex flex-col h-full overflow-y-auto custom-scrollbar p-3 space-y-3" style={{ minWidth: 280 }}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 bg-gray-800/50 border border-gray-700 rounded-xl p-3">
        <MetaRow label="ID" value={String(trace.id)} />
        <MetaRow label="Corr ID" value={trace.correlation_id} mono />
        <MetaRow label="Agente" value={trace.agent_id != null ? String(trace.agent_id) : '—'} />
        <MetaRow
          label="Source"
          value={
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${src.bg} ${src.text}`}>
              {src.label}
            </span>
          }
        />
        <MetaRow label="Latencia" value={`${trace.latency_ms}ms`} color={latencyColor(trace.latency_ms)} mono />
        <MetaRow label="Tokens" value={`${trace.token_usage_prompt}/${trace.token_usage_completion}`} mono />
        <MetaRow label="Telefono" value={trace.phone} mono />
        <MetaRow label="Fecha" value={time} />
      </div>

      <Section
        title={`Request Messages (${(requestSize / 1024).toFixed(1)}KB)`}
        defaultOpen={requestSize < 500}
        copyText={trace.request_messages}
      >
        <JsonViewer data={trace.request_messages} collapsed={requestSize > 2000} />
      </Section>

      <Section
        title={`Response Raw (${(responseSize / 1024).toFixed(1)}KB)`}
        defaultOpen={responseSize < 500}
        copyText={trace.response_raw || ''}
      >
        <JsonViewer data={trace.response_raw || ''} collapsed={responseSize > 2000} />
      </Section>

      {trace.response_source === 'error' && trace.error_type && (
        <Section title="Error" defaultOpen={true}>
          <div className="space-y-2">
            <div>
              <span className="text-[10px] text-gray-500 uppercase tracking-wider">Tipo</span>
              <p className="text-red-400 font-mono text-xs mt-0.5">{trace.error_type}</p>
            </div>
            {trace.error_message && (
              <div>
                <span className="text-[10px] text-gray-500 uppercase tracking-wider">Mensaje</span>
                <p className="text-red-300 text-xs mt-0.5 whitespace-pre-wrap break-words font-mono">{trace.error_message}</p>
              </div>
            )}
          </div>
        </Section>
      )}
    </div>
  )
}

function MetaRow({ label, value, mono, color }: { label: string; value: React.ReactNode; mono?: boolean; color?: string }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</span>
      <span className={`text-xs font-medium ${mono ? 'font-mono' : ''} ${color || 'text-white'}`}>
        {value}
      </span>
    </div>
  )
}

export function ResizablePanel({
  children,
  initialWidth,
  minWidth = 280,
  maxWidth = 1200,
  onWidthChange,
}: {
  children: React.ReactNode
  initialWidth: number
  minWidth?: number
  maxWidth?: number
  onWidthChange: (w: number) => void
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(initialWidth)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = initialWidth
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [initialWidth])

  const onMouseMove = useCallback((e: MouseEvent) => {
    if (!dragging.current) return
    const delta = startX.current - e.clientX
    const newWidth = Math.min(maxWidth, Math.max(minWidth, startWidth.current + delta))
    onWidthChange(newWidth)
  }, [minWidth, maxWidth, onWidthChange])

  const onMouseUp = useCallback(() => {
    dragging.current = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [onMouseMove])

  return (
    <div ref={panelRef} className="flex h-full" style={{ width: initialWidth }}>
      <div
        className="w-1 cursor-col-resize hover:bg-blue-500/30 active:bg-blue-500/50 transition-colors flex-shrink-0"
        onMouseDown={onMouseDown}
      />
      <div className="flex-1 min-w-0 overflow-hidden border-l border-gray-800">
        {children}
      </div>
    </div>
  )
}
