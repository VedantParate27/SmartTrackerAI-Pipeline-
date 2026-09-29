import type { Tone } from '#/components/ui'
import type { EventLogEntry } from '#/lib/api'
import { activityLabel, humanize } from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'

const TONE: Record<string, Tone> = {
  human_review_required: 'warn',
  ai_correction_recorded: 'warn',
  proof_rejected: 'danger',
  proof_verified: 'ok',
  complaint_resolved: 'ok',
  complaint_closed: 'ok',
  guidance_decided: 'ok',
}

/** Meta keys worth surfacing; the rest stay in the CSV export. */
const META_KEYS = [
  'field',
  'reasons',
  'confidence',
  'decision',
  'cleaner_name',
  'rejection_reason',
  'notes',
  'task_id',
] as const

function metaSummary(meta: EventLogEntry['meta']) {
  if (!meta) return null
  const parts = META_KEYS.flatMap((key) => {
    const value = meta[key]
    if (value === null || value === undefined || value === '') return []
    const text = Array.isArray(value)
      ? value.join(', ')
      : typeof value === 'object'
        ? JSON.stringify(value)
        : String(value)
    return [`${humanize(key)}: ${text}`]
  })
  return parts.length > 0 ? parts.join(' · ') : null
}

/** Events arrive newest first; the timeline reads top-down in time order. */
export default function CaseTimeline({ events }: { events: EventLogEntry[] }) {
  if (events.length === 0) {
    return <p className="m-0 text-sm muted">No events recorded yet.</p>
  }
  return (
    <ol className="timeline">
      {[...events].reverse().map((event) => {
        const detail = metaSummary(event.meta)
        const change =
          event.old_value || event.new_value
            ? `${event.old_value ?? '—'} → ${event.new_value ?? '—'}`
            : null
        return (
          <li key={event.event_id} data-tone={TONE[event.activity] ?? 'info'}>
            <p className="m-0 text-sm font-bold">
              {activityLabel(event.activity)}
            </p>
            <p className="m-0 text-xs muted">
              {formatDateTime(event.timestamp)}
              {event.actor_role ? ` · ${humanize(event.actor_role)}` : ''}
            </p>
            {change ? (
              <p className="m-0 mt-0.5 mono text-xs subtle">{change}</p>
            ) : null}
            {detail ? (
              <p className="m-0 mt-0.5 text-xs muted">{detail}</p>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
