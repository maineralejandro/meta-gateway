import { X } from 'lucide-react'

interface Notification {
  id: string
  phone: string
  reason: string
  sentiment?: { score: number; sentiment: string; confidence: number }
  timestamp: number
}

interface Props {
  notifications: Notification[]
  onDismiss: (id: string) => void
  onClick: (phone: string) => void
}

export default function NotificationBanner({ notifications, onDismiss, onClick }: Props) {
  if (notifications.length === 0) return null

  return (
    <div className="absolute top-0 right-0 left-0 z-50 space-y-2 p-3">
      {notifications.map(n => (
        <div
          key={n.id}
          className="animate-slide-in bg-yellow-900/90 border border-yellow-600 rounded-lg p-3 flex items-center justify-between cursor-pointer hover:bg-yellow-800/90 transition-colors"
          onClick={() => onClick(n.phone)}
        >
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="text-yellow-300 font-bold text-sm">⚠️ ESCALADA</span>
              <span className="font-mono text-sm text-yellow-200">{n.phone}</span>
            </div>
            <p className="text-xs text-yellow-300 mt-1">
              {n.reason}
              {n.sentiment && (
                <span className="ml-2 opacity-70">
                  sentimiento: {n.sentiment.score.toFixed(2)} | confianza: {n.sentiment.confidence.toFixed(2)}
                </span>
              )}
            </p>
          </div>
          <button
            onClick={e => { e.stopPropagation(); onDismiss(n.id) }}
            className="p-1 hover:bg-yellow-700 rounded ml-2"
          >
            <X size={16} className="text-yellow-300" />
          </button>
        </div>
      ))}
    </div>
  )
}
