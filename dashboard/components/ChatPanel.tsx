import { useEffect, useRef } from 'react'

interface Message {
  id: number
  phone: string
  direction: string
  source: string
  text: string
  media_type: string | null
  created_at: string
  meta_message_id?: string | null
  meta_status?: string | null
}

interface Props {
  messages: Message[]
  phone: string
  state: string
  onInspectDecision?: (messageId: number) => void
}

const SOURCE_STYLE: Record<string, { bubble: string; prefix: string }> = {
  customer: { bubble: 'bg-gray-700 text-white', prefix: '' },
  bot: { bubble: 'bg-blue-900/60 text-blue-100', prefix: '🤖' },
  human: { bubble: 'bg-green-900/60 text-green-100', prefix: '👤' },
}

export default function ChatPanel({ messages, phone, state, onInspectDecision }: Props) {
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
        {messages.length === 0 && (
          <p className="text-gray-500 text-sm text-center">No hay mensajes</p>
        )}
        {messages.map(msg => {
          const style = SOURCE_STYLE[msg.source] || SOURCE_STYLE.customer
          const isCustomer = msg.direction === 'inbound'
          const isTemp = msg.id < 0
          const isPending = !isCustomer && !isTemp && !msg.meta_message_id
          return (
            <div key={msg.id} className={`flex ${isCustomer ? 'justify-start' : 'justify-end'}`}>
              <div className={`max-w-[75%] rounded-lg px-3 py-2 ${style.bubble} ${isTemp || isPending ? 'opacity-60' : ''} ${msg.source === 'bot' && onInspectDecision ? 'cursor-pointer hover:ring-1 hover:ring-blue-500/50 transition-all' : ''}`}
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
                <p className="text-sm whitespace-pre-wrap">{msg.text}</p>
                <span className="text-xs opacity-40 block mt-1 text-right">
                  {isTemp && <span className="text-gray-400 mr-1">Enviando...</span>}
                  {isPending && <span className="text-yellow-500 mr-1">⏳ Pendiente</span>}
                  {msg.meta_status && <span className="text-gray-500 mr-1">{msg.meta_status}</span>}
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
