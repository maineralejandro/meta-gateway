import { useState, useEffect } from 'react'
import { authFetch } from '../lib/auth'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

interface Agent {
  id: number
  name: string
}

interface Props {
  currentState: string
  phone: string
  onStateChange: (phone: string, state: string) => void
  onCloseSession: (phone: string) => void
  onTransferAgent?: (phone: string, agentId: number) => Promise<void>
}

const STATES = [
  { value: 'BOT_ACTIVE', label: 'Bot Activo', color: 'bg-green-600 hover:bg-green-500', icon: '🤖' },
  { value: 'PENDING_APPROVAL', label: 'Pendiente', color: 'bg-yellow-600 hover:bg-yellow-500', icon: '⏳' },
  { value: 'HUMAN_ONLY', label: 'Solo Humano', color: 'bg-red-600 hover:bg-red-500', icon: '👤' },
]

export default function StateToggle({ currentState, phone, onStateChange, onCloseSession, onTransferAgent }: Props) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [transferring, setTransferring] = useState(false)
  const [pendingState, setPendingState] = useState<string | null>(null)
  const [pendingClose, setPendingClose] = useState(false)

  useEffect(() => {
    if (!phone) return
    authFetch(`${API_URL}/api/agents`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setAgents(data.map((a: any) => ({ id: a.id, name: a.name }))))
      .catch(() => {})
  }, [phone])

  const handleTransfer = async (agentId: number) => {
    if (!agentId || !onTransferAgent) return
    setTransferring(true)
    try {
      await onTransferAgent(phone, agentId)
    } finally {
      setTransferring(false)
    }
  }

  if (!phone) return null

  return (
    <div className="p-4 border-b border-gray-700">
      <h3 className="text-sm font-semibold text-gray-400 mb-2">ESTADO DE CONVERSACION</h3>
      <div className="space-y-2">
        {STATES.map(s => (
          <button
            key={s.value}
            onClick={() => {
              if (s.value !== currentState) setPendingState(s.value)
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

      {pendingState && (
        <div className="mt-2 bg-gray-800 rounded p-2 border border-gray-600">
          <p className="text-xs text-gray-300 mb-2">Cambiar estado a &quot;{STATES.find(s => s.value === pendingState)?.label}&quot;?</p>
          <div className="flex gap-2">
            <button
              onClick={() => { onStateChange(phone, pendingState); setPendingState(null) }}
              className="flex-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white text-xs rounded"
            >
              Confirmar
            </button>
            <button
              onClick={() => setPendingState(null)}
              className="flex-1 px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      <div className="mt-4 pt-4 border-t border-gray-700">
        <button
          onClick={() => setPendingClose(true)}
          className="w-full py-2 px-3 rounded text-sm font-medium flex items-center justify-center gap-2 bg-gray-800 hover:bg-red-900/50 hover:text-red-300 text-gray-400 transition-colors border border-gray-700"
        >
          ✕ Cerrar Sesion
        </button>
      </div>

      {pendingClose && (
        <div className="mt-2 bg-gray-800 rounded p-2 border border-red-900/50">
          <p className="text-xs text-gray-300 mb-2">Cerrar sesion y resetear a Bot Activo?</p>
          <div className="flex gap-2">
            <button
              onClick={() => { onCloseSession(phone); setPendingClose(false) }}
              className="flex-1 px-2 py-1 bg-red-600 hover:bg-red-500 text-white text-xs rounded"
            >
              Cerrar
            </button>
            <button
              onClick={() => setPendingClose(false)}
              className="flex-1 px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {agents.length > 1 && (
        <div className="mt-3 pt-3 border-t border-gray-700">
          <label className="text-xs text-gray-500 block mb-1">Transferir a agente</label>
          <select
            onChange={async (e) => {
              const agentId = Number(e.target.value)
              if (!agentId) return
              await handleTransfer(agentId)
              e.target.value = ''
            }}
            disabled={transferring}
            className="w-full bg-gray-800 text-gray-300 rounded px-2 py-1.5 text-sm border border-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
            defaultValue=""
          >
            <option value="" disabled>{transferring ? 'Transfiriendo...' : 'Seleccionar agente...'}</option>
            {agents.map(a => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}
