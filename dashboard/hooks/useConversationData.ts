import { useState, useCallback } from 'react'
import { authFetch } from '../lib/auth'
import type { Conversation, Message, AgentDecision, ErrorNotification } from '../lib/types'
import { addError } from '../lib/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [errors, setErrors] = useState<ErrorNotification[]>([])
  const [loadingConv, setLoadingConv] = useState(false)

  const loadConversations = useCallback(async () => {
    setLoadingConv(true)
    try {
      const res = await authFetch(`${API_URL}/api/conversations`)
      if (!res.ok) throw new Error(`Conversations: ${res.status} ${res.statusText}`)
      const data = await res.json()
      setConversations(data)
    } catch (e: any) {
      console.error('Failed to load conversations', e)
      setErrors(prev => addError(prev, e?.message || 'Error cargando conversaciones'))
    } finally {
      setLoadingConv(false)
    }
  }, [])

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

  const closeSession = useCallback(async (phone: string) => {
    try {
      const res = await authFetch(`${API_URL}/api/conversations/${phone}/close-session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ summary: '' }),
      })
      if (!res.ok) throw new Error(`Close session: ${res.status} ${res.statusText}`)
      loadConversations()
    } catch (e: any) {
      console.error('Failed to close session', e)
      setErrors(prev => addError(prev, e?.message || 'Error cerrando sesion'))
    }
  }, [loadConversations])

  const transferAgent = useCallback(async (phone: string, agentId: number) => {
    try {
      const res = await authFetch(`${API_URL}/api/conversations/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, agent_id: agentId }),
      })
      if (!res.ok) throw new Error(`Transfer agent: ${res.status}`)
      loadConversations()
    } catch (e: any) {
      setErrors(prev => addError(prev, e?.message || 'Error transfiriendo agente'))
    }
  }, [loadConversations])

  return { conversations, setConversations, loadConversations, updateState, closeSession, transferAgent, loadingConv, errors, setErrors }
}

export function useMessages() {
  const [messages, setMessages] = useState<Message[]>([])
  const [msgErrors, setMsgErrors] = useState<ErrorNotification[]>([])
  const [loadingMsgs, setLoadingMsgs] = useState(false)

  const loadMessages = useCallback(async (phone: string) => {
    setLoadingMsgs(true)
    try {
      const res = await authFetch(`${API_URL}/api/messages/${phone}`)
      if (!res.ok) throw new Error(`Messages: ${res.status} ${res.statusText}`)
      const data = await res.json()
      setMessages(data)
    } catch (e: any) {
      console.error('Failed to load messages', e)
      setMsgErrors(prev => addError(prev, e?.message || 'Error cargando mensajes'))
    } finally {
      setLoadingMsgs(false)
    }
  }, [])

  const sendMessage = useCallback(async (phone: string, message: string) => {
    const tempId = -(Date.now())
    setMessages(prev => [...prev, {
      id: tempId, phone, direction: 'outbound', source: 'human',
      text: message, media_type: null, media_url: null, created_at: new Date().toISOString(),
    }])

    const timeoutId = setTimeout(() => {
      setMessages(prev => prev.map(m =>
        m.id === tempId ? { ...m, _error: true } : m
      ))
    }, 10000)

    try {
      const res = await authFetch(`${API_URL}/api/messages/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, message }),
      })
      if (!res.ok) throw new Error(`Send message: ${res.status} ${res.statusText}`)
    } catch (e: any) {
      clearTimeout(timeoutId)
      setMessages(prev => prev.filter(m => m.id !== tempId))
      setMsgErrors(prev => addError(prev, e?.message || 'Error enviando mensaje'))
    }
  }, [])

  const resetUnread = useCallback(async (phone: string) => {
    try {
      await authFetch(`${API_URL}/api/conversations/${phone}/reset-unread`, { method: 'POST' })
    } catch {
      setMsgErrors(prev => addError(prev, 'Error reseteando unread'))
    }
  }, [])

  return { messages, setMessages, loadMessages, sendMessage, resetUnread, loadingMsgs, errors: msgErrors, setErrors: setMsgErrors }
}

export function useDecisions() {
  const [decisions, setDecisions] = useState<AgentDecision[]>([])

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

  return { decisions, setDecisions, loadDecisions }
}
