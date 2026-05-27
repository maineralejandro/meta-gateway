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
  meta_message_id?: string | null
  meta_status?: string | null
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

export interface CatalogVariant {
  id: number
  item_key: string
  label: string
  price: number
  slug: string
  sort_order: number
}

export interface CatalogItem {
  key: string
  name: string
  price: number
  category: string
  subcategory: string
  description: string
  tags: string[]
  size: string
  specifications: string
  is_available: boolean
  sort_order: number
  base_price: number | null
  image_url: string | null
  variants: CatalogVariant[]
}

export interface CatalogOption {
  key: string
  name: string
  price: number
  category_scope: string
  sort_order: number
}

export interface PromotionItem {
  promotion_key: string
  item_key: string
  promotion_price: number | null
}

export interface Promotion {
  key: string
  name: string
  promotion_type: string
  price: number | null
  valid_days: string[]
  valid_from: string
  valid_to: string
  terms: string
  display_text: string
  sort_order: number
  items: PromotionItem[]
}

export interface CapabilitySchema {
  key: string
  type: 'string' | 'integer' | 'boolean' | 'object' | 'array'
  label: string
  default: any
}

export interface CapabilityDetail {
  name: string
  description: string
  config_schema: CapabilitySchema[]
}

export interface AgentCapabilityState {
  id: number | null
  agent_id: number
  capability_name: string
  is_active: boolean
  config_json: string
}

export function addError(prev: ErrorNotification[], message: string): ErrorNotification[] {
  return [{ id: `err-${Date.now()}`, message, timestamp: Date.now() }, ...prev].slice(0, 3)
}
