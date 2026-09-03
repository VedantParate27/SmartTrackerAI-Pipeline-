import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { API_BASE_URL, checkHealth } from '#/lib/api'

export type Tone = 'neutral' | 'info' | 'warn' | 'ok' | 'danger'

function backendStatusTone(status: string): Tone {
  const value = status.toLowerCase()
  if (value === 'resolved') return 'ok'
  if (value === 'rejected') return 'danger'
  if (value === 'escalated') return 'warn'
  if (value === 'in_progress') return 'info'
  return 'neutral'
}

export function BackendStatusPill({ status }: { status: string }) {
  return (
    <span className="pill" data-tone={backendStatusTone(status)}>
      {status.replaceAll('_', ' ')}
    </span>
  )
}

export function BackendPriorityPill({ priority }: { priority: string }) {
  const tone: Tone = ['high', 'urgent'].includes(priority.toLowerCase())
    ? 'warn'
    : priority.toLowerCase() === 'medium'
      ? 'info'
      : 'neutral'
  return (
    <span className="pill" data-tone={tone}>
      {priority} priority
    </span>
  )
}

const CALLOUT_ICON: Record<Tone, string> = {
  neutral: 'i',
  info: 'i',
  warn: '!',
  danger: '!',
  ok: '✓',
}

export function Callout({
  tone = 'info',
  title,
  children,
}: {
  tone?: Tone
  title?: string
  children: ReactNode
}) {
  return (
    <div
      className="callout"
      data-tone={tone}
      role={tone === 'danger' ? 'alert' : undefined}
    >
      <span className="callout-icon" aria-hidden="true">
        {CALLOUT_ICON[tone]}
      </span>
      <div className="min-w-0">
        {title ? <strong className="block">{title}</strong> : null}
        <div className={title ? 'mt-0.5' : undefined}>{children}</div>
      </div>
    </div>
  )
}

export function Field({
  label,
  htmlFor,
  required,
  hint,
  error,
  children,
}: {
  label: string
  htmlFor: string
  required?: boolean
  hint?: string
  error?: string
  children: ReactNode
}) {
  return (
    <div className="field">
      <label className="label" htmlFor={htmlFor}>
        {label}
        {required ? (
          <span className="req" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {children}
      {hint && !error ? (
        <p className="hint" id={`${htmlFor}-hint`}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="field-error" id={`${htmlFor}-error`}>
          <span aria-hidden="true">!</span>
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  )
}

export function SectionCard({
  title,
  meta,
  children,
  bodyClassName = 'card-pad',
}: {
  title: string
  meta?: ReactNode
  children: ReactNode
  bodyClassName?: string
}) {
  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">{title}</h2>
        {meta ? <div className="text-xs muted">{meta}</div> : null}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="px-1 py-8 text-center text-sm muted">{children}</p>
}

/** Inline busy indicator. Purely decorative — the label beside it does the talking. */
export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

/** Placeholder bar used while a request is still in flight. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <span className={`skeleton ${className}`} aria-hidden="true" />
}

/** A full-width busy panel for a screen that has nothing to show yet. */
export function LoadingState({ label }: { label: string }) {
  return (
    <div className="load-panel" role="status">
      <Spinner />
      <span>{label}</span>
    </div>
  )
}

/**
 * The single failure surface for every request. `onRetry` re-issues the call;
 * `onReauth` appears for 401/403 so an expired token can be cleared without
 * hunting for the sign-out button.
 */
export function ErrorState({
  title,
  message,
  onRetry,
  onReauth,
}: {
  title: string
  message: string
  onRetry?: () => void
  onReauth?: () => void
}) {
  return (
    <Callout tone="danger" title={title}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>{message}</span>
        <span className="flex shrink-0 gap-1.5">
          {onReauth ? (
            <button type="button" className="btn btn-sm" onClick={onReauth}>
              Sign in again
            </button>
          ) : null}
          {onRetry ? (
            <button type="button" className="btn btn-sm" onClick={onRetry}>
              Retry
            </button>
          ) : null}
        </span>
      </div>
    </Callout>
  )
}

/** Live reachability of the FastAPI instance the app is pointed at. */
export function BackendStatus() {
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>(
    'checking',
  )
  const [message, setMessage] = useState('Checking the FastAPI backend…')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setHealth('checking')
    setMessage('Checking the FastAPI backend…')
    checkHealth(controller.signal)
      .then(() => {
        if (controller.signal.aborted) return
        setHealth('online')
        setMessage('FastAPI is reachable. All data on screen comes from it.')
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setHealth('offline')
        setMessage(
          error instanceof Error
            ? error.message
            : 'The backend is unavailable.',
        )
      })
    return () => controller.abort()
  }, [reload])

  const tone =
    health === 'online' ? 'ok' : health === 'offline' ? 'danger' : 'info'
  const title =
    health === 'online'
      ? 'Backend connected'
      : health === 'offline'
        ? 'Backend unavailable'
        : 'Connecting to backend'

  return (
    <Callout tone={tone} title={title}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          {message}{' '}
          <span className="subtle">
            API: <span className="mono">{API_BASE_URL}</span>
          </span>
        </span>
        {health === 'offline' ? (
          <button
            type="button"
            className="btn btn-sm shrink-0"
            onClick={() => setReload((n) => n + 1)}
          >
            Retry
          </button>
        ) : null}
      </div>
    </Callout>
  )
}
