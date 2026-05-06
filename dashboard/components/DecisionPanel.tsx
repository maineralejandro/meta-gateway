import type { Conversation, AgentDecision } from '../lib/types'

interface DecisionPanelProps {
  conversation: Conversation
  decisions: AgentDecision[]
  inspectedMessageId: number | null
  onInspect: (messageId: number | null) => void
}

export default function DecisionPanel({ conversation, decisions, inspectedMessageId, onInspect }: DecisionPanelProps) {
  const inspectedDecision = inspectedMessageId
    ? decisions.find(d => d.message_id === inspectedMessageId)
    : null

  if (inspectedMessageId && inspectedDecision) {
    return (
      <div className="p-4 text-xs text-gray-400 space-y-4">
        <div className="flex items-center gap-2">
          <button
            onClick={() => onInspect(null)}
            className="text-blue-400 hover:text-blue-300 text-xs"
          >
            ← Volver
          </button>
          <h3 className="font-semibold text-gray-500 uppercase tracking-wider text-[10px]">Detalle decision</h3>
        </div>
        <div className="bg-gray-800/50 p-3 rounded-xl border border-gray-700 space-y-2">
          <div className="flex justify-between">
            <span>Agente</span>
            <span className="text-white font-medium">{inspectedDecision.agent_name || '—'}</span>
          </div>
          <div className="flex justify-between">
            <span>Sentimiento</span>
            <span className={
              inspectedDecision.sentiment === 'negative' ? 'text-red-400' :
              inspectedDecision.sentiment === 'positive' ? 'text-emerald-400' :
              'text-yellow-400'
            }>{inspectedDecision.sentiment}</span>
          </div>
          <div className="flex justify-between">
            <span>Score sentimiento</span>
            <span className={inspectedDecision.sentiment_score < 0.3 ? 'text-red-400' : inspectedDecision.sentiment_score < 0.6 ? 'text-yellow-400' : 'text-emerald-400'}>
              {inspectedDecision.sentiment_score.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between">
            <span>Confianza</span>
            <span className={inspectedDecision.confidence < 0.7 ? 'text-red-400' : 'text-emerald-400'}>
              {inspectedDecision.confidence.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between">
            <span>LLM escalo</span>
            <span className={inspectedDecision.llm_escalate ? 'text-red-400' : 'text-gray-500'}>
              {inspectedDecision.llm_escalate ? 'Si' : 'No'}
            </span>
          </div>
          {inspectedDecision.escalate_reason && (
            <div className="pt-1 border-t border-gray-700">
              <span className="block text-gray-500 mb-1">Razon escalado</span>
              <span className="text-red-300">{inspectedDecision.escalate_reason}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span>Historial msgs</span>
            <span className="text-white">{inspectedDecision.history_count}</span>
          </div>
          <div className="flex justify-between">
            <span>Msg ID</span>
            <span className="text-gray-300 font-mono">{inspectedDecision.message_id}</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-4 text-xs text-gray-400 space-y-4">
      <h3 className="font-semibold text-gray-500 uppercase tracking-wider">Decisiones del agente</h3>
      {decisions.length === 0 ? (
        <p className="text-gray-600 text-[11px]">Sin decisiones registradas</p>
      ) : (
        <div className="space-y-2">
          {decisions.slice(0, 10).map(d => (
            <button
              key={d.id}
              onClick={() => d.message_id && onInspect(d.message_id)}
              className="w-full text-left bg-gray-800/50 p-2.5 rounded-lg border border-gray-700 hover:border-blue-600/50 transition-all"
            >
              <div className="flex justify-between items-center mb-1">
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                  d.sentiment === 'negative' ? 'bg-red-900/40 text-red-400' :
                  d.sentiment === 'positive' ? 'bg-emerald-900/40 text-emerald-400' :
                  'bg-yellow-900/40 text-yellow-400'
                }`}>{d.sentiment}</span>
                <span className="text-gray-500 text-[10px]">
                  {d.created_at ? new Date(d.created_at).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' }) : ''}
                </span>
              </div>
              <div className="flex justify-between text-[10px]">
                <span className="text-gray-500">conf: <span className={d.confidence < 0.7 ? 'text-red-400' : 'text-emerald-400'}>{d.confidence.toFixed(2)}</span></span>
                <span className="text-gray-500">score: <span className={d.sentiment_score < 0.3 ? 'text-red-400' : 'text-emerald-400'}>{d.sentiment_score.toFixed(2)}</span></span>
              </div>
              {d.escalate_reason && (
                <div className="text-[10px] text-red-400 mt-1 truncate">{d.escalate_reason}</div>
              )}
            </button>
          ))}
        </div>
      )}
      <div className="border-t border-gray-700 pt-3 space-y-2">
        <h3 className="font-semibold text-gray-500 uppercase tracking-wider text-[10px]">Resumen conversacion</h3>
        <div className="bg-gray-800/50 p-3 rounded-xl border border-gray-700 space-y-2">
          <div className="flex justify-between">
            <span>Sentimiento</span>
            <span className={conversation.sentiment_score != null
              ? (conversation.sentiment_score < 0.3 ? 'text-red-400' :
                 conversation.sentiment_score < 0.6 ? 'text-yellow-400' : 'text-emerald-400')
              : 'text-gray-500'
            }>
              {conversation.sentiment_score?.toFixed(2) ?? '—'}
            </span>
          </div>
          <div className="flex justify-between">
            <span>Confianza bot</span>
            <span className={conversation.confidence != null
              ? (conversation.confidence < 0.7 ? 'text-red-400' : 'text-emerald-400')
              : 'text-gray-500'
            }>
              {conversation.confidence?.toFixed(2) ?? '—'}
            </span>
          </div>
        </div>
        <div className="flex justify-between px-1">
          <span>Mensajes sin leer</span>
          <span className="bg-emerald-600 text-white px-1.5 py-0.5 rounded text-[10px] font-bold">
            {conversation.unread_count}
          </span>
        </div>
      </div>
    </div>
  )
}
