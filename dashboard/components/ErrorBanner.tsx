import { X, AlertTriangle } from 'lucide-react'

interface ErrorNotification {
  id: string
  message: string
  timestamp: number
}

interface Props {
  errors: ErrorNotification[]
  onDismiss: (id: string) => void
}

export default function ErrorBanner({ errors, onDismiss }: Props) {
  if (errors.length === 0) return null

  return (
    <div className="absolute top-0 right-0 left-0 z-40 space-y-2 p-3">
      {errors.map(e => (
        <div
          key={e.id}
          className="animate-slide-in bg-red-900/90 border border-red-600 rounded-lg p-3 flex items-center justify-between"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-red-300" />
            <span className="text-red-200 text-sm">{e.message}</span>
          </div>
          <button
            onClick={() => onDismiss(e.id)}
            className="p-1 hover:bg-red-700 rounded ml-2"
          >
            <X size={16} className="text-red-300" />
          </button>
        </div>
      ))}
    </div>
  )
}
