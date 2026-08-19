import { useState } from 'react'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { Callout, Field, PriorityPill, StatusPill } from '#/components/ui'
import { formatDateTime } from '#/lib/format'
import { findCase, useAppState } from '#/lib/store'
import { STATUS_MEANING } from '#/lib/taxonomy'
import type { CaseStatus } from '#/lib/types'

export const Route = createFileRoute('/track')({
  // `id` is optional so other pages can link to /track without a reference.
  validateSearch: (search: Record<string, unknown>): { id?: string } =>
    typeof search.id === 'string' && search.id ? { id: search.id } : {},
  component: TrackPage,
})

/** The requester-facing slice of the lifecycle in Appendix A.1. */
const VISIBLE_LIFECYCLE: CaseStatus[] = [
  'Submitted',
  'AI Analysis',
  'Pending Review',
  'Assigned to Department',
  'In Progress',
  'Resolved',
  'Closed',
]

/** BR-05: internal AI reasoning and staff notes stay out of the requester view. */
const HIDDEN_ACTIONS = [
  'AI analysis completed',
  'Classification overridden',
  'Draft edited',
]

function TrackPage() {
  const { id = '' } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const [query, setQuery] = useState(id)

  // Subscribe so the view updates while the pipeline runs.
  useAppState()
  const found = id ? findCase(id) : null

  return (
    <main id="main" className="wrap page max-w-2xl">
      <p className="kicker">Case status</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">Track a case</h1>
      <p className="mt-2 text-sm muted">
        Enter the reference number from your acknowledgement, for example{' '}
        <span className="mono">GRV-2026-0431</span>.
      </p>

      <form
        className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-end"
        onSubmit={(event) => {
          event.preventDefault()
          navigate({ search: { id: query.trim() } })
        }}
      >
        <div className="flex-1">
          <Field label="Tracking reference" htmlFor="track-id">
            <input
              id="track-id"
              className="input"
              value={query}
              placeholder="GRV-2026-0431"
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setQuery(event.target.value)}
            />
          </Field>
        </div>
        <button type="submit" className="btn btn-primary">
          Check status
        </button>
      </form>

      <div className="mt-6" aria-live="polite">
        {id && !found ? (
          <Callout tone="warn" title="No case found">
            No grievance is stored against <span className="mono">{id}</span>.
            Check the reference and try again. Cases created in this demo live
            in your browser only.
          </Callout>
        ) : null}

        {found ? (
          <div className="grid gap-4">
            <section className="card card-pad">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <span className="kicker">Reference</span>
                  <p className="mono mt-0.5 text-lg font-extrabold">
                    {found.id}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <StatusPill status={found.status} />
                  <PriorityPill priority={found.priority} />
                </div>
              </div>

              <p className="mt-3 text-sm muted">
                {STATUS_MEANING[found.status]}
              </p>

              <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="kicker">Submitted</dt>
                  <dd className="m-0">{formatDateTime(found.submittedAt)}</dd>
                </div>
                <div>
                  <dt className="kicker">Last updated</dt>
                  <dd className="m-0">{formatDateTime(found.updatedAt)}</dd>
                </div>
                <div>
                  <dt className="kicker">Handled by</dt>
                  <dd className="m-0">
                    {found.assignedDepartment ?? 'Not yet assigned'}
                  </dd>
                </div>
                <div>
                  <dt className="kicker">Attachments</dt>
                  <dd className="m-0">{found.attachments.length}</dd>
                </div>
              </dl>
            </section>

            <section className="card">
              <div className="card-head">
                <h2 className="card-title">Progress</h2>
              </div>
              <div className="card-pad">
                <ol className="timeline">
                  {VISIBLE_LIFECYCLE.map((status) => {
                    const reached =
                      VISIBLE_LIFECYCLE.indexOf(status) <=
                      VISIBLE_LIFECYCLE.indexOf(found.status)
                    const current = status === found.status
                    return (
                      <li key={status} data-current={current}>
                        <p
                          className={`m-0 text-sm font-bold ${reached ? '' : 'subtle'}`}
                        >
                          {status}
                          {current ? ' — current' : ''}
                        </p>
                      </li>
                    )
                  })}
                </ol>
                {!VISIBLE_LIFECYCLE.includes(found.status) ? (
                  <div className="mt-3">
                    <Callout
                      tone="warn"
                      title={`Current status: ${found.status}`}
                    >
                      {STATUS_MEANING[found.status]}
                    </Callout>
                  </div>
                ) : null}
              </div>
            </section>

            {found.resolution ? (
              <section className="card">
                <div className="card-head">
                  <h2 className="card-title">Approved response</h2>
                  <div className="text-xs muted">
                    Approved by {found.resolution.approver} ·{' '}
                    {formatDateTime(found.resolution.sentAt)}
                  </div>
                </div>
                <div className="card-pad">
                  <div className="draft-box">{found.resolution.text}</div>
                </div>
              </section>
            ) : (
              <Callout tone="info" title="Awaiting human approval">
                No response has been sent yet. A support administrator reviews
                the analysis and the policy evidence before anything is sent to
                you.
              </Callout>
            )}

            <section className="card">
              <div className="card-head">
                <h2 className="card-title">History</h2>
              </div>
              <ul className="m-0 list-none divide-rows p-0">
                {found.audit
                  .filter((event) => !HIDDEN_ACTIONS.includes(event.action))
                  .map((event) => (
                    <li key={event.id} className="px-4 py-2.5 text-sm">
                      <p className="m-0 font-semibold">{event.action}</p>
                      <p className="m-0 text-xs subtle">
                        {formatDateTime(event.at)}
                      </p>
                    </li>
                  ))}
              </ul>
            </section>
          </div>
        ) : null}
      </div>

      {!found ? (
        <p className="mt-6 text-sm muted">
          Do not have a reference yet?{' '}
          <Link to="/submit">Submit a grievance</Link>.
        </p>
      ) : null}
    </main>
  )
}
