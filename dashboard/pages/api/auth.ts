import type { NextApiRequest, NextApiResponse } from 'next'
import crypto from 'crypto'

const AUTH_SECRET = process.env.DASHBOARD_AUTH_SECRET || ''
const DASHBOARD_TOKEN = process.env.DASHBOARD_TOKEN || ''
const COOKIE_NAME = 'hermes_session'
const COOKIE_MAX_AGE = 86400

function sign(value: string): string {
  return crypto.createHmac('sha256', AUTH_SECRET).update(value).digest('hex')
}

function verify(token: string, signature: string): boolean {
  const expected = sign(token)
  return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  if (!AUTH_SECRET) {
    console.error('DASHBOARD_AUTH_SECRET not configured')
    return res.status(500).json({ error: 'Server misconfiguration' })
  }

  const { token } = req.body || {}

  if (!token || token !== DASHBOARD_TOKEN) {
    return res.status(401).json({ error: 'Invalid token' })
  }

  const signature = sign(DASHBOARD_TOKEN)
  const cookieValue = `${DASHBOARD_TOKEN}:${signature}`

  res.setHeader('Set-Cookie', [
    `${COOKIE_NAME}=${cookieValue}`,
    `Path=/`,
    `HttpOnly`,
    `SameSite=Strict`,
    `Max-Age=${COOKIE_MAX_AGE}`,
  ].join('; '))

  return res.status(200).json({ ok: true })
}
