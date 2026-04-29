const DASHBOARD_TOKEN = process.env.NEXT_PUBLIC_DASHBOARD_TOKEN || ''

export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  if (DASHBOARD_TOKEN) {
    headers['Authorization'] = `Bearer ${DASHBOARD_TOKEN}`
  }
  return headers
}

export function wsUrlWithToken(baseUrl: string): string {
  if (!DASHBOARD_TOKEN) return baseUrl
  const sep = baseUrl.includes('?') ? '&' : '?'
  return `${baseUrl}${sep}token=${DASHBOARD_TOKEN}`
}

export async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const headers = {
    ...init?.headers,
    ...authHeaders(),
  }
  return fetch(url, { ...init, headers })
}
