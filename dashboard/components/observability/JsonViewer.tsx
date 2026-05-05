import { useMemo } from 'react'
import { JsonView, allExpanded, collapseAllNested, darkStyles } from 'react-json-view-lite'
import 'react-json-view-lite/dist/index.css'

interface Props {
  data: any
  collapsed?: boolean
  maxSize?: number
}

const HERMES_THEME = {
  ...darkStyles,
  container: 'json-viewer-container',
  punctuation: 'text-gray-500',
  label: 'text-blue-400',
  clickableLabel: 'text-blue-400 cursor-pointer hover:text-blue-300',
  nullValue: 'text-gray-500 italic',
  undefinedValue: 'text-gray-500 italic',
  numberValue: 'text-cyan-300',
  stringValue: 'text-emerald-300',
  booleanValue: 'text-yellow-300',
  otherValue: 'text-gray-300',
  expandIcon: 'text-gray-500',
  collapseIcon: 'text-gray-500',
  collapsedContent: 'text-gray-600',
  childFieldsContainer: 'ml-4 border-l border-gray-800',
}

export default function JsonViewer({ data, collapsed = false, maxSize = 10240 }: Props) {
  const size = useMemo(() => {
    try {
      return JSON.stringify(data).length
    } catch {
      return 0
    }
  }, [data])

  const parsed = useMemo(() => {
    if (typeof data === 'string') {
      try {
        return JSON.parse(data)
      } catch {
        return data
      }
    }
    return data
  }, [data])

  if (size > maxSize) {
    return (
      <div className="text-xs text-yellow-400 bg-yellow-900/20 border border-yellow-700/30 rounded-lg p-3">
        JSON demasiado grande ({(size / 1024).toFixed(1)}KB). Mostrando resumen truncado.
        <JsonView
          data={typeof parsed === 'object' && parsed !== null ? truncateObject(parsed, maxSize) : { value: String(parsed).slice(0, 500) }}
          style={HERMES_THEME}
          shouldExpandNode={collapseAllNested}
        />
      </div>
    )
  }

  if (typeof parsed === 'string') {
    return (
      <pre className="text-emerald-300 text-xs whitespace-pre-wrap break-all bg-gray-950/50 p-3 rounded-lg border border-gray-800 overflow-x-auto custom-scrollbar">
        {parsed}
      </pre>
    )
  }

  return (
    <div className="json-viewer-wrapper">
      <JsonView
        data={parsed}
        style={HERMES_THEME}
        shouldExpandNode={collapsed ? collapseAllNested : allExpanded}
      />
    </div>
  )
}

function truncateObject(obj: any, maxSize: number): any {
  if (Array.isArray(obj)) {
    if (obj.length > 5) {
      return [...obj.slice(0, 5), `... y ${obj.length - 5} mas`]
    }
    return obj.map(v => truncateObject(v, maxSize))
  }
  if (obj !== null && typeof obj === 'object') {
    const result: any = {}
    let est = 0
    for (const [k, v] of Object.entries(obj)) {
      if (est > maxSize * 0.8) {
        result['...'] = 'truncado'
        break
      }
      const val = typeof v === 'string' && v.length > 200 ? v.slice(0, 200) + '...' : v
      result[k] = truncateObject(val, maxSize)
      est += JSON.stringify(val).length
    }
    return result
  }
  if (typeof obj === 'string' && obj.length > 200) {
    return obj.slice(0, 200) + '...'
  }
  return obj
}
