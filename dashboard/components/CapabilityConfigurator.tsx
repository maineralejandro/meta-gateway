import React, { useState, useEffect, useCallback } from 'react'
import { authFetch } from '../lib/auth'
import type { CapabilityDetail, CapabilitySchema, AgentCapabilityState } from '../lib/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

interface Props {
  agentId: number
  onUpdate: () => void
}

const CAPABILITY_ICONS: Record<string, string> = {
  cart: '\uD83D\uDED2',
  appointment: '\uD83D\uDCC5',
  lead: '\uD83C\uDFAF',
  membership: '\uD83D\uDCB3',
}

export default function CapabilityConfigurator({ agentId, onUpdate }: Props) {
  const [available, setAvailable] = useState<CapabilityDetail[]>([])
  const [active, setActive] = useState<AgentCapabilityState[]>([])
  const [configs, setConfigs] = useState<Record<string, any>>({})
  const [toggles, setToggles] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [capsRes, activeRes] = await Promise.all([
        authFetch(`${API_URL}/api/capabilities`),
        authFetch(`${API_URL}/api/agents/${agentId}/capabilities`),
      ])
      if (!capsRes.ok || !activeRes.ok) throw new Error('Failed to load capabilities')
      const capsData: CapabilityDetail[] = await capsRes.json()
      const activeData: AgentCapabilityState[] = await activeRes.json()
      setAvailable(capsData)
      setActive(activeData)

      const newToggles: Record<string, boolean> = {}
      const newConfigs: Record<string, any> = {}
      for (const cap of capsData) {
        const existing = activeData.find(a => a.capability_name === cap.name)
        newToggles[cap.name] = existing ? existing.is_active : false
        try {
          newConfigs[cap.name] = existing && existing.config_json ? JSON.parse(existing.config_json) : {}
        } catch {
          newConfigs[cap.name] = {}
        }
        for (const field of cap.config_schema) {
          if (!(field.key in newConfigs[cap.name])) {
            newConfigs[cap.name][field.key] = field.default
          }
        }
      }
      setToggles(newToggles)
      setConfigs(newConfigs)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useEffect(() => { loadData() }, [loadData])

  const handleToggle = (name: string) => {
    setToggles(prev => ({ ...prev, [name]: !prev[name] }))
  }

  const handleConfigChange = (capName: string, key: string, value: any) => {
    setConfigs(prev => ({
      ...prev,
      [capName]: { ...prev[capName], [key]: value },
    }))
  }

  const handleArrayAdd = (capName: string, key: string) => {
    const current = configs[capName]?.[key] || []
    setConfigs(prev => ({
      ...prev,
      [capName]: { ...prev[capName], [key]: [...current, ''] },
    }))
  }

  const handleArrayRemove = (capName: string, key: string, index: number) => {
    const current = configs[capName]?.[key] || []
    setConfigs(prev => ({
      ...prev,
      [capName]: { ...prev[capName], [key]: current.filter((_: any, i: number) => i !== index) },
    }))
  }

  const handleArrayItemChange = (capName: string, key: string, index: number, value: string) => {
    const current = [...(configs[capName]?.[key] || [])]
    current[index] = value
    setConfigs(prev => ({
      ...prev,
      [capName]: { ...prev[capName], [key]: current },
    }))
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const capabilities = available.map(cap => ({
        capability_name: cap.name,
        is_active: toggles[cap.name] ? 1 : 0,
        config_json: JSON.stringify(configs[cap.name] || {}),
      }))
      const res = await authFetch(`${API_URL}/api/agents/${agentId}/capabilities`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capabilities }),
      })
      if (!res.ok) throw new Error('Failed to save capabilities')

      await authFetch(`${API_URL}/api/agents/${agentId}/reload`, { method: 'POST' })
      setSuccessMsg('Capabilities guardadas y cache recargado')
      onUpdate()
      await loadData()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="p-6 text-gray-400">Cargando capabilities...</div>

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-semibold text-gray-200">Capabilities</h3>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-all"
        >
          {saving ? 'Guardando...' : 'Guardar Capabilities'}
        </button>
      </div>

      {error && (
        <div className="p-3 bg-red-900/20 border border-red-500/30 text-red-400 rounded-xl text-sm">{error}</div>
      )}
      {successMsg && (
        <div className="p-3 bg-emerald-900/20 border border-emerald-500/30 text-emerald-400 rounded-xl text-sm">{successMsg}</div>
      )}

      {available.map(cap => (
        <div key={cap.name} className={`rounded-xl border transition-all ${toggles[cap.name] ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-gray-700 bg-gray-800/30'}`}>
          <div className="flex items-center justify-between p-4">
            <div className="flex items-center gap-3">
              <span className="text-lg">{CAPABILITY_ICONS[cap.name] || '\u2699'}</span>
              <div>
                <span className="font-medium text-gray-200 capitalize">{cap.name}</span>
                <p className="text-xs text-gray-500">{cap.description}</p>
              </div>
            </div>
            <button
              onClick={() => handleToggle(cap.name)}
              className={`relative w-11 h-6 rounded-full transition-colors ${toggles[cap.name] ? 'bg-emerald-500' : 'bg-gray-600'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${toggles[cap.name] ? 'translate-x-5' : ''}`} />
            </button>
          </div>

          {toggles[cap.name] && cap.config_schema.length > 0 && (
            <div className="px-4 pb-4 space-y-3 border-t border-gray-700/50 pt-3">
              {cap.config_schema.map(field => (
                <ConfigFieldRenderer
                  key={`${cap.name}-${field.key}`}
                  schema={field}
                  value={configs[cap.name]?.[field.key]}
                  onChange={(value) => handleConfigChange(cap.name, field.key, value)}
                  onArrayAdd={() => handleArrayAdd(cap.name, field.key)}
                  onArrayRemove={(index) => handleArrayRemove(cap.name, field.key, index)}
                  onArrayItemChange={(index, value) => handleArrayItemChange(cap.name, field.key, index, value)}
                />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

interface FieldProps {
  schema: CapabilitySchema
  value: any
  onChange: (value: any) => void
  onArrayAdd: () => void
  onArrayRemove: (index: number) => void
  onArrayItemChange: (index: number, value: string) => void
}

function ConfigFieldRenderer({ schema, value, onChange, onArrayAdd, onArrayRemove, onArrayItemChange }: FieldProps) {
  if (schema.type === 'boolean') {
    return (
      <div className="flex items-center justify-between">
        <label className="text-sm text-gray-400">{schema.label}</label>
        <button
          onClick={() => onChange(!value)}
          className={`relative w-11 h-6 rounded-full transition-colors ${value ? 'bg-emerald-500' : 'bg-gray-600'}`}
        >
          <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${value ? 'translate-x-5' : ''}`} />
        </button>
      </div>
    )
  }

  if (schema.type === 'integer') {
    return (
      <div className="space-y-1">
        <label className="text-sm text-gray-400">{schema.label}</label>
        <input
          type="number"
          step="1"
          value={value ?? schema.default ?? 0}
          onChange={e => onChange(parseInt(e.target.value) || 0)}
          className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
        />
      </div>
    )
  }

  if (schema.type === 'string') {
    return (
      <div className="space-y-1">
        <label className="text-sm text-gray-400">{schema.label}</label>
        <input
          type="text"
          value={value ?? schema.default ?? ''}
          onChange={e => onChange(e.target.value)}
          className="w-full bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
        />
      </div>
    )
  }

  if (schema.type === 'array') {
    const items = Array.isArray(value) ? value : []
    const isObjectArray = items.length > 0 && typeof items[0] === 'object' && items[0] !== null

    if (isObjectArray) {
      return (
        <div className="space-y-1">
          <label className="text-sm text-gray-400">{schema.label}</label>
          <textarea
            value={JSON.stringify(value ?? schema.default ?? [], null, 2)}
            onChange={e => {
              try {
                const parsed = JSON.parse(e.target.value)
                onChange(parsed)
              } catch {}
            }}
            rows={4}
            className="w-full bg-gray-950/50 border border-gray-800 rounded-lg px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
          />
        </div>
      )
    }

    return (
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <label className="text-sm text-gray-400">{schema.label}</label>
          <button
            onClick={onArrayAdd}
            className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
          >
            + Agregar
          </button>
        </div>
        {items.map((item: any, index: number) => (
          <div key={index} className="flex gap-2">
            <input
              type="text"
              value={item}
              onChange={e => onArrayItemChange(index, e.target.value)}
              className="flex-1 bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
            />
            <button
              onClick={() => onArrayRemove(index)}
              className="px-2 text-gray-500 hover:text-red-400 transition-colors"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    )
  }

  if (schema.type === 'object') {
    return (
      <div className="space-y-1">
        <label className="text-sm text-gray-400">{schema.label}</label>
        <textarea
          value={typeof value === 'string' ? value : JSON.stringify(value ?? schema.default ?? {}, null, 2)}
          onChange={e => {
            try {
              const parsed = JSON.parse(e.target.value)
              onChange(parsed)
            } catch {
              onChange(e.target.value)
            }
          }}
          rows={8}
          className="w-full bg-gray-950/50 border border-gray-800 rounded-lg px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
        />
      </div>
    )
  }

  return null
}
