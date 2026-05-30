import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import StateToggle from '../components/StateToggle'

describe('StateToggle', () => {
  const mockOnStateChange = jest.fn()
  const mockOnCloseSession = jest.fn()

  it('renders nothing when no phone is selected', () => {
    const { container } = render(
      <StateToggle currentState="BOT_ACTIVE" phone="" onStateChange={mockOnStateChange} onCloseSession={mockOnCloseSession} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders all three state buttons', () => {
    render(
      <StateToggle currentState="BOT_ACTIVE" phone="+5691234" onStateChange={mockOnStateChange} onCloseSession={mockOnCloseSession} />
    )
    expect(screen.getByText(/Bot Activo/)).toBeInTheDocument()
    expect(screen.getByText(/Pendiente/)).toBeInTheDocument()
    expect(screen.getByText(/Solo Humano/)).toBeInTheDocument()
  })

  it('shows active state indicator', () => {
    render(
      <StateToggle currentState="BOT_ACTIVE" phone="+5691234" onStateChange={mockOnStateChange} onCloseSession={mockOnCloseSession} />
    )
    expect(screen.getByText(/Activo/)).toBeInTheDocument()
  })

  it('shows confirmation when clicking a different state', () => {
    render(
      <StateToggle currentState="BOT_ACTIVE" phone="+5691234" onStateChange={mockOnStateChange} onCloseSession={mockOnCloseSession} />
    )
    fireEvent.click(screen.getByText(/Solo Humano/))
    expect(screen.getByText(/Confirmar/)).toBeInTheDocument()
  })

  it('calls onStateChange when confirming state change', () => {
    render(
      <StateToggle currentState="BOT_ACTIVE" phone="+5691234" onStateChange={mockOnStateChange} onCloseSession={mockOnCloseSession} />
    )
    fireEvent.click(screen.getByText(/Solo Humano/))
    fireEvent.click(screen.getByText(/Confirmar/))
    expect(mockOnStateChange).toHaveBeenCalledWith('+5691234', 'HUMAN_ONLY')
  })

  it('does not call onStateChange when clicking the active state', () => {
    render(
      <StateToggle currentState="BOT_ACTIVE" phone="+5691234" onStateChange={mockOnStateChange} onCloseSession={mockOnCloseSession} />
    )
    fireEvent.click(screen.getByText(/Bot Activo/))
    expect(mockOnStateChange).not.toHaveBeenCalled()
  })

  it('renders close session button', () => {
    render(
      <StateToggle currentState="BOT_ACTIVE" phone="+5691234" onStateChange={mockOnStateChange} onCloseSession={mockOnCloseSession} />
    )
    expect(screen.getByText(/Cerrar Sesion/)).toBeInTheDocument()
  })

  it('shows confirmation when clicking close session', () => {
    render(
      <StateToggle currentState="BOT_ACTIVE" phone="+5691234" onStateChange={mockOnStateChange} onCloseSession={mockOnCloseSession} />
    )
    fireEvent.click(screen.getByText(/Cerrar Sesion/))
    expect(screen.getByText(/Cerrar/)).toBeInTheDocument()
  })
})
