import type { NextApiRequest, NextApiResponse } from 'next'
import crypto from 'crypto'

const AUTH_SECRET = process.env.DASHBOARD_AUTH_SECRET || ''
const DASHBOARD_TOKEN = process.env.DASHBOARD_TOKEN || ''
const COOKIE_NAME = 'hermes_session'

function sign(value: string): string {
  return crypto.createHmac('sha256', AUTH_SECRET).update(value).digest('hex')
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  if (!AUTH_SECRET) {
    return res.status(500).json({ error: 'Server misconfiguration' })
  }

  const cookie = req.cookies[COOKIE_NAME]
  if (!cookie) {
    return res.status(401).json({ authenticated: false })
  }

  const [token, signature] = cookie.split(':')
  if (!token || !signature || token !== DASHBOARD_TOKEN) {
    return res.status(401).json({ authenticated: false })
  }

  try {
    const expected = sign(DASHBOARD_TOKEN)
    if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) {
      return res.status(401).json({ authenticated: false })
    }
  } catch {
    return res.status(401).json({ authenticated: false })
  }

  return res.status(200).json({ authenticated: true })
}
