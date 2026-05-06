import { useState, useCallback } from 'react'
import { authFetch } from '../lib/auth'
import type { Conversation, Message, AgentDecision, ErrorNotification } from '../lib/types'
import { addError } from '../lib/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [errors, setErrors] = useState<ErrorNotification[]>([])

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

  return { conversations, setConversations, loadConversations, updateState, errors, setErrors }
}

export function useMessages() {
  const [messages, setMessages] = useState<Message[]>([])
  const [msgErrors, setMsgErrors] = useState<ErrorNotification[]>([])

  const loadMessages = useCallback(async (phone: string) => {
    try {
      const res = await authFetch(`${API_URL}/api/messages/${phone}`)
      if (!res.ok) throw new Error(`Messages: ${res.status} ${res.statusText}`)
      const data = await res.json()
      setMessages(data)
    } catch (e: any) {
      console.error('Failed to load messages', e)
      setMessages([])
      setMsgErrors(prev => addError(prev, e?.message || 'Error cargando mensajes'))
    }
  }, [])

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
      setMsgErrors(prev => addError(prev, e?.message || 'Error enviando mensaje'))
    }
  }, [])

  const resetUnread = useCallback(async (phone: string) => {
    try {
      await authFetch(`${API_URL}/api/conversations/${phone}/reset-unread`, { method: 'POST' })
    } catch {}
  }, [])

  return { messages, setMessages, loadMessages, sendMessage, resetUnread, errors: msgErrors, setErrors: setMsgErrors }
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
