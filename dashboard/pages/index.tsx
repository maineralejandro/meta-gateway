import { useState, useEffect, useCallback } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { authFetch } from '../lib/auth'
import { wsUrlWithToken } from '../lib/auth'
import ConversationList from '../components/ConversationList'
import ChatPanel from '../components/ChatPanel'
import StateToggle from '../components/StateToggle'
import MessageInput from '../components/MessageInput'
import NotificationBanner from '../components/NotificationBanner'
import ErrorBanner from '../components/ErrorBanner'
import AgentEditor from '../components/AgentEditor'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'
const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080/ws'
const WS_URL = wsUrlWithToken(WS_BASE_URL)

interface Conversation {
  phone: string
  contact_name: string | null
  state: string
  last_message_at: string
  requires_human_review: number
  unread_count: number
  sentiment_score: number | null
  confidence: number | null
}

interface Message {
  id: number
  phone: string
  direction: string
  source: string
  text: string
  media_type: string | null
  created_at: string
}

interface WSNotification {
  id: string
  phone: string
  reason: string
  sentiment?: { score: number; sentiment: string; confidence: number }
  timestamp: number
}

interface ErrorNotification {
  id: string
  message: string
  timestamp: number
}

interface AgentDecision {
  id: number
  message_id: number | null
  phone: string
  sentiment: string
  sentiment_score: number
  confidence: number
  llm_escalate: number
  escalate_reason: string | null
  history_count: number
  agent_name: string
  created_at: string | null
}

function addError(prev: ErrorNotification[], message: string): ErrorNotification[] {
  return [{ id: `err-${Date.now()}`, message, timestamp: Date.now() }, ...prev].slice(0, 3)
}

