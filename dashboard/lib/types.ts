export interface Conversation {
  phone: string
  contact_name: string | null
  state: string
  last_message_at: string
  requires_human_review: number
  unread_count: number
  sentiment_score: number | null
  confidence: number | null
}

export interface Message {
  id: number
  phone: string
  direction: string
  source: string
  text: string
  media_type: string | null
  created_at: string
}

export interface WSNotification {
  id: string
  phone: string
  reason: string
  sentiment?: { score: number; sentiment: string; confidence: number }
  timestamp: number
}

export interface ErrorNotification {
  id: string
  message: string
  timestamp: number
}

export interface AgentDecision {
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

export function addError(prev: ErrorNotification[], message: string): ErrorNotification[] {
  return [{ id: `err-${Date.now()}`, message, timestamp: Date.now() }, ...prev].slice(0, 3)
}
