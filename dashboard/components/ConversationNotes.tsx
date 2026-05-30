import { useState, useEffect, useCallback } from 'react'
import { authFetch } from '../lib/auth'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

interface Note {
  id: number
  phone: string
  note: string
  author: string
  created_at: string
}

interface Props {
  phone: string
}

export default function ConversationNotes({ phone }: Props) {
  const [notes, setNotes] = useState<Note[]>([])
  const [newNote, setNewNote] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const loadNotes = useCallback(async () => {
    if (!phone) return
    try {
      const res = await authFetch(`${API_URL}/api/conversations/${phone}/notes`)
      if (res.ok) setNotes(await res.json())
    } catch {}
  }, [phone])

  useEffect(() => { loadNotes() }, [loadNotes])

  const addNote = async () => {
    if (!newNote.trim() || submitting) return
    setSubmitting(true)
    try {
      const res = await authFetch(`${API_URL}/api/conversations/${phone}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: newNote.trim() }),
      })
      if (res.ok) {
        const created = await res.json()
        setNotes(prev => [created, ...prev])
        setNewNote('')
      }
    } catch {} finally {
      setSubmitting(false)
    }
  }

  const deleteNote = async (noteId: number) => {
    try {
      const res = await authFetch(`${API_URL}/api/conversations/${phone}/notes/${noteId}`, { method: 'DELETE' })
      if (res.ok) setNotes(prev => prev.filter(n => n.id !== noteId))
    } catch {}
  }

  if (!phone) return null

  return (
    <div className="p-4 border-b border-gray-700">
      <h3 className="text-sm font-semibold text-gray-400 mb-2">NOTAS</h3>
      <div className="space-y-2 mb-3 max-h-60 overflow-y-auto">
        {notes.length === 0 && (
          <p className="text-xs text-gray-600">Sin notas</p>
        )}
        {notes.map(n => (
          <div key={n.id} className="bg-gray-800 rounded px-2 py-1.5 text-xs group">
            <div className="flex items-start justify-between gap-1">
              <p className="text-gray-300 whitespace-pre-wrap flex-1">{n.note}</p>
              <button
                onClick={() => deleteNote(n.id)}
                className="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
              >
                ✕
              </button>
            </div>
            <span className="text-gray-600 block mt-1">
              {n.author} · {new Date(n.created_at).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
        ))}
      </div>
      <div className="flex gap-1">
        <input
          value={newNote}
          onChange={e => setNewNote(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && addNote()}
          placeholder="Agregar nota..."
          className="flex-1 bg-gray-800 text-white rounded px-2 py-1 text-xs border border-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <button
          onClick={addNote}
          disabled={!newNote.trim() || submitting}
          className="px-2 py-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-30 text-white text-xs rounded"
        >
          +
        </button>
      </div>
    </div>
  )
}
