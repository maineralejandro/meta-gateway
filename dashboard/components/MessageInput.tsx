import { useState, useEffect, KeyboardEvent } from 'react'
import { Send } from 'lucide-react'

const DEFAULT_QUICK_REPLIES = [
  'Un momento por favor',
  'Tu pedido esta en camino',
  'En que mas puedo ayudarte?',
  'Gracias por tu compra!',
  'Voy a revisarlo',
]

interface Props {
  phone: string
  state: string
  onSend: (phone: string, message: string) => void
}

export default function MessageInput({ phone, state, onSend }: Props) {
  const [text, setText] = useState('')
  const [replies, setReplies] = useState<string[]>(DEFAULT_QUICK_REPLIES)
  const [customReply, setCustomReply] = useState('')
  const [showAddReply, setShowAddReply] = useState(false)

  useEffect(() => {
    const saved = localStorage.getItem('hermes_quick_replies')
    if (saved) {
      try { setReplies(JSON.parse(saved)) } catch {}
    }
  }, [])

  const addCustomReply = () => {
    if (!customReply.trim()) return
    const next = [...replies, customReply.trim()]
    setReplies(next)
    localStorage.setItem('hermes_quick_replies', JSON.stringify(next))
    setCustomReply('')
    setShowAddReply(false)
  }

  const handleSend = () => {
    if (!text.trim() || !phone) return
    onSend(phone, text.trim())
    setText('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const canSend = phone && (state === 'HUMAN_ONLY' || state === 'PENDING_APPROVAL')

  return (
    <div className="p-3 border-t border-gray-700">
      {canSend && (
        <div className="mb-2">
          <div className="flex gap-1 overflow-x-auto pb-1 scrollbar-hide">
            {replies.map(qr => (
              <button
                key={qr}
                onClick={() => onSend(phone, qr)}
                className="whitespace-nowrap px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded-full transition-colors border border-gray-600"
              >
                {qr}
              </button>
            ))}
            <button
              onClick={() => setShowAddReply(!showAddReply)}
              className="whitespace-nowrap px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-500 text-xs rounded-full transition-colors border border-gray-700 border-dashed"
            >
              + Agregar
            </button>
          </div>
          {showAddReply && (
            <div className="flex gap-1 mt-1">
              <input
                value={customReply}
                onChange={e => setCustomReply(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addCustomReply()}
                placeholder="Nueva respuesta rapida..."
                className="flex-1 bg-gray-800 text-white rounded px-2 py-1 text-xs border border-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
                autoFocus
              />
              <button
                onClick={addCustomReply}
                disabled={!customReply.trim()}
                className="px-2 py-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-30 text-white text-xs rounded"
              >
                Guardar
              </button>
            </div>
          )}
        </div>
      )}
      <div className="flex items-end gap-2">
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            !phone ? 'Selecciona una conversacion...' :
            canSend ? 'Escribe tu respuesta manual...' :
            'Cambia a modo Humano para responder manualmente'
          }
          disabled={!canSend}
          rows={2}
          className="flex-1 bg-gray-800 text-white rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
        />
        <button
          onClick={handleSend}
          disabled={!canSend || !text.trim()}
          className="p-2 bg-blue-600 hover:bg-blue-500 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <Send size={18} />
        </button>
      </div>
      {!canSend && phone && (
        <p className="text-xs text-gray-500 mt-1">
          Para responder manualmente, cambia el estado a "Solo Humano" o "Pendiente"
        </p>
      )}
    </div>
  )
}
