import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import ConversationList from '../components/ConversationList'

const mockConversations = [
  {
    phone: '+5691111',
    contact_name: 'Juan',
    state: 'BOT_ACTIVE',
    last_message_at: '2024-01-01T12:00:00Z',
    requires_human_review: 0,
    unread_count: 0,
    sentiment_score: 0.8,
    confidence: 0.9,
  },
  {
    phone: '+5692222',
    contact_name: null,
    state: 'PENDING_APPROVAL',
    last_message_at: '2024-01-01T12:01:00Z',
    requires_human_review: 1,
    unread_count: 3,
    sentiment_score: 0.2,
    confidence: 0.6,
  },
]

describe('ConversationList', () => {
  const mockOnSelect = jest.fn()
  const mockOnFilterChange = jest.fn()

  it('renders conversations with phone numbers', () => {
    render(
      <ConversationList
        conversations={mockConversations}
        selectedPhone=""
        onSelect={mockOnSelect}
        filterState={null}
        onFilterChange={mockOnFilterChange}
      />
    )
    expect(screen.getByText('+5691111')).toBeInTheDocument()
    expect(screen.getByText('+5692222')).toBeInTheDocument()
  })

  it('shows unread count badge', () => {
    render(
      <ConversationList
        conversations={mockConversations}
        selectedPhone=""
        onSelect={mockOnSelect}
        filterState={null}
        onFilterChange={mockOnFilterChange}
      />
    )
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('shows empty state when no conversations', () => {
    render(
      <ConversationList
        conversations={[]}
        selectedPhone=""
        onSelect={mockOnSelect}
        filterState={null}
        onFilterChange={mockOnFilterChange}
      />
    )
    expect(screen.getByText('No hay conversaciones')).toBeInTheDocument()
  })

  it('calls onSelect when clicking a conversation', () => {
    render(
      <ConversationList
        conversations={mockConversations}
        selectedPhone=""
        onSelect={mockOnSelect}
        filterState={null}
        onFilterChange={mockOnFilterChange}
      />
    )
    fireEvent.click(screen.getByText('+5691111'))
    expect(mockOnSelect).toHaveBeenCalledWith('+5691111')
  })
})
