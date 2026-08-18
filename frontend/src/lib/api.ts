import type { Complaint, PolicyDocument } from './types'

export const API_BASE_URL = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/$/, '')

export interface DurableAppState {
  cases: Complaint[]
  policies: PolicyDocument[]
}

export interface AppStateEnvelope {
  state: DurableAppState | null
  revision: number
  updated_at: string | null
}

function errorMessage(status: number, body: unknown) {
  if (
    typeof body === 'object' &&
    body !== null &&
    'detail' in body &&
    typeof body.detail === 'string'
  ) {
    return body.detail
  }
  return `Backend request failed with HTTP ${status}.`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(8_000),
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(errorMessage(response.status, body))
  return body as T
}

export function loadAppState(signal?: AbortSignal) {
  return request<AppStateEnvelope>('/app/state', { signal })
}

export function saveAppState(state: DurableAppState) {
  return request<AppStateEnvelope>('/app/state', {
    method: 'PUT',
    body: JSON.stringify(state),
  })
}
