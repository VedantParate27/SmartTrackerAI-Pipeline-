import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { API_BASE_URL, checkHealth } from '#/lib/api'
import {
  backendConfidence,
  reviewReasonLabel,
  wasteLabel,
} from '#/lib/complaint-format'

export type Tone = 'neutral' | 'info' | 'warn' | 'ok' | 'danger'

function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="pill" data-tone={tone}>
      {children}
    </span>
  )
}

const STATUS_TONE: Record<string, Tone> = {
  pending: 'neutral',
  in_progress: 'info',
  resolved: 'ok',
  closed: 'neutral',
}

export function BackendStatusPill({ status }: { status: string }) {
  return (
    <Pill tone={STATUS_TONE[status.toLowerCase()] ?? 'neutral'}>
      {status.replaceAll('_', ' ')}
    </Pill>
  )
}

export function BackendPriorityPill({ priority }: { priority: string }) {
  const value = priority.toLowerCase()
  const tone: Tone =
    value === 'urgent'
      ? 'danger'
      : value === 'high'
        ? 'warn'
        : value === 'medium'
          ? 'info'
          : 'neutral'
  return <Pill tone={tone}>{priority} priority</Pill>
}

/** Hazardous and medical waste carry a safety policy, so they read as danger. */
export function WastePill({ wasteType }: { wasteType: string | null }) {
  if (!wasteType) return <Pill tone="neutral">Type not set</Pill>
  const tone: Tone = ['hazardous', 'medical'].includes(wasteType)
    ? 'danger'
    : wasteType === 'e_waste'
      ? 'warn'
      : 'neutral'
  return <Pill tone={tone}>{wasteLabel(wasteType)}</Pill>
}

export function ReviewPill({
  required,
  reason,
}: {
  required: boolean | null
  reason: string | null
}) {
  if (!required) return null
  return (
    <Pill tone="warn">
      Needs review{reason ? ` · ${reviewReasonLabel(reason)}` : ''}
    </Pill>
  )
}

/** Confidence is judged against the threshold the backend actually used. */
export function ConfidenceBadge({
  confidence,
  threshold,
}: {
  confidence: number | null
  threshold: number
}) {
  const text = backendConfidence(confidence)
  if (text === null) return <Pill tone="warn">No confidence score</Pill>
  const tone: Tone = (confidence ?? 0) >= threshold ? 'ok' : 'warn'
  return (
    <Pill tone={tone}>
      {text} confidence
      <span className="sr-only">
        {' '}
        against a {backendConfidence(threshold)} threshold
      </span>
    </Pill>
  )
}

const TASK_TONE: Record<string, Tone> = {
  assigned: 'info',
  in_progress: 'info',
  proof_submitted: 'warn',
  verified: 'ok',
  rejected: 'danger',
}

export function TaskStatusPill({ status }: { status: string }) {
  return (
    <Pill tone={TASK_TONE[status] ?? 'neutral'}>
      Task {status.replaceAll('_', ' ')}
    </Pill>
  )
}

const PROOF_TONE: Record<string, Tone> = {
  pending_verification: 'warn',
  verified: 'ok',
  rejected: 'danger',
}

export function ProofStatusPill({ status }: { status: string }) {
  return (
    <Pill tone={PROOF_TONE[status] ?? 'neutral'}>
      {status === 'pending_verification'
        ? 'Awaiting check'
        : status.replaceAll('_', ' ')}
    </Pill>
  )
}

/**
 * A proof photo that degrades to a labelled placeholder. Seeded proofs point
 * at files that were never written, so a missing image is a normal case.
 */
export function ProofImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false)
  const ref = useRef<HTMLImageElement>(null)

  // An image that failed during SSR, before React attached onError, never
  // fires the event again; a completed image with no pixels has failed.
  useEffect(() => {
    const image = ref.current
    if (image?.complete && image.naturalWidth === 0) setFailed(true)
  }, [src])

  if (failed) {
    return (
      <div className="proof-image proof-missing" role="img" aria-label={alt}>
        <span>Image unavailable</span>
      </div>
    )
  }
  return (
    <a href={src} target="_blank" rel="noreferrer">
      <img
        ref={ref}
        className="proof-image"
        src={src}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    </a>
  )
}

const STEPS = ['pending', 'in_progress', 'resolved'] as const

/** Citizen-facing progress: submitted → being handled → resolved. */
export function StatusSteps({ status }: { status: string }) {
  const value = status.toLowerCase() === 'closed' ? 'resolved' : status
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
  label: ReactNode
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
