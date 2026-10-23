import { useEffect, useState, type ReactNode } from 'react'
import { STATUS_TONE } from '#/lib/taxonomy'
import type { Tone } from '#/lib/taxonomy'
import { percent } from '#/lib/format'
import type { CaseStatus, Priority } from '#/lib/types'
import { checkHealth } from '#/lib/api'

export function StatusPill({ status }: { status: CaseStatus }) {
  return (
    <span className="pill" data-tone={STATUS_TONE[status]}>
      {status}
    </span>
  )
}

const PRIORITY_TONE: Record<Priority, Tone> = {
  Low: 'neutral',
  Medium: 'info',
  High: 'warn',
}

export function PriorityPill({ priority }: { priority: Priority }) {
  return (
    <span className="pill" data-tone={PRIORITY_TONE[priority]}>
      {priority} priority
    </span>
  )
}

/**
 * UI-04: confidence is communicated with a number and a word, so the meaning
 * never depends on colour alone.
 */
export function ConfidenceMeter({
  value,
  threshold,
  label = 'Classifier confidence',
}: {
  value: number
  threshold: number
  label?: string
}) {
  const low = value < threshold
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="kicker">{label}</span>
        <span className="text-sm font-extrabold">
          {percent(value)}{' '}
          <span className="text-xs font-normal muted">
            ({low ? 'below threshold' : 'confident'})
          </span>
        </span>
      </div>
      <div
        className="meter"
        role="progressbar"
        aria-valuenow={Math.round(value * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div
          className="meter-bar"
          data-tone={low ? 'warn' : 'ok'}
          style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }}
        />
      </div>
    </div>
  )
}

const STEPS = ['submitted', 'in_progress', 'resolved'] as const

export function StatusSteps({ status }: { status: string }) {
  const norm = status.toLowerCase()
  const value = norm === 'closed' ? 'resolved' : norm === 'assigned' || norm === 'verification' ? 'in_progress' : norm
  const current = Math.max(0, STEPS.indexOf(value as (typeof STEPS)[number]))
  const labels = ['Submitted', 'Being handled', 'Resolved']
  return (
    <ol className="steps" aria-label="Complaint progress">
      {labels.map((text, index) => (
        <li
          key={text}
          className="step"
          data-state={
            index < current ? 'done' : index === current ? 'current' : 'todo'
          }
          aria-current={index === current ? 'step' : undefined}
        >
          <span className="step-dot" aria-hidden="true" />
          {text}
        </li>
      ))}
    </ol>
  )
}

export function BackendStatus() {
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>('checking')
  const [message, setMessage] = useState('Checking the FastAPI backend…')

  useEffect(() => {
    const controller = new AbortController()
    setHealth('checking')
    checkHealth(controller.signal)
      .then(() => {
        if (controller.signal.aborted) return
        setHealth('online')
        setMessage('FastAPI is reachable.')
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setHealth('offline')
        setMessage(
          error instanceof Error ? error.message : 'The backend is unavailable.',
        )
      })
    return () => controller.abort()
  }, [])

  return (
    <div className={`backend-status backend-status-${health}`}>
      <span className="backend-status-dot" />
      <span className="text-xs">{health === 'online' ? 'Backend Connected' : message}</span>
    </div>
  )
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <span className={`skeleton ${className}`} aria-hidden="true" />
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="load-panel" role="status">
      <Spinner />
      <span>{label}</span>
    </div>
  )
}

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
          {onRetry ? (
            <button type="button" className="btn btn-sm" onClick={onRetry}>
              Retry
            </button>
          ) : null}
          {onReauth ? (
            <button type="button" className="btn btn-sm" onClick={onReauth}>
              Sign in again
            </button>
          ) : null}
        </span>
      </div>
    </Callout>
  )
}

const CALLOUT_ICON: Record<Tone, string> = {
  neutral: 'i',
  info: 'i',
  ok: '✓',
  warn: '!',
  danger: '!',
}

export function Callout({
  tone = 'neutral',
  title,
  children,
}: {
  tone?: Tone
  title?: string
  children: ReactNode
}) {
  return (
    <aside className="callout" data-tone={tone} aria-label={title ?? tone}>
      <span className="callout-icon" aria-hidden="true">
        {CALLOUT_ICON[tone]}
      </span>
      <div className="callout-body">
        {title ? <p className="callout-title">{title}</p> : null}
        <div className="text-sm">{children}</div>
      </div>
    </aside>
  )
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string
  htmlFor?: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  const hintId = htmlFor ? `${htmlFor}-hint` : undefined
  const errorId = htmlFor ? `${htmlFor}-err` : undefined
  return (
    <div className="field">
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint ? (
        <p id={hintId} className="hint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

export function SectionCard({
  title,
  meta,
  action,
  children,
}: {
  title: string
  meta?: ReactNode
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="card card-pad">
      <header className="mb-4 flex flex-wrap items-baseline justify-between gap-2 border-b border-(--line) pb-3">
        <div>
          <h2 className="text-base font-extrabold">{title}</h2>
          {meta ? <p className="m-0 mt-0.5 text-xs muted">{meta}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </header>
      {children}
    </section>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="px-1 py-8 text-center text-sm muted">{children}</p>
}

export function DemoNotice() {
  return (
    <Callout tone="info" title="Demo build — frontend only">
      No FastAPI backend, model provider or vector store is connected. The
      classification, hybrid retrieval and draft generation shown here are
      simulated locally from the seeded policy set so the SRS workflow can be
      reviewed end to end.
    </Callout>
  )
}
