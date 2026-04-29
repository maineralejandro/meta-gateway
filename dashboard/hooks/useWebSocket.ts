import { useEffect, useRef, useCallback } from 'react'

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

const MIN_DELAY = 3000
const MAX_DELAY = 30000
const BACKOFF_FACTOR = 2

export function useWebSocket(url: string, handlers: Record<string, WSHandler>) {
  const wsRef = useRef<WebSocket | null>(null)
  const handlersRef = useRef(handlers)
  const retryDelayRef = useRef(MIN_DELAY)
  const retryTimerRef = useRef<NodeJS.Timeout | null>(null)
  handlersRef.current = handlers

  const connect = useCallback(() => {
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[WS] Connected')
      retryDelayRef.current = MIN_DELAY
    }

    ws.onclose = () => {
      const delay = retryDelayRef.current
      console.log(`[WS] Disconnected, reconnecting in ${delay}ms...`)
      retryDelayRef.current = Math.min(delay * BACKOFF_FACTOR, MAX_DELAY)
      retryTimerRef.current = setTimeout(connect, delay)
    }

    ws.onerror = (e) => console.error('[WS] Error', e)

    ws.onmessage = (event) => {
      try {
        const data: WSMessage = JSON.parse(event.data)
        const handler = handlersRef.current[data.type]
        if (handler) handler(data)
      } catch (e) {
        console.error('[WS] Parse error', e)
      }
    }
  }, [url])

  useEffect(() => {
    connect()
    return () => {
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return wsRef
}
