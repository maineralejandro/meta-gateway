import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useRouter } from 'next/router'
import { useWebSocket, ConnectionState } from '../hooks/useWebSocket'
import { useConversations, useMessages, useDecisions } from '../hooks/useConversationData'
import { buildWSHandlers } from '../hooks/useWSHandlers'
import { checkAuth, logout } from '../lib/auth'
import type { WSNotification, ErrorNotification } from '../lib/types'
import ConversationList from '../components/ConversationList'
import ChatPanel from '../components/ChatPanel'
import StateToggle from '../components/StateToggle'
import MessageInput from '../components/MessageInput'
import NotificationBanner from '../components/NotificationBanner'
import ErrorBanner from '../components/ErrorBanner'
import AgentEditor from '../components/AgentEditor'
import CatalogManager from '../components/CatalogManager'
import DecisionPanel from '../components/DecisionPanel'
import ConversationNotes from '../components/ConversationNotes'
import ObservabilityTab from '../components/observability/ObservabilityTab'

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080/ws'

export default function WhatsAppDashboard() {
  const router = useRouter()
  const [view, setView] = useState<'conversations' | 'agent' | 'catalog' | 'observability'>('conversations')
  const [selectedPhone, setSelectedPhone] = useState('')
  const [notifications, setNotifications] = useState<WSNotification[]>([])
  const [filterState, setFilterState] = useState<string | null>(null)
  const [inspectedMessageId, setInspectedMessageId] = useState<number | null>(null)
  const [authed, setAuthed] = useState(false)
  const [soundEnabled, setSoundEnabled] = useState(true)
  const lastActivityRef = useRef(Date.now())
  const IDLE_TIMEOUT = 30 * 60 * 1000
  const [mobileShowChat, setMobileShowChat] = useState(false)
  const [mobilePanel, setMobilePanel] = useState<'chat' | 'sidebar'>('chat')

  const { conversations, setConversations, loadConversations, updateState, closeSession, transferAgent, loadingConv, errors: convErrors, setErrors: setConvErrors } = useConversations()
  const { messages, setMessages, loadMessages, sendMessage, resetUnread, loadingMsgs, errors: msgErrors, setErrors: setMsgErrors } = useMessages()
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
    setMobileShowChat(true)
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

  const { connectionState } = useWebSocket(WS_BASE_URL, wsHandlers, undefined)

  useEffect(() => {
    checkAuth().then(ok => {
      if (ok) setAuthed(true)
      else router.replace('/login')
    })
  }, [router])

  useEffect(() => {
    setSoundEnabled(localStorage.getItem('hermes_sound') !== 'false')
  }, [])

  useEffect(() => {
    loadConversations()
    const interval = setInterval(loadConversations, 30000)
    return () => clearInterval(interval)
  }, [loadConversations])

  const selectedConversation = conversations.find(c => c.phone === selectedPhone)

  useEffect(() => {
    const resetIdle = () => { lastActivityRef.current = Date.now() }
    window.addEventListener('mousemove', resetIdle)
    window.addEventListener('keydown', resetIdle)
    window.addEventListener('click', resetIdle)
    const check = setInterval(() => {
      if (Date.now() - lastActivityRef.current > IDLE_TIMEOUT) {
        clearInterval(check)
        logout()
      }
    }, 15000)
    return () => {
      window.removeEventListener('mousemove', resetIdle)
      window.removeEventListener('keydown', resetIdle)
      window.removeEventListener('click', resetIdle)
      clearInterval(check)
    }
  }, [])

  useEffect(() => {
    if (view !== 'conversations') return
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      lastActivityRef.current = Date.now()
      const convs = conversations.filter(c => !filterState || c.state === filterState)
      const idx = convs.findIndex(c => c.phone === selectedPhone)
      if (e.key === 'ArrowUp' && idx > 0) {
        e.preventDefault()
        handleSelectPhone(convs[idx - 1].phone)
      } else if (e.key === 'ArrowDown' && idx < convs.length - 1) {
        e.preventDefault()
        handleSelectPhone(convs[idx + 1].phone)
      } else if (e.key === '1' && selectedPhone) {
        updateState(selectedPhone, 'BOT_ACTIVE')
      } else if (e.key === '2' && selectedPhone) {
        updateState(selectedPhone, 'PENDING_APPROVAL')
      } else if (e.key === '3' && selectedPhone) {
        updateState(selectedPhone, 'HUMAN_ONLY')
      } else if (e.key === 'Escape') {
        setSelectedPhone('')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [view, conversations, filterState, selectedPhone, handleSelectPhone, updateState])

  const handleInspectDecision = useCallback((messageId: number) => {
    setInspectedMessageId(messageId)
  }, [])

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden bg-gray-950 text-white">
      <nav className="h-14 border-b border-gray-800 bg-gray-900 flex items-center px-6 justify-between flex-shrink-0 z-20">
        <div className="flex items-center gap-8">
          <div className="text-emerald-500 font-bold text-xl tracking-tight">HERMES</div>
          <button
            onClick={() => {
              const next = soundEnabled ? 'false' : 'true'
              localStorage.setItem('hermes_sound', next)
              setSoundEnabled(!soundEnabled)
            }}
            className="px-2 py-1 text-xs text-gray-400 hover:text-gray-200 transition-colors"
            title={soundEnabled ? 'Silenciar alertas' : 'Activar alertas de sonido'}
          >
            {soundEnabled ? '🔊' : '🔇'}
          </button>
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${
              connectionState === 'connected' ? 'bg-green-500' :
              connectionState === 'reconnecting' ? 'bg-yellow-500 animate-pulse' :
              'bg-red-500 animate-pulse'
            }`} />
            <span className="text-xs text-gray-500">
              {connectionState === 'connected' ? 'Live' :
               connectionState === 'reconnecting' ? 'Reconectando...' :
               'Desconectado'}
            </span>
          </div>
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
          onClick={() => setView('catalog')}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${view === 'catalog' ? 'bg-gray-800 text-emerald-400' : 'text-gray-400 hover:text-gray-200'}`}
        >
          Catalogo
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
        <div className={`w-full md:w-80 border-r border-gray-800 bg-gray-900 flex-shrink-0 overflow-y-auto custom-scrollbar ${mobileShowChat ? 'hidden md:block' : ''}`}>
          <ConversationList
            conversations={conversations}
            selectedPhone={selectedPhone}
            onSelect={handleSelectPhone}
            filterState={filterState}
            onFilterChange={setFilterState}
            loading={loadingConv}
          />
        </div>

        <div className={`flex-1 flex flex-col bg-gray-950 min-h-0 ${!mobileShowChat && !selectedPhone ? 'hidden md:flex' : 'flex'}`}>
          {mobileShowChat && (
            <div className="md:hidden flex border-b border-gray-700">
              <button
                onClick={() => { setMobileShowChat(false); setMobilePanel('chat') }}
                className="px-3 py-2 text-sm text-gray-400 hover:text-white"
              >
                ← Volver
              </button>
              <div className="flex-1 flex">
                <button
                  onClick={() => setMobilePanel('chat')}
                  className={`flex-1 py-2 text-xs text-center ${mobilePanel === 'chat' ? 'text-emerald-400 border-b-2 border-emerald-500' : 'text-gray-500'}`}
                >
                  Chat
                </button>
                <button
                  onClick={() => setMobilePanel('sidebar')}
                  className={`flex-1 py-2 text-xs text-center ${mobilePanel === 'sidebar' ? 'text-emerald-400 border-b-2 border-emerald-500' : 'text-gray-500'}`}
                >
                  Estado y Notas
                </button>
              </div>
            </div>
          )}
          {mobileShowChat && mobilePanel === 'chat' && (
            <>
              <ChatPanel
                messages={messages}
                phone={selectedPhone}
                state={selectedConversation?.state || 'BOT_ACTIVE'}
                onInspectDecision={handleInspectDecision}
                loading={loadingMsgs}
              />
              <MessageInput
                phone={selectedPhone}
                state={selectedConversation?.state || 'BOT_ACTIVE'}
                onSend={sendMessage}
              />
            </>
          )}
          {mobileShowChat && mobilePanel === 'sidebar' && (
            <div className="flex-1 overflow-y-auto bg-gray-900 custom-scrollbar">
              <StateToggle
                currentState={selectedConversation?.state || 'BOT_ACTIVE'}
                phone={selectedPhone}
                onStateChange={updateState}
                onCloseSession={closeSession}
                onTransferAgent={transferAgent}
              />
              <ConversationNotes phone={selectedPhone} />
              {selectedConversation && (
                <DecisionPanel
                  conversation={selectedConversation}
                  decisions={decisions}
                  inspectedMessageId={inspectedMessageId}
                  onInspect={setInspectedMessageId}
                />
              )}
            </div>
          )}
          {!mobileShowChat && (
            <>
              <ChatPanel
                messages={messages}
                phone={selectedPhone}
                state={selectedConversation?.state || 'BOT_ACTIVE'}
                onInspectDecision={handleInspectDecision}
                loading={loadingMsgs}
              />
              <MessageInput
                phone={selectedPhone}
                state={selectedConversation?.state || 'BOT_ACTIVE'}
                onSend={sendMessage}
              />
            </>
          )}
        </div>

        <div className="hidden md:block w-72 border-l border-gray-800 bg-gray-900 flex-shrink-0 overflow-y-auto custom-scrollbar">
          <StateToggle
            currentState={selectedConversation?.state || 'BOT_ACTIVE'}
            phone={selectedPhone}
            onStateChange={updateState}
            onCloseSession={closeSession}
            onTransferAgent={transferAgent}
          />
          <ConversationNotes phone={selectedPhone} />

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
) : view === 'catalog' ? (
  <div className="flex-1 h-full">
    <CatalogManager />
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
