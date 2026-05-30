import React from 'react'
import { render, screen } from '@testing-library/react'
import ChatPanel from '../components/ChatPanel'

describe('ChatPanel', () => {
  it('shows placeholder when no phone is selected', () => {
    render(<ChatPanel messages={[]} phone="" state="BOT_ACTIVE" />)
    expect(screen.getByText('Selecciona una conversación')).toBeInTheDocument()
  })

  it('shows empty state when no messages', () => {
    render(<ChatPanel messages={[]} phone="+5691234" state="BOT_ACTIVE" />)
    expect(screen.getByText('No hay mensajes')).toBeInTheDocument()
  })

  it('renders messages with correct source styling', () => {
    const messages = [
      { id: 1, phone: '+5691234', direction: 'inbound', source: 'customer', text: 'Hola', media_type: null, media_url: null, created_at: '2024-01-01T12:00:00Z' },
      { id: 2, phone: '+5691234', direction: 'outbound', source: 'bot', text: 'Bienvenido', media_type: null, media_url: null, created_at: '2024-01-01T12:00:01Z' },
    ]
    render(<ChatPanel messages={messages} phone="+5691234" state="BOT_ACTIVE" />)
    expect(screen.getByText('Hola')).toBeInTheDocument()
    expect(screen.getByText('Bienvenido')).toBeInTheDocument()
  })

  it('shows conversation state badge', () => {
    render(<ChatPanel messages={[]} phone="+5691234" state="PENDING_APPROVAL" />)
    expect(screen.getByText('PENDING_APPROVAL')).toBeInTheDocument()
  })
})
