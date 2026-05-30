import { useState, useEffect, useRef, useCallback } from 'react'

interface WSMessage {
  type: string
  phone?: string
  message?: string
  direction?: string
  source?: string
  state?: string
  reason?: string
  sentiment?: any
  response?: string
  old_state?: string
  error?: string
}

type WSHandler = (msg: WSMessage) => void

export type ConnectionState = 'connected' | 'disconnected' | 'reconnecting'

const MIN_DELAY = 3000
const MAX_DELAY = 30000
const BACKOFF_FACTOR = 2
const PING_INTERVAL = 30000

export function useWebSocket(url: string, handlers: Record<string, WSHandler>, token?: string) {
  const wsRef = useRef<WebSocket | null>(null)
  const handlersRef = useRef(handlers)
  const retryDelayRef = useRef(MIN_DELAY)
  const retryTimerRef = useRef<NodeJS.Timeout | null>(null)
  const pingTimerRef = useRef<NodeJS.Timeout | null>(null)
  const mountedRef = useRef(true)
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected')
  handlersRef.current = handlers

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[WS] Connected')
      setConnectionState('connected')
      retryDelayRef.current = MIN_DELAY
      if (token) {
        ws.send(JSON.stringify({ type: 'auth', token }))
      }
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setConnectionState('reconnecting')
      const delay = retryDelayRef.current
      console.log(`[WS] Disconnected, reconnecting in ${delay}ms...`)
      retryDelayRef.current = Math.min(delay * BACKOFF_FACTOR, MAX_DELAY)
      retryTimerRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      console.error('[WS] Error')
      setConnectionState('disconnected')
    }

    ws.onmessage = (event) => {
      try {
        const data: WSMessage = JSON.parse(event.data)
        if (data.type === 'pong') return
        if (data.type === 'auth_ok') return
        const handler = handlersRef.current[data.type]
        if (handler) handler(data)
      } catch (e) {
        console.error('[WS] Parse error', e)
      }
    }
  }, [url, token])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
      if (pingTimerRef.current) clearInterval(pingTimerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [connect])

  useEffect(() => {
    pingTimerRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }))
      }
    }, PING_INTERVAL)
    return () => {
      if (pingTimerRef.current) clearInterval(pingTimerRef.current)
    }
  }, [])

  return { wsRef, connectionState }
}
