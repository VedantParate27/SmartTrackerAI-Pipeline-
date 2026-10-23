import { useMemo, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  Callout,
  EmptyState,
  ErrorState,
  LoadingState,
  SectionCard,
  Spinner,
} from '#/components/ui'
import type { Tone } from '#/components/ui'
import { PHASE2_MOCK } from '#/lib/analytics'
import { signOut, useAuth } from '#/lib/auth'
import { aiSeverityLabel, aiWasteLabel } from '#/lib/complaint-format'
import { formatAge, formatDateTime, secondsSince } from '#/lib/format'
import {
  LOCATIONS,
  markAllNotificationsRead,
  markNotificationRead,
  reloadNotifications,
  setPreviewLocation,
  simulateIncomingReport,
  useNotificationFeed,
} from '#/lib/notifications'
import type { CleanerNotification, NotificationKind } from '#/lib/notifications'

export const Route = createFileRoute('/cleaner/notifications')({
  component: NotificationsPage,
})

const KIND: Record<NotificationKind, { tone: Tone; label: string }> = {
  task_assigned: { tone: 'info', label: 'New task' },
  task_reassigned: { tone: 'info', label: 'Reassigned' },
  proof_rejected: { tone: 'danger', label: 'Proof rejected' },
  proof_verified: { tone: 'ok', label: 'Verified' },
  area_report: { tone: 'warn', label: 'Area report' },
}

