interface Props {
  currentState: string
  phone: string
  onStateChange: (phone: string, state: string) => void
  onCloseSession: (phone: string) => void
}

const STATES = [
  { value: 'BOT_ACTIVE', label: 'Bot Activo', color: 'bg-green-600 hover:bg-green-500', icon: '🤖' },
  { value: 'PENDING_APPROVAL', label: 'Pendiente', color: 'bg-yellow-600 hover:bg-yellow-500', icon: '⏳' },
  { value: 'HUMAN_ONLY', label: 'Solo Humano', color: 'bg-red-600 hover:bg-red-500', icon: '👤' },
]

export default function StateToggle({ currentState, phone, onStateChange, onCloseSession }: Props) {
  if (!phone) return null

  return (
    <div className="p-4 border-b border-gray-700">
      <h3 className="text-sm font-semibold text-gray-400 mb-2">ESTADO DE CONVERSACIÓN</h3>
      <div className="space-y-2">
        {STATES.map(s => (
          <button
            key={s.value}
            onClick={() => {
              if (s.value !== currentState) onStateChange(phone, s.value)
            }}
            disabled={s.value === currentState}
            className={`w-full py-2 px-3 rounded text-sm font-medium flex items-center justify-between transition-colors ${
              s.value === currentState
                ? `${s.color} text-white ring-2 ring-white/20 cursor-default`
                : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
            }`}
          >
            <span>{s.icon} {s.label}</span>
            {s.value === currentState && <span className="text-xs">● Activo</span>}
          </button>
        ))}
      </div>
      <div className="mt-4 pt-4 border-t border-gray-700">
        <button
          onClick={() => {
            if (confirm('Cerrar sesion y resetear a Bot Activo?')) onCloseSession(phone)
          }}
          className="w-full py-2 px-3 rounded text-sm font-medium flex items-center justify-center gap-2 bg-gray-800 hover:bg-red-900/50 hover:text-red-300 text-gray-400 transition-colors border border-gray-700"
        >
          ✕ Cerrar Sesion
        </button>
      </div>
    </div>
  )
}
