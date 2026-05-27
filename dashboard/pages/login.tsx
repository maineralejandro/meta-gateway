import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'

export default function Login() {
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const router = useRouter()

  useEffect(() => {
    fetch('/api/auth/check', { method: 'GET' })
      .then(r => { if (r.ok) router.replace('/') })
      .catch(() => {})
  }, [router])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      const res = await fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      })

      if (res.ok) {
        router.replace('/')
      } else {
        const data = await res.json()
        setError(data.error || 'Authentication failed')
      }
    } catch {
      setError('Connection error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center">
      <div className="bg-gray-800 p-8 rounded-xl shadow-xl w-full max-w-sm">
        <h1 className="text-2xl font-bold text-white mb-6 text-center">Hermes Dashboard</h1>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-gray-300 text-sm mb-2">Access Token</label>
            <input
              type="password"
              value={token}
              onChange={e => setToken(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
              placeholder="Enter dashboard token"
              autoFocus
            />
          </div>
          {error && (
            <p className="text-red-400 text-sm mb-4">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading || !token}
            className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white rounded font-medium transition"
          >
            {loading ? 'Connecting...' : 'Login'}
          </button>
        </form>
      </div>
    </div>
  )
}
