import { useSyncExternalStore } from 'react'
import { ApiError, login, registerAccount } from './api'

const SESSION_KEY = 'smarttracker.auth'

export interface AuthSession {
  accessToken: string
  tokenType: string
  role: string
  subject: string
}

interface AuthState {
  session: AuthSession | null
  hydrated: boolean
}

let state: AuthState = { session: null, hydrated: false }
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

function set(next: AuthState) {
  state = next
  emit()
}

function decodeClaims(accessToken: string) {
  try {
    const payload = accessToken.split('.')[1]
    if (!payload) return null
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const claims = JSON.parse(atob(padded)) as Record<string, unknown>
    return {
      role: typeof claims.role === 'string' ? claims.role : 'unknown',
      subject: typeof claims.sub === 'string' ? claims.sub : '',
    }
  } catch {
    return null
  }
}

function sessionFromToken(accessToken: string, tokenType: string) {
  const claims = decodeClaims(accessToken)
  if (!claims) return null
  return { accessToken, tokenType, ...claims } satisfies AuthSession
}

function persist(session: AuthSession | null) {
  if (typeof window === 'undefined') return
  if (session) {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
  } else {
    window.sessionStorage.removeItem(SESSION_KEY)
  }
}

export function hydrateAuth() {
  if (state.hydrated || typeof window === 'undefined') return
  let session: AuthSession | null = null
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY)
    if (raw) {
      const saved = JSON.parse(raw) as Partial<AuthSession>
      if (saved.accessToken && saved.tokenType) {
        session = sessionFromToken(saved.accessToken, saved.tokenType)
      }
    }
  } catch {
    session = null
  }
  set({ session, hydrated: true })
}

export async function signIn(email: string, password: string) {
  const token = await login({ email, password })
  const session = sessionFromToken(token.access_token, token.token_type)
  if (!session)
    throw new Error('The backend returned an unreadable access token.')
  persist(session)
  set({ session, hydrated: true })
  return session
}

export async function registerAndSignIn(input: {
  name: string
  email: string
  password: string
}) {
  await registerAccount({ ...input, role: 'citizen', department: null })
  return signIn(input.email, input.password)
}

export function signOut() {
  persist(null)
  set({ session: null, hydrated: true })
}

/**
 * 401 is the backend's answer to an expired or invalid JWT, so the stored token
 * is dead and the screen should offer a re-login. 403 is deliberately excluded:
 * it means the token is fine but the account lacks access to that record, and
 * signing out would be the wrong remedy.
 */
export function isExpiredSession(error: unknown) {
  return error instanceof ApiError && error.status === 401
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot() {
  return state
}

export function useAuth() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}