export default function WhatsAppDashboard() {
  const [view, setView] = useState<'conversations' | 'agent'>('conversations')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedPhone, setSelectedPhone] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [notifications, setNotifications] = useState<WSNotification[]>([])
  const [errors, setErrors] = useState<ErrorNotification[]>([])
  const [filterState, setFilterState] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<AgentDecision[]>([])
  const [inspectedMessageId, setInspectedMessageId] = useState<number | null>(null)

  const loadConversations = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/conversations`)
      if (!res.ok) throw new Error(`Conversations: ${res.status} ${res.statusText}`)
      const data = await res.json()
      setConversations(data)
    } catch (e: any) {
      console.error('Failed to load conversations', e)
      setErrors(prev => addError(prev, e?.message || 'Error cargando conversaciones'))
    }
  }, [])

  const loadMessages = useCallback(async (phone: string) => {
    try {
      const res = await authFetch(`${API_URL}/api/messages/${phone}`)
      if (!res.ok) throw new Error(`Messages: ${res.status} ${res.statusText}`)
      const data = await res.json()
      setMessages(data)
    } catch (e: any) {
      console.error('Failed to load messages', e)
      setMessages([])
      setErrors(prev => addError(prev, e?.message || 'Error cargando mensajes'))
    }
  }, [])

  const resetUnread = useCallback(async (phone: string) => {
    try {
      await authFetch(`${API_URL}/api/conversations/${phone}/reset-unread`, { method: 'POST' })
    } catch {}
  }, [])

  const loadDecisions = useCallback(async (phone: string) => {
    try {
      const res = await authFetch(`${API_URL}/api/messages/${phone}/decisions`)
      if (!res.ok) throw new Error(`Decisions: ${res.status}`)
      const data = await res.json()
      setDecisions(data)
    } catch {
      setDecisions([])
    }
  }, [])

  const handleSelectPhone = useCallback((phone: string) => {
    setSelectedPhone(phone)
    loadMessages(phone)
    resetUnread(phone)
    loadDecisions(phone)
    setInspectedMessageId(null)
    setConversations(prev =>
      prev.map(c => c.phone === phone ? { ...c, unread_count: 0 } : c)
    )
    setView('conversations')
  }, [loadMessages, resetUnread, loadDecisions])

  const updateState = useCallback(async (phone: string, state: string) => {
    try {
      const res = await authFetch(`${API_URL}/api/conversations/state`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, state }),
      })
      if (!res.ok) throw new Error(`Update state: ${res.status} ${res.statusText}`)
      loadConversations()
    } catch (e: any) {
      console.error('Failed to update state', e)
      setErrors(prev => addError(prev, e?.message || 'Error actualizando estado'))
    }
  }, [loadConversations])

  const sendMessage = useCallback(async (phone: string, message: string) => {
    const tempId = -(Date.now())
    setMessages(prev => [...prev, {
      id: tempId,
      phone,
      direction: 'outbound',
      source: 'human',
      text: message,
      media_type: null,
      created_at: new Date().toISOString(),
    }])
    try {
      const res = await authFetch(`${API_URL}/api/messages/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, message }),
      })
      if (!res.ok) throw new Error(`Send message: ${res.status} ${res.statusText}`)
    } catch (e: any) {
      console.error('Failed to send message', e)
      setErrors(prev => addError(prev, e?.message || 'Error enviando mensaje'))
    }
  }, [])

  const wsHandlers = {
  'new-message': (data: any) => {
    setConversations(prev => {
      const existing = prev.find(c => c.phone === data.phone)
      if (existing) {
        return prev.map(c =>
          c.phone === data.phone
            ? { ...c, unread_count: c.phone === selectedPhone ? 0 : c.unread_count + 1, state: data.state || c.state }
            : c
        )
      }
      return [...prev, {
        phone: data.phone,
        contact_name: null,
        state: data.state || 'BOT_ACTIVE',
        last_message_at: new Date().toISOString(),
        requires_human_review: 0,
        unread_count: 1,
        sentiment_score: null,
        confidence: null,
      }]
    })
    if (data.phone === selectedPhone) {
      setMessages(prev => {
        const last = prev[prev.length - 1]
        if (last && last.direction === 'inbound' && last.source === 'customer' && last.text === data.message) {
          return prev
        }
        return [...prev, {
          id: Date.now(),
          phone: data.phone,
          direction: 'inbound',
          source: 'customer',
          text: data.message,
          media_type: null,
          created_at: new Date().toISOString(),
        }]
      })
    }
  },
  'bot-replied': (data: any) => {
    if (data.phone === selectedPhone) {
      const newId = data.message_id || Date.now() + 1
      setMessages(prev => {
        if (prev.some(m => m.id === newId)) return prev
        return [...prev, {
          id: newId,
          phone: data.phone,
          direction: 'outbound',
          source: 'bot',
          text: data.response,
          media_type: null,
          created_at: new Date().toISOString(),
        }]
      })
      if (data.decision) {
        setDecisions(prev => {
          if (prev.some(d => d.message_id === data.decision.message_id)) return prev
          return [data.decision, ...prev]
        })
      }
    }
    loadConversations()
  },
  'human-sent': (data: any) => {
    if (data.phone === selectedPhone) {
      setMessages(prev => {
        const tempIdx = prev.findIndex(m => m.id < 0 && m.source === 'human' && m.text === data.message && m.phone === data.phone)
        if (tempIdx !== -1) {
          const updated = [...prev]
          updated[tempIdx] = { ...updated[tempIdx], id: Date.now() + 2 }
          return updated
        }
        return [...prev, {
          id: Date.now() + 2,
          phone: data.phone,
          direction: 'outbound',
          source: 'human',
          text: data.message,
          media_type: null,
          created_at: new Date().toISOString(),
        }]
      })
    }
    loadConversations()
  },
  'escalated': (data: any) => {
    const notif: WSNotification = {
      id: `${data.phone}-${Date.now()}`,
      phone: data.phone,
      reason: data.reason || 'Escalada por sentimiento/confianza',
      sentiment: data.sentiment,
      timestamp: Date.now(),
    }
    setNotifications(prev => [notif, ...prev].slice(0, 5))
    setConversations(prev =>
      prev.map(c =>
        c.phone === data.phone
          ? { ...c, state: 'PENDING_APPROVAL', requires_human_review: 1, sentiment_score: data.sentiment?.score ?? c.sentiment_score }
          : c
      )
    )
    if (data.phone === selectedPhone) {
      if (data.decision?.message_id) {
        setMessages(prev => {
          if (prev.some(m => m.id === data.decision.message_id)) return prev
          return [...prev, {
            id: data.decision.message_id,
            phone: data.phone,
            direction: 'outbound',
            source: 'bot',
            text: 'Un momento, te comunico con un atendedor. 🙏',
            media_type: null,
            created_at: new Date().toISOString(),
          }]
        })
        setDecisions(prev => {
          if (prev.some(d => d.message_id === data.decision.message_id)) return prev
          return [data.decision, ...prev]
        })
      } else {
        loadMessages(selectedPhone)
        if (data.decision) {
          setDecisions(prev => [data.decision, ...prev])
        }
      }
    }
    setTimeout(() => {
      setNotifications(prev => prev.filter(n => n.id !== notif.id))
    }, 15000)
  },
    'state-changed': (data: any) => {
      setConversations(prev =>
        prev.map(c =>
          c.phone === data.phone
            ? { ...c, state: data.state, requires_human_review: data.state !== 'BOT_ACTIVE' ? 1 : 0 }
            : c
        )
      )
    },
  'waiting-for-human': (data: any) => {
    setConversations(prev =>
      prev.map(c =>
        c.phone === data.phone
          ? { ...c, state: 'HUMAN_ONLY', requires_human_review: 1 }
          : c
      )
    )
  },
    'error': (data: any) => {
      console.error('WS error event', data)
    },
  }

  useWebSocket(WS_URL, wsHandlers)

  useEffect(() => {
    loadConversations()
    const interval = setInterval(loadConversations, 30000)
    return () => clearInterval(interval)
  }, [loadConversations])

  const selectedConversation = conversations.find(c => c.phone === selectedPhone)

  const handleInspectDecision = useCallback((messageId: number) => {
    setInspectedMessageId(messageId)
  }, [])

  const inspectedDecision = inspectedMessageId
    ? decisions.find(d => d.message_id === inspectedMessageId)
    : null

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden bg-gray-950 text-white">
      {/* Navigation Bar */}
      <nav className="h-14 border-b border-gray-800 bg-gray-900 flex items-center px-6 justify-between flex-shrink-0 z-20">
        <div className="flex items-center gap-8">
          <div className="text-emerald-500 font-bold text-xl tracking-tight">HERMES</div>
          <div className="flex gap-4">
            <button 
              onClick={() => setView('conversations')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${view === 'conversations' ? 'bg-gray-800 text-emerald-400' : 'text-gray-400 hover:text-gray-200'}`}
            >
              Conversaciones
            </button>
            <button 
              onClick={() => setView('agent')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${view === 'agent' ? 'bg-gray-800 text-emerald-400' : 'text-gray-400 hover:text-gray-200'}`}
            >
              Gestión de Agente
            </button>
          </div>
        </div>
      </nav>

      <NotificationBanner
        notifications={notifications}
        onDismiss={id => setNotifications(prev => prev.filter(n => n.id !== id))}
        onClick={phone => handleSelectPhone(phone)}
      />
      <ErrorBanner
        errors={errors}
        onDismiss={id => setErrors(prev => prev.filter(e => e.id !== id))}
      />

      <div className="flex-1 flex min-h-0">
        {view === 'conversations' ? (
          <>
            <div className="w-80 border-r border-gray-800 bg-gray-900 flex-shrink-0 overflow-y-auto custom-scrollbar">
              <ConversationList
                conversations={conversations}
                selectedPhone={selectedPhone}
                onSelect={handleSelectPhone}
                filterState={filterState}
                onFilterChange={setFilterState}
              />
            </div>

            <div className="flex-1 flex flex-col bg-gray-950 min-h-0">
            <ChatPanel
              messages={messages}
              phone={selectedPhone}
              state={selectedConversation?.state || 'BOT_ACTIVE'}
              onInspectDecision={handleInspectDecision}
            />
              <MessageInput
                phone={selectedPhone}
                state={selectedConversation?.state || 'BOT_ACTIVE'}
                onSend={sendMessage}
              />
            </div>

          <div className="w-72 border-l border-gray-800 bg-gray-900 flex-shrink-0 overflow-y-auto custom-scrollbar">
            <StateToggle
              currentState={selectedConversation?.state || 'BOT_ACTIVE'}
              phone={selectedPhone}
              onStateChange={updateState}
            />

            {selectedConversation && (
              <div className="p-4 text-xs text-gray-400 space-y-4">
                {inspectedMessageId && inspectedDecision ? (
                  <>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setInspectedMessageId(null)}
                        className="text-blue-400 hover:text-blue-300 text-xs"
                      >
                        ← Volver
                      </button>
                      <h3 className="font-semibold text-gray-500 uppercase tracking-wider text-[10px]">Detalle decisión</h3>
                    </div>
                    <div className="bg-gray-800/50 p-3 rounded-xl border border-gray-700 space-y-2">
                      <div className="flex justify-between">
                        <span>Agente</span>
                        <span className="text-white font-medium">{inspectedDecision.agent_name || '—'}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Sentimiento</span>
                        <span className={
                          inspectedDecision.sentiment === 'negative' ? 'text-red-400' :
                          inspectedDecision.sentiment === 'positive' ? 'text-emerald-400' :
                          'text-yellow-400'
                        }>{inspectedDecision.sentiment}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Score sentimiento</span>
                        <span className={inspectedDecision.sentiment_score < 0.3 ? 'text-red-400' : inspectedDecision.sentiment_score < 0.6 ? 'text-yellow-400' : 'text-emerald-400'}>
                          {inspectedDecision.sentiment_score.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Confianza</span>
                        <span className={inspectedDecision.confidence < 0.7 ? 'text-red-400' : 'text-emerald-400'}>
                          {inspectedDecision.confidence.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>LLM escaló</span>
                        <span className={inspectedDecision.llm_escalate ? 'text-red-400' : 'text-gray-500'}>
                          {inspectedDecision.llm_escalate ? 'Sí' : 'No'}
                        </span>
                      </div>
                      {inspectedDecision.escalate_reason && (
                        <div className="pt-1 border-t border-gray-700">
                          <span className="block text-gray-500 mb-1">Razón escalado</span>
                          <span className="text-red-300">{inspectedDecision.escalate_reason}</span>
                        </div>
                      )}
                      <div className="flex justify-between">
                        <span>Historial msgs</span>
                        <span className="text-white">{inspectedDecision.history_count}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Msg ID</span>
                        <span className="text-gray-300 font-mono">{inspectedDecision.message_id}</span>
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <h3 className="font-semibold text-gray-500 uppercase tracking-wider">Decisiones del agente</h3>
                    {decisions.length === 0 ? (
                      <p className="text-gray-600 text-[11px]">Sin decisiones registradas</p>
                    ) : (
                      <div className="space-y-2">
                        {decisions.slice(0, 10).map(d => (
                          <button
                            key={d.id}
                            onClick={() => d.message_id && setInspectedMessageId(d.message_id)}
                            className="w-full text-left bg-gray-800/50 p-2.5 rounded-lg border border-gray-700 hover:border-blue-600/50 transition-all"
                          >
                            <div className="flex justify-between items-center mb-1">
                              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                                d.sentiment === 'negative' ? 'bg-red-900/40 text-red-400' :
                                d.sentiment === 'positive' ? 'bg-emerald-900/40 text-emerald-400' :
                                'bg-yellow-900/40 text-yellow-400'
                              }`}>{d.sentiment}</span>
                              <span className="text-gray-500 text-[10px]">
                                {d.created_at ? new Date(d.created_at).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' }) : ''}
                              </span>
                            </div>
                            <div className="flex justify-between text-[10px]">
                              <span className="text-gray-500">conf: <span className={d.confidence < 0.7 ? 'text-red-400' : 'text-emerald-400'}>{d.confidence.toFixed(2)}</span></span>
                              <span className="text-gray-500">score: <span className={d.sentiment_score < 0.3 ? 'text-red-400' : 'text-emerald-400'}>{d.sentiment_score.toFixed(2)}</span></span>
                            </div>
                            {d.escalate_reason && (
                              <div className="text-[10px] text-red-400 mt-1 truncate">{d.escalate_reason}</div>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="border-t border-gray-700 pt-3 space-y-2">
                      <h3 className="font-semibold text-gray-500 uppercase tracking-wider text-[10px]">Resumen conversación</h3>
                      <div className="bg-gray-800/50 p-3 rounded-xl border border-gray-700 space-y-2">
                        <div className="flex justify-between">
                          <span>Sentimiento</span>
                          <span className={selectedConversation.sentiment_score != null
                            ? (selectedConversation.sentiment_score < 0.3 ? 'text-red-400' :
                               selectedConversation.sentiment_score < 0.6 ? 'text-yellow-400' : 'text-emerald-400')
                            : 'text-gray-500'
                          }>
                            {selectedConversation.sentiment_score?.toFixed(2) ?? '—'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span>Confianza bot</span>
                          <span className={selectedConversation.confidence != null
                            ? (selectedConversation.confidence < 0.7 ? 'text-red-400' : 'text-emerald-400')
                            : 'text-gray-500'
                          }>
                            {selectedConversation.confidence?.toFixed(2) ?? '—'}
                          </span>
                        </div>
                      </div>
                      <div className="flex justify-between px-1">
                        <span>Mensajes sin leer</span>
                        <span className="bg-emerald-600 text-white px-1.5 py-0.5 rounded text-[10px] font-bold">
                          {selectedConversation.unread_count}
                        </span>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
          </>
        ) : (
          <div className="flex-1 h-full">
            <AgentEditor />
          </div>
        )}
      </div>
      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: #1f2937;
          border-radius: 10px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: #374151;
        }
      `}</style>
    </div>
  )
}
