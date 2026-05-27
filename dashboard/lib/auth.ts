export function authHeaders(): Record<string, string> {
  return {}
}

export function wsUrlWithToken(baseUrl: string): string {
  return baseUrl
}

export async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(url, { ...init, credentials: 'include' })
  if (res.status === 401 && typeof window !== 'undefined') {
    window.location.href = '/login'
  }
  return res
}

export async function checkAuth(): Promise<boolean> {
  try {
    const res = await fetch('/api/auth/check', { credentials: 'include' })
    return res.ok
  } catch {
    return false
  }
}

export async function logout(): Promise<void> {
  document.cookie = 'hermes_session=; Path=/; Max-Age=0'
  window.location.href = '/login'
}
