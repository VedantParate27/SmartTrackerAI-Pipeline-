import type { ReactNode } from 'react'
import { API_BASE_URL } from '#/lib/api'
import { useAppState } from '#/lib/store'
import { STATUS_TONE } from '#/lib/taxonomy'
import type { Tone } from '#/lib/taxonomy'
import { percent } from '#/lib/format'
import type { CaseStatus, Priority } from '#/lib/types'

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
          <span className={low ? 'text-(--warn)' : 'text-(--ok)'}>
            {low ? '· below threshold' : '· above threshold'}
          </span>
        </span>
      </div>
      <div
        className="meter"
        role="meter"
        aria-valuenow={Math.round(value * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${percent(value)}, threshold ${percent(threshold)}`}
      >
        <div
          className="meter-fill"
          data-tone={low ? 'warn' : 'ok'}
          style={{ width: `${Math.max(3, Math.round(value * 100))}%` }}
        />
      </div>
      <p className="hint">
        Configured threshold: {percent(threshold)}. Cases below it go to manual
        triage.
      </p>
    </div>
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

export function DemoNotice() {
  const { syncStatus, syncMessage, backendRevision } = useAppState()
  const tone =
    syncStatus === 'online' ? 'ok' : syncStatus === 'offline' ? 'warn' : 'info'
  const title =
    syncStatus === 'online'
      ? 'Backend connected'
      : syncStatus === 'offline'
        ? 'Offline fallback active'
        : 'Connecting to backend'

  return (
    <Callout tone={tone} title={title}>
      {syncMessage}{' '}
      <span className="subtle">
        API: <span className="mono">{API_BASE_URL}</span>
        {backendRevision > 0 ? ` · revision ${backendRevision}` : ''}. AI
        analysis remains the deterministic prototype pipeline until a model
        provider and vector index are configured.
      </span>
    </Callout>
  )
}
