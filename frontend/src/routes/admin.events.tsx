import { useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  Callout,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  SectionCard,
  Spinner,
} from '#/components/ui'
import {
  ACTOR_ROLES,
  EVENT_ACTIVITIES,
  downloadExport,
  getEvents,
} from '#/lib/api'
import type { EventFilters } from '#/lib/api'
import { signOut, useAuth } from '#/lib/auth'
import { activityLabel, humanize } from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'
import { useApi } from '#/lib/use-api'

export const Route = createFileRoute('/admin/events')({ component: EventsPage })

const LIMITS = [100, 500, 2000, 5000]

function EventsPage() {
  const { session } = useAuth()
  const token = session?.role === 'admin' ? session.accessToken : undefined

  const [draft, setDraft] = useState<EventFilters>({ limit: 100 })
  const [applied, setApplied] = useState<EventFilters>({ limit: 100 })

  const events = useApi(
    token ? (signal) => getEvents(applied, token, signal) : null,
    [
      token,
      applied.case_id,
      applied.activity,
      applied.actor_role,
      applied.limit,
    ],
  )

  if (!token) {
    return (
      <Callout tone="danger" title="Admin session required">
        Sign in with a backend admin account to read the event log.
      </Callout>
    )
  }

  return (
    <div className="grid gap-4">
      <SectionCard title="Exports" meta="CSV · for pm4py and the DWM notebooks">
        <div className="grid gap-3 sm:grid-cols-2">
          <ExportButton
            label="Event log"
            detail="One row per lifecycle event, pm4py column names."
            path="/admin/events/export"
            filename="event_log.csv"
            token={token}
          />
          <ExportButton
            label="Mining dataset"
            detail="One row per complaint, 24 fields; seeded rows flagged."
            path="/admin/mining/dataset/export"
            filename="mining_dataset.csv"
            token={token}
          />
        </div>
      </SectionCard>

      <section className="card card-pad" aria-labelledby="event-filters">
        <h2 id="event-filters" className="kicker">
          Filters
        </h2>
        <form
          className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-5 lg:items-end"
          onSubmit={(event) => {
            event.preventDefault()
            setApplied({
              ...draft,
              case_id: draft.case_id?.trim() || undefined,
            })
          }}
        >
          <Field label="Case" htmlFor="filter-case">
            <input
              id="filter-case"
              className="input"
              placeholder="TRK-…"
              spellCheck={false}
              value={draft.case_id ?? ''}
              onChange={(event) =>
                setDraft({ ...draft, case_id: event.target.value })
              }
            />
          </Field>
          <Field label="Activity" htmlFor="filter-activity">
            <select
              id="filter-activity"
              className="select"
              value={draft.activity ?? ''}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  activity: event.target.value || undefined,
                })
              }
            >
              <option value="">Any activity</option>
              {EVENT_ACTIVITIES.map((activity) => (
                <option key={activity} value={activity}>
                  {activityLabel(activity)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Actor" htmlFor="filter-actor">
            <select
              id="filter-actor"
              className="select"
              value={draft.actor_role ?? ''}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  actor_role: event.target.value || undefined,
                })
              }
            >
              <option value="">Any actor</option>
              {ACTOR_ROLES.map((role) => (
                <option key={role} value={role}>
                  {humanize(role)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Show" htmlFor="filter-limit">
            <select
              id="filter-limit"
              className="select"
              value={draft.limit}
              onChange={(event) =>
                setDraft({ ...draft, limit: Number(event.target.value) })
              }
            >
              {LIMITS.map((limit) => (
                <option key={limit} value={limit}>
                  Latest {limit}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={events.loading}
          >
            {events.loading ? <Spinner /> : null}
            Apply
          </button>
        </form>
      </section>

      <section
        className="card overflow-hidden"
        aria-labelledby="events-heading"
        aria-busy={events.loading}
      >
        <div className="card-head">
          <h2 id="events-heading" className="card-title">
            Lifecycle events
          </h2>
          <div className="text-xs muted">
            {events.data ? `${events.data.length} shown, newest first` : null}
          </div>
        </div>

        {events.error ? (
          <div className="card-pad">
            <ErrorState
              title="Events could not be loaded"
              message={events.error}
              onRetry={events.reload}
              onReauth={events.expired ? signOut : undefined}
            />
          </div>
        ) : events.loading && !events.data ? (
          <div className="card-pad">
            <LoadingState label="Loading events…" />
          </div>
        ) : events.data && events.data.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Case</th>
                  <th scope="col">Activity</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Change</th>
                </tr>
              </thead>
              <tbody>
                {events.data.map((event) => (
                  <tr key={event.event_id}>
                    <td className="whitespace-nowrap">
                      {formatDateTime(event.timestamp)}
                    </td>
                    <td className="whitespace-nowrap">
                      <Link
                        to="/admin/cases/$caseId"
                        params={{ caseId: event.case_id }}
                        className="mono"
                      >
                        {event.case_id}
                      </Link>
                    </td>
                    <td>{activityLabel(event.activity)}</td>
                    <td>
                      {event.actor_role ? humanize(event.actor_role) : '—'}
                      {event.actor_id !== null ? (
                        <span className="subtle"> #{event.actor_id}</span>
                      ) : null}
                    </td>
                    <td className="mono text-xs">
                      {event.old_value || event.new_value
                        ? `${event.old_value ?? '—'} → ${event.new_value ?? '—'}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>No events match these filters.</EmptyState>
        )}
      </section>
    </div>
  )
}

function ExportButton({
  label,
  detail,
  path,
  filename,
  token,
}: {
  label: string
  detail: string
  path: '/admin/events/export' | '/admin/mining/dataset/export'
  filename: string
  token: string
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  return (
    <div className="grid content-start gap-2">
      <button
        type="button"
        className="btn justify-between"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          setError(null)
          try {
            await downloadExport(path, filename, token)
          } catch (caught) {
            setError(
              caught instanceof Error ? caught.message : 'Download failed.',
            )
          } finally {
            setBusy(false)
          }
        }}
      >
        <span>{busy ? 'Preparing…' : `Download ${label.toLowerCase()}`}</span>
        {busy ? <Spinner /> : <span aria-hidden="true">↓</span>}
      </button>
      <p className="m-0 text-xs muted">{detail}</p>
      {error ? <ErrorState title="Download failed" message={error} /> : null}
    </div>
  )
}
