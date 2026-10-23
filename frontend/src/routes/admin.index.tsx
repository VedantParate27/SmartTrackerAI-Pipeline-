import { useMemo, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  BackendPriorityPill,
  BackendStatusPill,
  Callout,
  EmptyState,
  ErrorState,
  ReviewPill,
  Skeleton,
  Spinner,
  WastePill,
} from '#/components/ui'
import { WASTE_TYPES, getAdminQueue, needsReview } from '#/lib/api'
import type { AdminQueueItem } from '#/lib/api'
import { signOut, useAuth } from '#/lib/auth'
import {
  formatCoordinates,
  severityLabel,
  triageModeLabel,
  wasteLabel,
} from '#/lib/complaint-format'
import { formatAge } from '#/lib/format'
import { useApi } from '#/lib/use-api'

export const Route = createFileRoute('/admin/')({ component: QueuePage })

function unique(values: Array<string | null | undefined>) {
  return [
    ...new Set(values.filter((value): value is string => Boolean(value))),
  ].sort()
}

function summary(item: AdminQueueItem) {
  const text = item.complaint_text.trim()
  return text.length > 120 ? `${text.slice(0, 120)}…` : text
}

function QueuePage() {
  const { session } = useAuth()
  const token = session?.role === 'admin' ? session.accessToken : undefined
  const queue = useApi(
    token ? (signal) => getAdminQueue(token, signal) : null,
    [token],
  )
  const cases = useMemo(() => queue.data ?? [], [queue.data])

  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('any')
  const [waste, setWaste] = useState('any')
  const [review, setReview] = useState('any')
  const [priority, setPriority] = useState('any')

  const statusOptions = useMemo(
    () => unique(cases.map((item) => item.status)),
    [cases],
  )
  const priorityOptions = useMemo(
    () => unique(cases.map((item) => item.priority)),
    [cases],
  )

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return cases.filter((item) => {
      const haystack = [
        item.tracking_id,
        item.complaint_text,
        item.name,
        item.email,
        item.address_text,
        item.department,
        wasteLabel(item.waste_type),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (needle && !haystack.includes(needle)) return false
      if (status !== 'any' && item.status !== status) return false
      if (waste === 'none' && item.waste_type) return false
      if (waste !== 'any' && waste !== 'none' && item.waste_type !== waste) {
        return false
      }
      if (review === 'yes' && !needsReview(item)) return false
      if (review === 'no' && needsReview(item)) return false
      if (priority !== 'any' && item.priority !== priority) return false
      return true
    })
  }, [cases, search, status, waste, review, priority])

  const stats = useMemo(() => {
    const count = (wanted: string) =>
      cases.filter((item) => item.status.toLowerCase() === wanted).length
    return [
      { label: 'Total', value: cases.length },
      {
        label: 'Needs review',
        value: cases.filter(needsReview).length,
      },
      { label: 'Pending', value: count('pending') },
      { label: 'In progress', value: count('in_progress') },
      { label: 'Resolved', value: count('resolved') },
    ]
  }, [cases])

  if (!token) {
    return (
      <Callout tone="danger" title="Admin session required">
        Sign in with a backend admin account to load this queue.
      </Callout>
    )
  }

  return (
    <div className="grid gap-4">
      {queue.error ? (
        <ErrorState
          title="Queue request failed"
          message={queue.error}
          onRetry={queue.reload}
          onReauth={queue.expired ? signOut : undefined}
        />
      ) : null}

      <section
        aria-label="Queue summary"
        className="grid grid-cols-2 gap-2 sm:grid-cols-5"
      >
        {stats.map((stat) => (
          <div key={stat.label} className="stat">
            <p className="stat-value m-0">
              {queue.loading && !queue.data ? (
                <Skeleton className="mt-2 h-5 w-10" />
              ) : (
                stat.value
              )}
            </p>
            <p className="m-0 mt-0.5 text-xs muted">{stat.label}</p>
          </div>
        ))}
      </section>

      <section className="card card-pad" aria-labelledby="filters-heading">
        <div className="flex items-center justify-between gap-2">
          <h2 id="filters-heading" className="kicker">
            Filters
          </h2>
          <button
            type="button"
            className="btn btn-sm"
            disabled={queue.loading}
            onClick={queue.reload}
          >
            {queue.loading ? <Spinner /> : null}
            {queue.loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <input
            className="input lg:col-span-1"
            type="search"
            aria-label="Search complaints"
            placeholder="Search ID, text, address"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="select"
            aria-label="Review"
            value={review}
            onChange={(event) => setReview(event.target.value)}
          >
            <option value="any">Any review state</option>
            <option value="yes">Needs review</option>
            <option value="no">No review pending</option>
          </select>
          <select
            className="select"
            aria-label="Waste type"
            value={waste}
            onChange={(event) => setWaste(event.target.value)}
          >
            <option value="any">Any waste type</option>
            {WASTE_TYPES.map((type) => (
              <option key={type} value={type}>
                {wasteLabel(type)}
              </option>
            ))}
            <option value="none">Not set</option>
          </select>
          <select
            className="select"
            aria-label="Status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="any">Any status</option>
            {statusOptions.map((item) => (
              <option key={item} value={item}>
                {item.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
          <select
            className="select"
            aria-label="Priority"
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
          >
            <option value="any">Any priority</option>
            {priorityOptions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </section>

      <section
        className="card overflow-hidden"
        aria-labelledby="queue-heading"
        aria-busy={queue.loading}
      >
        <div className="card-head">
          <h2 id="queue-heading" className="card-title">
            Complaint queue
          </h2>
          <div className="text-xs muted">
            {filtered.length} of {cases.length} complaints
          </div>
        </div>

        {queue.loading && !queue.data ? (
          <div
            className="divide-rows"
            role="status"
            aria-label="Loading complaints"
          >
            {[0, 1, 2, 3].map((row) => (
              <div key={row} className="queue-row">
                <Skeleton className="w-28" />
                <Skeleton className="w-full" />
                <Skeleton className="w-20" />
                <Skeleton className="w-12" />
                <Skeleton className="w-10" />
                <Skeleton className="w-8" />
              </div>
            ))}
          </div>
        ) : (
          <div className="divide-rows">
            {filtered.length === 0 ? (
              <EmptyState>
                {cases.length === 0
                  ? 'The backend has no complaints yet. Submit one, or run the seeder, to populate this queue.'
                  : 'No complaints match the current filters.'}
              </EmptyState>
            ) : (
              filtered.map((item) => (
                <Link
                  key={item.tracking_id}
                  to="/admin/cases/$caseId"
                  params={{ caseId: item.tracking_id }}
                  className="queue-row"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="mono font-bold">{item.tracking_id}</span>
                    <BackendStatusPill status={item.status} />
                  </div>
                  <div className="min-w-0">
                    <p className="m-0 text-sm">{summary(item)}</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      <ReviewPill
                        required={needsReview(item)}
                        reason={item.review_reason}
                      />
                      <WastePill wasteType={item.waste_type} />
                      {item.quantity_severity ? (
                        <span className="pill">
                          {severityLabel(item.quantity_severity)}
                        </span>
                      ) : null}
                      <BackendPriorityPill priority={item.priority} />
                      {item.department ? (
                        <span className="pill normal-case whitespace-normal [overflow-wrap:anywhere]">
                          {item.department}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="truncate text-xs muted" data-label="Location">
                    {item.address_text ??
                      formatCoordinates(item.latitude, item.longitude) ??
                      'No location'}
                  </div>
                  <div className="text-xs" data-label="Triage">
                    {triageModeLabel(item.triage_mode)}
                  </div>
                  <div className="text-xs muted" data-label="Age">
                    {formatAge(item.created_at, new Date().toISOString())}
                  </div>
                  <div
                    className="text-right text-sm text-(--accent)"
                    aria-hidden="true"
                  >
                    Open →
                  </div>
                </Link>
              ))
            )}
          </div>
        )}
      </section>
    </div>
  )
}
