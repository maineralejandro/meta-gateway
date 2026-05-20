import { useState, useEffect, useCallback, useMemo } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { useConversations, useMessages, useDecisions } from '../hooks/useConversationData'
import { buildWSHandlers } from '../hooks/useWSHandlers'
import type { WSNotification, ErrorNotification } from '../lib/types'
import ConversationList from '../components/ConversationList'
import ChatPanel from '../components/ChatPanel'
import StateToggle from '../components/StateToggle'
import MessageInput from '../components/MessageInput'
import NotificationBanner from '../components/NotificationBanner'
import ErrorBanner from '../components/ErrorBanner'
import AgentEditor from '../components/AgentEditor'
import DecisionPanel from '../components/DecisionPanel'
import ObservabilityTab from '../components/observability/ObservabilityTab'

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080/ws'
const DASHBOARD_TOKEN = process.env.NEXT_PUBLIC_DASHBOARD_TOKEN || ''

export default function WhatsAppDashboard() {
  const [view, setView] = useState<'conversations' | 'agent' | 'observability'>('conversations')
  const [selectedPhone, setSelectedPhone] = useState('')
  const [notifications, setNotifications] = useState<WSNotification[]>([])
  const [filterState, setFilterState] = useState<string | null>(null)
  const [inspectedMessageId, setInspectedMessageId] = useState<number | null>(null)

  const { conversations, setConversations, loadConversations, updateState, errors: convErrors, setErrors: setConvErrors } = useConversations()
  const { messages, setMessages, loadMessages, sendMessage, resetUnread, errors: msgErrors, setErrors: setMsgErrors } = useMessages()
  const { decisions, setDecisions, loadDecisions } = useDecisions()

  const allErrors = useMemo<ErrorNotification[]>(
    () => [...convErrors, ...msgErrors].sort((a, b) => b.timestamp - a.timestamp).slice(0, 5),
    [convErrors, msgErrors]
  )

  const dismissError = useCallback((id: string) => {
    setConvErrors(prev => prev.filter(e => e.id !== id))
    setMsgErrors(prev => prev.filter(e => e.id !== id))
  }, [setConvErrors, setMsgErrors])

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
  }, [loadMessages, resetUnread, loadDecisions, setConversations])

  const wsHandlers = useMemo(() => buildWSHandlers({
    selectedPhone,
    setConversations,
    setMessages,
    setDecisions,
    setNotifications,
    loadConversations,
    loadMessages,
  }), [selectedPhone, setConversations, setMessages, setDecisions, loadConversations, loadMessages])

  useWebSocket(WS_BASE_URL, wsHandlers, DASHBOARD_TOKEN)

  useEffect(() => {
    loadConversations()
    const interval = setInterval(loadConversations, 30000)
    return () => clearInterval(interval)
  }, [loadConversations])

  const selectedConversation = conversations.find(c => c.phone === selectedPhone)

  const handleInspectDecision = useCallback((messageId: number) => {
    setInspectedMessageId(messageId)
  }, [])

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden bg-gray-950 text-white">
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
          Gestion de Agente
        </button>
        <button
          onClick={() => setView('observability')}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${view === 'observability' ? 'bg-gray-800 text-emerald-400' : 'text-gray-400 hover:text-gray-200'}`}
        >
          Diagnostico
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
        errors={allErrors}
        onDismiss={dismissError}
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
              <DecisionPanel
                conversation={selectedConversation}
                decisions={decisions}
                inspectedMessageId={inspectedMessageId}
                onInspect={setInspectedMessageId}
              />
            )}
          </div>
          </>
) : view === 'agent' ? (
  <div className="flex-1 h-full">
    <AgentEditor />
  </div>
) : (
  <div className="flex-1 h-full">
    <ObservabilityTab />
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
