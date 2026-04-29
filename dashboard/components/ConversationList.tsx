import { useEffect, useState } from 'react'

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

interface Props {
  conversations: Conversation[]
  selectedPhone: string
  onSelect: (phone: string) => void
  filterState: string | null
  onFilterChange: (state: string | null) => void
}

const STATE_CONFIG: Record<string, { bg: string; dot: string; label: string }> = {
  BOT_ACTIVE: { bg: 'bg-green-900/40', dot: 'bg-green-500', label: 'BOT' },
  PENDING_APPROVAL: { bg: 'bg-yellow-900/40', dot: 'bg-yellow-500', label: 'PENDING' },
  HUMAN_ONLY: { bg: 'bg-red-900/40', dot: 'bg-red-500', label: 'HUMAN' },
}

export default function ConversationList({ conversations, selectedPhone, onSelect, filterState, onFilterChange }: Props) {
  const filtered = filterState ? conversations.filter(c => c.state === filterState) : conversations

  const counts = {
    BOT_ACTIVE: conversations.filter(c => c.state === 'BOT_ACTIVE').length,
    PENDING_APPROVAL: conversations.filter(c => c.state === 'PENDING_APPROVAL').length,
    HUMAN_ONLY: conversations.filter(c => c.state === 'HUMAN_ONLY').length,
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-gray-700">
        <h2 className="text-lg font-bold mb-2">Conversaciones</h2>
        <div className="flex gap-1 text-xs">
          <button
            onClick={() => onFilterChange(null)}
            className={`px-2 py-1 rounded ${!filterState ? 'bg-gray-500' : 'bg-gray-700 hover:bg-gray-600'}`}
          >
            Todas ({conversations.length})
          </button>
          <button
            onClick={() => onFilterChange('BOT_ACTIVE')}
            className={`px-2 py-1 rounded ${filterState === 'BOT_ACTIVE' ? 'bg-green-700' : 'bg-gray-700 hover:bg-gray-600'}`}
          >
            🟢 {counts.BOT_ACTIVE}
          </button>
          <button
            onClick={() => onFilterChange('PENDING_APPROVAL')}
            className={`px-2 py-1 rounded ${filterState === 'PENDING_APPROVAL' ? 'bg-yellow-700' : 'bg-gray-700 hover:bg-gray-600'}`}
          >
            🟡 {counts.PENDING_APPROVAL}
          </button>
          <button
            onClick={() => onFilterChange('HUMAN_ONLY')}
            className={`px-2 py-1 rounded ${filterState === 'HUMAN_ONLY' ? 'bg-red-700' : 'bg-gray-700 hover:bg-gray-600'}`}
          >
            🔴 {counts.HUMAN_ONLY}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 && (
          <p className="text-gray-500 text-sm p-4 text-center">No hay conversaciones</p>
        )}
        {filtered.map(c => {
          const cfg = STATE_CONFIG[c.state] || STATE_CONFIG.BOT_ACTIVE
          const isSelected = c.phone === selectedPhone
          return (
            <div
              key={c.phone}
              onClick={() => onSelect(c.phone)}
              className={`p-3 cursor-pointer border-b border-gray-800 hover:bg-gray-800/50 transition-colors ${isSelected ? 'bg-gray-800' : ''} ${cfg.bg}`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${cfg.dot} ${c.state === 'PENDING_APPROVAL' ? 'animate-pulse-dot' : ''}`} />
                  <span className="font-mono text-sm">{c.phone}</span>
                </div>
                <div className="flex items-center gap-2">
                  {c.unread_count > 0 && (
                    <span className="bg-blue-600 text-white text-xs px-1.5 py-0.5 rounded-full font-bold">
                      {c.unread_count}
                    </span>
                  )}
                  <span className={`text-xs px-1.5 py-0.5 rounded ${cfg.dot}/20 text-white`}>
                    {cfg.label}
                  </span>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400 truncate">
                  {c.contact_name || 'Sin nombre'}
                </span>
                {c.sentiment_score != null && (
                  <span className={`text-xs ${c.sentiment_score < 0.3 ? 'text-red-400' : c.sentiment_score < 0.6 ? 'text-yellow-400' : 'text-green-400'}`}>
                    😐 {c.sentiment_score.toFixed(2)}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
