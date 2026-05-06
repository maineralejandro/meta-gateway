import { useCallback } from 'react'
import type { Conversation, Message, AgentDecision, WSNotification } from '../lib/types'

interface WSHandlersDeps {
  selectedPhone: string
  setConversations: React.Dispatch<React.SetStateAction<Conversation[]>>
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  setDecisions: React.Dispatch<React.SetStateAction<AgentDecision[]>>
  setNotifications: React.Dispatch<React.SetStateAction<WSNotification[]>>
  loadConversations: () => Promise<void>
  loadMessages: (phone: string) => Promise<void>
}

export function buildWSHandlers(deps: WSHandlersDeps): Record<string, (data: any) => void> {
  const {
    selectedPhone,
    setConversations,
    setMessages,
    setDecisions,
    setNotifications,
    loadConversations,
    loadMessages,
  } = deps

  return {
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
              text: 'Un momento, te comunico con un atendedor.',
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
}
