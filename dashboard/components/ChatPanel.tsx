import { useEffect, useRef } from 'react'
import { FileText, Music } from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

interface Message {
  id: number
  phone: string
  direction: string
  source: string
  text: string
  media_type: string | null
  media_url: string | null
  meta_message_id?: string | null
  created_at: string
  meta_status?: string | null
  _error?: boolean
}

interface Props {
  messages: Message[]
  phone: string
  state: string
  onInspectDecision?: (messageId: number) => void
  loading?: boolean
}

const SOURCE_STYLE: Record<string, { bubble: string; prefix: string }> = {
  customer: { bubble: 'bg-gray-700 text-white', prefix: '' },
  bot: { bubble: 'bg-blue-900/60 text-blue-100', prefix: '🤖' },
  human: { bubble: 'bg-green-900/60 text-green-100', prefix: '👤' },
}

function MediaRenderer({ msg }: { msg: Message }) {
  const mediaId = msg.media_url
  if (!msg.media_type || !mediaId) return null

  const proxyUrl = `${API_URL}/api/messages/media-proxy/${encodeURIComponent(mediaId)}`

  if (msg.media_type === 'image') {
    return (
      <img
        src={proxyUrl}
        alt={msg.text || 'Imagen'}
        className="max-w-full rounded mt-1 mb-1 cursor-pointer"
        onClick={() => window.open(proxyUrl, '_blank')}
        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
      />
    )
  }
  if (msg.media_type === 'audio' || msg.media_type === 'voice') {
    return (
      <div className="flex items-center gap-2 mt-1 mb-1 text-sm opacity-70">
        <Music size={14} />
        <audio controls src={proxyUrl} className="h-8 max-w-[200px]" />
      </div>
    )
  }
  if (msg.media_type === 'document' || msg.media_type === 'sticker' || msg.media_type === 'video') {
    return (
      <a
        href={proxyUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-2 mt-1 mb-1 text-xs text-blue-300 hover:text-blue-200 underline"
      >
        {msg.media_type === 'video' ? '🎬' : <FileText size={14} />}
        {msg.media_type === 'video' ? 'Ver video' : msg.media_type === 'sticker' ? 'Ver sticker' : 'Ver documento'}
      </a>
    )
  }
  return null
}

export default function ChatPanel({ messages, phone, state, onInspectDecision, loading }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  if (!phone) {
    return (
      <div className="flex flex-1 items-center justify-center min-h-0 text-gray-500">
        Selecciona una conversación
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="p-3 border-b border-gray-700 flex items-center justify-between">
        <div>
          <h3 className="font-mono font-bold">{phone}</h3>
          <span className={`text-xs px-2 py-0.5 rounded ${
            state === 'BOT_ACTIVE' ? 'bg-green-900/40 text-green-400' :
            state === 'PENDING_APPROVAL' ? 'bg-yellow-900/40 text-yellow-400' :
            'bg-red-900/40 text-red-400'
          }`}>
            {state}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loading && messages.length === 0 && (
          <div className="space-y-3">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className={`flex ${i % 2 === 0 ? 'justify-end' : 'justify-start'}`}>
                <div className="animate-pulse max-w-[60%] rounded-lg px-3 py-2 bg-gray-800">
                  <div className="h-3 bg-gray-700 rounded w-32 mb-1" />
                  <div className="h-2 bg-gray-700 rounded w-16" />
                </div>
              </div>
            ))}
          </div>
        )}
        {!loading && messages.length === 0 && (
          <p className="text-gray-500 text-sm text-center">No hay mensajes</p>
        )}
        {messages.map(msg => {
          const style = SOURCE_STYLE[msg.source] || SOURCE_STYLE.customer
          const isCustomer = msg.direction === 'inbound'
          const isTemp = msg.id < 0
          const isPending = !isCustomer && !isTemp && !msg.meta_message_id
          return (
            <div key={msg.id} className={`flex ${isCustomer ? 'justify-start' : 'justify-end'}`}>
              <div className={`max-w-[75%] rounded-lg px-3 py-2 ${style.bubble} ${isTemp || isPending ? 'opacity-60' : ''} ${msg._error ? 'ring-1 ring-red-500/50' : ''} ${msg.source === 'bot' && onInspectDecision ? 'cursor-pointer hover:ring-1 hover:ring-blue-500/50 transition-all' : ''}`}
                onClick={() => msg.source === 'bot' && onInspectDecision && onInspectDecision(msg.id)}
              >
                {msg.source !== 'customer' && (
                  <span className="text-xs opacity-60 block mb-1">
                    {style.prefix} {msg.source}
                    {msg.source === 'bot' && onInspectDecision && (
                      <span className="ml-1 opacity-70" title="Ver decisión del agente">🧠</span>
                    )}
                  </span>
                )}
                <MediaRenderer msg={msg} />
                {msg.text && <p className="text-sm whitespace-pre-wrap">{msg.text}</p>}
                <span className="text-xs opacity-40 block mt-1 text-right">
                  {isTemp && <span className="text-gray-400 mr-1">Enviando...</span>}
                  {msg._error && <span className="text-red-400 mr-1">✕ Error</span>}
                  {isPending && !msg._error && <span className="text-yellow-500 mr-1">⏳ Pendiente</span>}
                  {!isCustomer && !isTemp && (
                    <span className="mr-1">
                      {msg.meta_status === 'read' && <span className="text-blue-400">✓✓</span>}
                      {msg.meta_status === 'delivered' && <span className="text-gray-400">✓✓</span>}
                      {msg.meta_status === 'sent' && <span className="text-gray-500">✓</span>}
                      {!msg.meta_status && !isPending && <span className="text-gray-600">✓</span>}
                    </span>
                  )}
                  {new Date(msg.created_at).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
