/**
 * Supabase email/password sign-in over the public Auth REST API (no extra dependency).
 *
 * Only the short-lived access token and the refresh token are kept, in sessionStorage
 * (scoped to this tab, cleared when it closes). The backend verifies every token; this
 * module never decides what a user may see.
 */

const SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''
const SUPABASE_ANON_KEY = (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) ?? ''
const STORAGE_KEY = 'gem.session'
/** Local test sign-in (development only): needs DEV_LOGIN_ENABLED=true on the backend. */
export const DEV_LOGIN = import.meta.env.DEV && import.meta.env.VITE_DEV_LOGIN !== 'false'

export interface Session {
  accessToken: string
  refreshToken: string
  expiresAt: number // epoch ms
  email: string | null
}

export const authConfigured = (): boolean => DEV_LOGIN || Boolean(SUPABASE_URL && SUPABASE_ANON_KEY)

function read(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

function write(session: Session | null): void {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* storage unavailable: session lives only in memory for this page */
  }
  current = session
}

let current: Session | null = read()

interface TokenResponse {
  access_token: string
  refresh_token: string
  expires_in: number
  user?: { email?: string | null }
}

async function tokenRequest(grant: 'password' | 'refresh_token', body: object): Promise<Session> {
  if (!authConfigured()) throw new Error('Sign-in is not configured (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY).')
  const res = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=${grant}`, {
    method: 'POST',
    headers: { apikey: SUPABASE_ANON_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(grant === 'password' ? 'Invalid email or password.' : 'Session expired.')
  const data = (await res.json()) as TokenResponse
  const session: Session = {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    expiresAt: Date.now() + data.expires_in * 1000,
    email: data.user?.email ?? current?.email ?? null,
  }
  write(session)
  return session
}

async function devSignIn(email: string): Promise<Session> {
  const res = await fetch('/api/dev/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) throw new Error('Local test sign-in failed. Is DEV_LOGIN_ENABLED=true set and the server running?')
  const data = (await res.json()) as { access_token: string; expires_in: number; email: string }
  const session: Session = {
    accessToken: data.access_token,
    refreshToken: '',
    expiresAt: Date.now() + data.expires_in * 1000,
    email: data.email,
  }
  write(session)
  return session
}

export const signIn = (email: string, password: string) =>
  DEV_LOGIN ? devSignIn(email) : tokenRequest('password', { email, password })

export function signOut(): void {
  write(null)
}

export function getSession(): Session | null {
  return current
}

/** A valid access token, refreshed shortly before expiry; null when signed out. */
export async function getAccessToken(): Promise<string | null> {
  if (!current) return null
  if (Date.now() < current.expiresAt - 60_000) return current.accessToken
  if (!current.refreshToken) {
    signOut() // local test sign-in has no refresh: sign in again
    return null
  }
  try {
    return (await tokenRequest('refresh_token', { refresh_token: current.refreshToken })).accessToken
  } catch {
    signOut()
    return null
  }
}
