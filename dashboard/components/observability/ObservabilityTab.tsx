import { useState, useEffect, useCallback, useRef } from 'react'
import { authFetch } from '../../lib/auth'
import HealthBar from './HealthBar'
import MetricCards from './MetricCards'
import LastErrorBanner from './LastErrorBanner'
import TraceList from './TraceList'
import TraceDetail, { ResizablePanel } from './TraceDetail'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'
const POLL_INTERVAL = 15000

interface HealthDetail {
  llm: { available: boolean; model: string; base_url: string; key_prefix: string }
  trace_stats_24h: TraceStats
  last_error: LastError | null
}

interface TraceStats {
  total: number
  llm: number
  fallback: number
  error: number
  avg_llm_latency: number
  avg_latency: number
}

interface LastError {
  id: number
  phone: string
  correlation_id: string
  error_type: string
  error_message: string
  created_at: string
}

interface TraceSummary {
  id: number
  phone: string
  correlation_id: string
  response_source: 'llm' | 'fallback' | 'error'
  error_type: string | null
  token_usage_prompt: number
  token_usage_completion: number
  latency_ms: number
  created_at: string
}

interface TraceFull {
  id: number
  phone: string
  correlation_id: string
  agent_id: number | null
  request_messages: string
  response_raw: string | null
  response_source: 'llm' | 'fallback' | 'error'
  error_type: string | null
  error_message: string | null
  token_usage_prompt: number
  token_usage_completion: number
  latency_ms: number
  created_at: string
}

export default function ObservabilityTab() {
  const [health, setHealth] = useState<HealthDetail | null>(null)
  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [selectedTrace, setSelectedTrace] = useState<TraceFull | null>(null)
  const [selectedTraceId, setSelectedTraceId] = useState<number | null>(null)
  const [filter, setFilter] = useState<'all' | 'llm' | 'fallback' | 'error'>('all')
  const [sortKey, setSortKey] = useState<'created_at' | 'latency_ms'>('created_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [loading, setLoading] = useState(false)
  const [detailWidth, setDetailWidth] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('hermes_detail_width')
      return saved ? parseInt(saved, 10) : 500
    }
    return 500
  })
  const pollRef = useRef<NodeJS.Timeout | null>(null)
  const visibleRef = useRef(true)

  const fetchHealth = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/debug/health-detail`)
      if (res.ok) {
        const data = await res.json()
        setHealth(data)
      }
    } catch {}
  }, [])

  const fetchTraces = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: '50' })
      if (filter !== 'all') params.set('source', filter)
      const res = await authFetch(`${API_URL}/api/debug/traces/recent?${params}`)
      if (res.ok) {
        const data = await res.json()
        setTraces(data)
      }
    } catch {} finally {
      setLoading(false)
      setLastRefresh(new Date())
    }
  }, [filter])

  const fetchTraceDetail = useCallback(async (id: number) => {
    try {
      const res = await authFetch(`${API_URL}/api/debug/trace-by-id/${id}`)
      if (res.ok) {
        const data = await res.json()
        setSelectedTrace(data)
      }
    } catch {}
  }, [])

  const refreshAll = useCallback(async () => {
    setLoading(true)
    await Promise.all([fetchHealth(), fetchTraces()])
    setLoading(false)
  }, [fetchHealth, fetchTraces])

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(() => {
      if (!document.hidden && visibleRef.current) {
        fetchHealth()
        fetchTraces()
      }
    }, POLL_INTERVAL)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [fetchHealth, fetchTraces])

  useEffect(() => {
    visibleRef.current = true
    return () => { visibleRef.current = false }
  }, [])

  useEffect(() => {
    localStorage.setItem('hermes_detail_width', String(detailWidth))
  }, [detailWidth])

  const handleSelectTrace = useCallback((id: number) => {
    setSelectedTraceId(id)
    fetchTraceDetail(id)
  }, [fetchTraceDetail])

  const handleSort = useCallback((key: 'created_at' | 'latency_ms') => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }, [sortKey])

  const sortedTraces = [...traces].sort((a, b) => {
    const mul = sortDir === 'asc' ? 1 : -1
    if (sortKey === 'latency_ms') return (a.latency_ms - b.latency_ms) * mul
    return (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) * mul
  })

  return (
    <div className="flex flex-col h-full bg-gray-950">
      <HealthBar
        health={health}
        lastRefresh={lastRefresh}
        onRefresh={refreshAll}
        loading={loading}
      />
      <MetricCards stats={health?.trace_stats_24h || null} />
      <LastErrorBanner error={health?.last_error || null} />
      <div className="flex-1 flex min-h-0 border-t border-gray-800">
        <div className="flex-1 min-w-0">
          <TraceList
            traces={sortedTraces}
            selectedTraceId={selectedTraceId}
            onSelect={handleSelectTrace}
            loading={loading}
            filter={filter}
            onFilterChange={setFilter}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={handleSort}
          />
        </div>
        {selectedTraceId && (
          <ResizablePanel
            initialWidth={detailWidth}
            minWidth={280}
            maxWidth={1200}
            onWidthChange={setDetailWidth}
          >
            <TraceDetail trace={selectedTrace} width={detailWidth} />
          </ResizablePanel>
        )}
      </div>
    </div>
  )
}