function NotificationsPage() {
  const { session } = useAuth()
  const feed = useNotificationFeed(session)
  const [view, setView] = useState<'all' | 'unread'>('all')
  const [locationFilter, setLocationFilter] = useState<number | 'all'>('all')
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const isAdmin = session?.role === 'admin'
  const rows = feed.feed?.notifications ?? []

  const shown = useMemo(
    () =>
      rows.filter(
        (row) =>
          (view === 'all' || !row.read_at) &&
          (locationFilter === 'all' || row.location_id === locationFilter),
      ),
    [rows, view, locationFilter],
  )

  if (!session) return null

  async function run(action: () => Promise<unknown>) {
    setActionError(null)
    setBusy(true)
    try {
      await action()
    } catch (caught) {
      setActionError(
        caught instanceof Error ? caught.message : 'That did not work.',
      )
    } finally {
      setBusy(false)
    }
  }

  const scope = isAdmin
    ? 'Signed in as an admin, so notifications for every location are listed.'
    : feed.feed?.location_name
      ? `Only notifications for ${feed.feed.location_name} reach you — the location you clean.`
      : 'Notifications for your location.'

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="m-0 text-sm muted">{scope}</p>
        <div className="flex gap-1.5">
          <button
            type="button"
            className="btn btn-sm"
            disabled={feed.loading}
            onClick={() => void reloadNotifications(session)}
          >
            {feed.loading ? <Spinner /> : null}
            {feed.loading ? 'Refreshing…' : 'Refresh'}
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy || feed.unread === 0}
            onClick={() => void run(() => markAllNotificationsRead(session))}
          >
            Mark all read
          </button>
        </div>
      </div>

      {PHASE2_MOCK ? (
        <Callout tone="warn" title="Demo data">
          The notification endpoint is not live yet, so this screen runs on
          synthetic notifications in the agreed format. Nothing here is a real
          task.
        </Callout>
      ) : null}

      {PHASE2_MOCK && !isAdmin ? <LocationRuleDemo /> : null}

      {actionError ? (
        <ErrorState title="Action failed" message={actionError} />
      ) : null}

      {feed.error ? (
        <ErrorState
          title="Notifications could not be loaded"
          message={feed.error}
          onRetry={() => void reloadNotifications(session)}
          onReauth={feed.expired ? signOut : undefined}
        />
      ) : feed.loading && !feed.feed ? (
        <LoadingState label="Loading notifications…" />
      ) : (
        <SectionCard
          title="Notifications"
          meta={`${feed.unread} unread`}
          bodyClassName=""
        >
          <div className="filter-bar">
            <div className="segmented" role="group" aria-label="Show">
              {(['all', 'unread'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={view === value}
                  onClick={() => setView(value)}
                >
                  {value === 'all' ? 'All' : `Unread (${feed.unread})`}
                </button>
              ))}
            </div>
            {isAdmin ? (
              <label className="flex items-center gap-2 text-xs muted">
                Location
                <select
                  className="select select-sm"
                  value={locationFilter}
                  onChange={(event) =>
                    setLocationFilter(
                      event.target.value === 'all'
                        ? 'all'
                        : Number(event.target.value),
                    )
                  }
                >
                  <option value="all">All locations</option>
                  {LOCATIONS.map((location) => (
                    <option key={location.id} value={location.id}>
                      {location.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>

          {shown.length === 0 ? (
            <EmptyState>
              {view === 'unread'
                ? 'You are all caught up.'
                : 'No notifications yet. New tasks for your location appear here.'}
            </EmptyState>
          ) : (
            <ul className="notif-list divide-rows">
              {shown.map((row) => (
                <NotificationRow
                  key={row.id}
                  row={row}
                  showLocation={isAdmin}
                  onRead={() =>
                    void run(() => markNotificationRead(session, row.id))
                  }
                />
              ))}
            </ul>
          )}
        </SectionCard>
      )}
    </div>
  )
}

function NotificationRow({
  row,
  showLocation,
  onRead,
}: {
  row: CleanerNotification
  showLocation: boolean
  onRead: () => void
}) {
  const kind = KIND[row.kind]
  const unread = !row.read_at
  const details = [aiWasteLabel(row.waste_type), aiSeverityLabel(row.severity)]
    .filter(Boolean)
    .join(' · ')

  return (
    <li className="notif" data-unread={unread ? '' : undefined}>
      <span className="notif-dot" data-tone={kind.tone} aria-hidden="true" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <strong className="text-sm">{row.title}</strong>
          <span className="pill" data-tone={kind.tone}>
            {kind.label}
          </span>
          {showLocation ? (
            <span className="pill">{row.location_name}</span>
          ) : null}
          {unread ? <span className="sr-only">Unread.</span> : null}
        </div>
        <p className="mt-1 mb-0 text-sm muted">{row.body}</p>
        <p className="mt-1.5 mb-0 flex flex-wrap gap-x-2 text-xs subtle">
          <time
            dateTime={row.created_at}
            title={formatDateTime(row.created_at)}
          >
            {secondsSince(row.created_at) < 60
              ? 'Just now'
              : `${formatAge(row.created_at, new Date().toISOString())} ago`}
          </time>
          {details ? <span>· {details}</span> : null}
          {row.task_id ? <span className="mono">· {row.task_id}</span> : null}
        </p>
      </div>
      <div className="notif-actions">
        {row.task_id && !PHASE2_MOCK ? (
          <Link
            to="/cleaner/tasks/$taskId"
            params={{ taskId: row.task_id }}
            className="btn btn-sm"
            onClick={unread ? onRead : undefined}
          >
            Open task
          </Link>
        ) : null}
        {unread ? (
          <button
            type="button"
            className="btn btn-sm btn-quiet"
            onClick={onRead}
          >
            Mark read
          </button>
        ) : null}
      </div>
    </li>
  )
}

/**
 * Demo of the Phase 1 location rule on mock data: file a report anywhere and
 * see that only that location's cleaners are notified.
 */
function LocationRuleDemo() {
  const { session } = useAuth()
  const feed = useNotificationFeed(session)
  const [target, setTarget] = useState<number>(LOCATIONS[1].id)
  const [result, setResult] = useState<{
    delivered: boolean
    location: string
  } | null>(null)
  const [sending, setSending] = useState(false)

  if (!session) return null
  const own = feed.feed?.location_id ?? null

  return (
    <SectionCard title="Location rule — try it" meta="Demo only">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="field">
          <span className="label">You are a cleaner in</span>
          <select
            className="select"
            value={own ?? ''}
            disabled={feed.loading}
            onChange={(event) => {
              setResult(null)
              void setPreviewLocation(session, Number(event.target.value))
            }}
          >
            {LOCATIONS.map((location) => (
              <option key={location.id} value={location.id}>
                {location.name}
              </option>
            ))}
          </select>
        </label>
        <div className="field">
          <label className="label" htmlFor="sim-location">
            A citizen reports waste in
          </label>
          <div className="flex gap-1.5">
            <select
              id="sim-location"
              className="select"
              value={target}
              onChange={(event) => {
                setResult(null)
                setTarget(Number(event.target.value))
              }}
            >
              {LOCATIONS.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-primary shrink-0"
              disabled={sending}
              onClick={async () => {
                setSending(true)
                const sent = await simulateIncomingReport(session, target)
                setResult({
                  delivered: sent.delivered,
                  location: sent.row.location_name,
                })
                setSending(false)
              }}
            >
              {sending ? <Spinner /> : null}
              Send
            </button>
          </div>
        </div>
      </div>
      {result ? (
        <div className="mt-3">
          <Callout
            announce
            tone={result.delivered ? 'ok' : 'info'}
            title={result.delivered ? 'You were notified' : 'Not sent to you'}
          >
            {result.delivered
              ? `The report is in ${result.location}, your location, so it is at the top of your feed.`
              : `The report is in ${result.location}. Only ${result.location} cleaners are notified, so your feed is unchanged.`}
          </Callout>
        </div>
      ) : null}
    </SectionCard>
  )
}
