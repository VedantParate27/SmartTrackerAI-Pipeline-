import { useEffect, useMemo, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { Callout, EmptyState, StatusPill } from '#/components/ui'
import { ageInHours, formatAge, percent } from '#/lib/format'
import { getAdminQueue } from '#/lib/api'
import { isVisible, useAppState } from '#/lib/store'
import { CONFIG, DEPARTMENTS, PRIORITIES, STATUSES } from '#/lib/taxonomy'
import type { Complaint } from '#/lib/types'

export const Route = createFileRoute('/admin/')({ component: QueuePage })

const AGE_OPTIONS = [
  { value: 'any', label: 'Any age' },
  { value: '24', label: 'Older than 24 h' },
  { value: '72', label: 'Older than 72 h' },
] as const

const CONFIDENCE_OPTIONS = [
  { value: 'any', label: 'Any confidence' },
  { value: 'low', label: 'Below threshold' },
  { value: 'high', label: 'Above threshold' },
] as const

const OPEN_STATUSES = new Set(['Pending Review', 'Manual Triage'])

function summary(item: Complaint) {
  const text = item.text.trim()
  return text.length > 120 ? `${text.slice(0, 120)}…` : text
}

function QueuePage() {
  const { session, now } = useAppState()
  const [backendCases, setBackendCases] = useState<Complaint[]>([])

    useEffect(() => {
    getAdminQueue()
      .then((items) => {
        const mapped: Complaint[] = items.map((item) => ({
          id: String(item.id),
          requesterName: `User ${item.user_id}`,
          contact: '',
          channel: 'Web',
          language: 'English',
          text: item.complaint_text,
          attachments: [],
          priority: 'Medium',
          status:
            item.status === 'awaiting_review'
              ? 'Pending Review'
              : 'Submitted',
          submittedAt: item.created_at,
          updatedAt: item.updated_at,
          assignedDepartment: item.department,
          classification: item.category
            ? {
                intent: item.category,
                department: item.department ?? 'other',
                confidence: item.confidence_score ?? 0,
                alternatives: [],
                modelVersion: 'Gemini',
                taxonomyVersion: 'Phase 2',
                ruleApplied: null,
                overriddenBy: null,
              }
            : null,
          entities: [],
          evidence: [],
          aiDraft: null,
          editedDraft: null,
          resolution: null,
          closureReason: null,
          duplicateOf: null,
          comments: [],
          audit: [],
        }))

        setBackendCases(mapped)
      })
      .catch((error) => {
        console.error('Failed to load admin queue:', error)
      })
  }, [])

  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('any')
  const [department, setDepartment] = useState('any')
  const [priority, setPriority] = useState('any')
  const [age, setAge] = useState<(typeof AGE_OPTIONS)[number]['value']>('any')
  const [confidence, setConfidence] =
    useState<(typeof CONFIDENCE_OPTIONS)[number]['value']>('any')

  const permitted = useMemo(
  () => backendCases.filter((item) => isVisible(item, session)),
  [backendCases, session],
  )

  const stats = useMemo(
    () => [
      {
        label: 'Awaiting review',
        value: permitted.filter((item) => OPEN_STATUSES.has(item.status))
          .length,
      },
      {
        label: 'Manual triage',
        value: permitted.filter((item) => item.status === 'Manual Triage')
          .length,
      },
      {
        label: 'Escalated',
        value: permitted.filter((item) => item.status === 'Escalated').length,
      },
      {
        label: 'With department',
        value: permitted.filter(
          (item) =>
            item.status === 'Assigned to Department' ||
            item.status === 'In Progress',
        ).length,
      },
      {
        label: 'Resolved or closed',
        value: permitted.filter(
          (item) => item.status === 'Resolved' || item.status === 'Closed',
        ).length,
      },
    ],
    [permitted],
  )

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()

    return permitted
      .filter((item) => {
        if (needle) {
          const haystack = `${item.id} ${item.requesterName} ${item.text} ${item.classification?.intent ?? ''}`
          if (!haystack.toLowerCase().includes(needle)) return false
        }
        if (status !== 'any' && item.status !== status) return false
        if (priority !== 'any' && item.priority !== priority) return false

        if (department !== 'any') {
          const owner =
            item.assignedDepartment ?? item.classification?.department
          if (owner !== department) return false
        }

        if (age !== 'any' && ageInHours(item.submittedAt, now) < Number(age)) {
          return false
        }

        if (confidence !== 'any') {
          const score = item.classification?.confidence
          if (score === undefined) return confidence === 'low'
          const low = score < CONFIG.confidenceThreshold
          if (confidence === 'low' ? !low : low) return false
        }

        return true
      })
      .sort(
        (a, b) =>
          new Date(b.submittedAt).getTime() - new Date(a.submittedAt).getTime(),
      )
  }, [permitted, search, status, department, priority, age, confidence, now])

  return (
    <div className="grid gap-4">
      {session.departments !== null ? (
        <Callout tone="info" title="Department-limited view">
          You are signed in as {session.role} for{' '}
          {session.departments.join(', ')}. Cases routed elsewhere are not
          listed.
        </Callout>
      ) : null}

      <section
        aria-label="Queue summary"
        className="grid grid-cols-2 gap-2 sm:grid-cols-5"
      >
        {stats.map((stat) => (
          <div key={stat.label} className="stat">
            <p className="stat-value m-0">{stat.value}</p>
            <p className="m-0 mt-0.5 text-xs muted">{stat.label}</p>
          </div>
        ))}
      </section>

      {/* UI-02: queue filters for status, department, age, priority, confidence. */}
      <section className="card card-pad" aria-labelledby="filters-heading">
        <h2 id="filters-heading" className="kicker">
          Filters
        </h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div className="sm:col-span-2 lg:col-span-1">
            <label className="sr-only" htmlFor="q">
              Search cases
            </label>
            <input
              id="q"
              className="input"
              type="search"
              placeholder="Search reference, requester or text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>

          <label className="sr-only" htmlFor="f-status">
            Status
          </label>
          <select
            id="f-status"
            className="select"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="any">Any status</option>
            {STATUSES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="f-dept">
            Department
          </label>
          <select
            id="f-dept"
            className="select"
            value={department}
            onChange={(event) => setDepartment(event.target.value)}
          >
            <option value="any">Any department</option>
            {DEPARTMENTS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="f-priority">
            Priority
          </label>
          <select
            id="f-priority"
            className="select"
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
          >
            <option value="any">Any priority</option>
            {PRIORITIES.map((item) => (
              <option key={item} value={item}>
                {item} priority
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="f-age">
            Age
          </label>
          <select
            id="f-age"
            className="select"
            value={age}
            onChange={(event) =>
              setAge(
                event.target.value as (typeof AGE_OPTIONS)[number]['value'],
              )
            }
          >
            {AGE_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="f-confidence">
            Confidence
          </label>
          <select
            id="f-confidence"
            className="select"
            value={confidence}
            onChange={(event) =>
              setConfidence(
                event.target
                  .value as (typeof CONFIDENCE_OPTIONS)[number]['value'],
              )
            }
          >
            {CONFIDENCE_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
      </section>

      <section className="card overflow-hidden" aria-labelledby="queue-heading">
        <div className="card-head">
          <h2 id="queue-heading" className="card-title">
            Case queue
          </h2>
          <div className="text-xs muted">
            {filtered.length} of {permitted.length} cases
          </div>
        </div>

        <div className="queue-head kicker" aria-hidden="true">
          <span>Reference</span>
          <span>Complaint</span>
          <span>Department</span>
          <span>Confidence</span>
          <span>Age</span>
          <span />
        </div>

        <div className="divide-rows">
          {filtered.length === 0 ? (
            <EmptyState>No cases match the current filters.</EmptyState>
          ) : (
            filtered.map((item) => {
              const owner =
                item.assignedDepartment ??
                item.classification?.department ??
                '—'
              const score = item.classification?.confidence
              const low =
                score !== undefined && score < CONFIG.confidenceThreshold

              return (
                <Link
                  key={item.id}
                  to="/admin/cases/$caseId"
                  params={{ caseId: item.id }}
                  className="queue-row"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="mono font-bold">{item.id}</span>
                    <StatusPill status={item.status} />
                  </div>

                  <div className="min-w-0">
                    <p className="m-0 text-sm">{summary(item)}</p>
                    <p className="m-0 mt-0.5 text-xs subtle">
                      {item.classification?.intent ?? 'Not yet classified'} ·{' '}
                      {item.requesterName} · {item.priority} priority
                    </p>
                  </div>

                  <div className="text-xs muted" data-label="Department">
                    {owner}
                  </div>

                  <div className="text-xs" data-label="Confidence">
                    {score === undefined ? (
                      <span className="subtle">Pending</span>
                    ) : (
                      <span className={low ? 'font-bold text-(--warn)' : ''}>
                        {percent(score)}
                        {low ? ' · low' : ''}
                      </span>
                    )}
                  </div>

                  <div className="text-xs muted" data-label="Age">
                    {formatAge(item.submittedAt, now)}
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
      </section>
    </div>
  )
}
