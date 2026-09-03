import { useEffect, useMemo, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  BackendPriorityPill,
  BackendStatusPill,
  Callout,
  EmptyState,
  ErrorState,
  Skeleton,
  Spinner,
} from '#/components/ui'
import { getAdminQueue } from '#/lib/api'
import type { AdminQueueItem } from '#/lib/api'
import { isExpiredSession, signOut, useAuth } from '#/lib/auth'
import {
  backendCategory,
  backendClassificationConfidence,
} from '#/lib/complaint-format'
import { formatAge } from '#/lib/format'

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
  const [cases, setCases] = useState<AdminQueueItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [reload, setReload] = useState(0)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('any')
  const [department, setDepartment] = useState('any')
  const [priority, setPriority] = useState('any')

  useEffect(() => {
    if (!session || session.role !== 'admin') return
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getAdminQueue(session.accessToken, controller.signal)
      .then(setCases)
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setExpired(isExpiredSession(caught))
        setError(
          caught instanceof Error
            ? caught.message
            : 'The complaint queue could not be loaded.',
        )
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [reload, session])

  const statusOptions = useMemo(
    () => unique(cases.map((item) => item.status)),
    [cases],
  )
  const departmentOptions = useMemo(
    () => unique(cases.map((item) => item.department)),
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
        backendCategory(item.classification),
        item.department,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (needle && !haystack.includes(needle)) return false
      if (status !== 'any' && item.status !== status) return false
      if (department !== 'any' && item.department !== department) {
        return false
      }
      if (priority !== 'any' && item.priority !== priority) return false
      return true
    })
  }, [cases, search, status, department, priority])

  const stats = useMemo(() => {
    const count = (wanted: string[]) =>
      cases.filter((item) => wanted.includes(item.status.toLowerCase())).length
    return [
      { label: 'Total complaints', value: cases.length },
      { label: 'Pending', value: count(['pending']) },
      { label: 'In progress', value: count(['in_progress']) },
      { label: 'Resolved', value: count(['resolved']) },
      {
        label: 'Unassigned',
        value: cases.filter((item) => !item.department).length,
      },
    ]
  }, [cases])

  if (!session || session.role !== 'admin') {
    return (
      <Callout tone="danger" title="Admin session required">
        Sign in with a backend admin account to load this queue.
      </Callout>
    )
  }

  return (
    <div className="grid gap-4">
      {error ? (
        <ErrorState
          title="Queue request failed"
          message={error}
          onRetry={() => setReload((n) => n + 1)}
          onReauth={expired ? signOut : undefined}
        />
      ) : null}

      <section
        aria-label="Queue summary"
        className="grid grid-cols-2 gap-2 sm:grid-cols-5"
      >
        {stats.map((stat) => (
          <div key={stat.label} className="stat">
            <p className="stat-value m-0">
              {loading && cases.length === 0 ? (
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
            disabled={loading}
            onClick={() => setReload((n) => n + 1)}
          >
            {loading ? <Spinner /> : null}
            {loading ? 'Refreshing…' : 'Refresh from backend'}
          </button>
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <input
            className="input"
            type="search"
            aria-label="Search complaints"
            placeholder="Search reference, requester or complaint text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
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
            aria-label="Department"
            value={department}
            onChange={(event) => setDepartment(event.target.value)}
          >
            <option value="any">Any department</option>
            {departmentOptions.map((item) => (
              <option key={item} value={item}>
                {item}
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
        aria-busy={loading}
      >
        <div className="card-head">
          <h2 id="queue-heading" className="card-title">
            Live complaint queue
          </h2>
          <div className="text-xs muted">
            {filtered.length} of {cases.length} complaints
          </div>
        </div>

        {loading && cases.length === 0 ? (
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
                  ? 'The backend has no complaints yet. Submit one to populate this queue.'
                  : 'No complaints match the current filters.'}
              </EmptyState>
            ) : (
              filtered.map((item) => {
                const category = backendCategory(item.classification)
                const confidence = backendClassificationConfidence(
                  item.classification,
                )
                return (
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
                        <BackendPriorityPill priority={item.priority} />
                        {category ? (
                          <span className="pill">{category}</span>
                        ) : null}
                      </div>
                    </div>
                    <div className="text-xs muted" data-label="Department">
                      {item.department ?? 'Unassigned'}
                    </div>
                    <div className="text-xs" data-label="Confidence">
                      {confidence ?? (
                        <span className="subtle">Not returned</span>
                      )}
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
                )
              })
            )}
          </div>
        )}
      </section>
    </div>
  )
}
