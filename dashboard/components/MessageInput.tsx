import { useState, KeyboardEvent } from 'react'
import { Send } from 'lucide-react'

interface Props {
  phone: string
  state: string
  onSend: (phone: string, message: string) => void
  disabled?: boolean
}

export default function MessageInput({ phone, state, onSend, disabled }: Props) {
  const [text, setText] = useState('')

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
      <div className="flex items-end gap-2">
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            !phone ? 'Selecciona una conversación...' :
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
