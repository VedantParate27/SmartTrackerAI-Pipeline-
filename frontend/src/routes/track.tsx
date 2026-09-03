import { useEffect, useState } from 'react'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import AuthPanel from '#/components/AuthPanel'
import {
  BackendPriorityPill,
  BackendStatusPill,
  Callout,
  ErrorState,
  Field,
  LoadingState,
  SectionCard,
  Spinner,
} from '#/components/ui'
import { getComplaint, getMyComplaints } from '#/lib/api'
import type { ComplaintResponse } from '#/lib/api'
import { isExpiredSession, signOut, useAuth } from '#/lib/auth'
import { formatDateTime } from '#/lib/format'

export const Route = createFileRoute('/track')({
  validateSearch: (search: Record<string, unknown>): { id?: string } =>
    typeof search.id === 'string' && search.id ? { id: search.id } : {},
  component: TrackPage,
})

function TrackPage() {
  const { id = '' } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { session, hydrated } = useAuth()
  const [query, setQuery] = useState(id)
  const [complaint, setComplaint] = useState<ComplaintResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [reload, setReload] = useState(0)
  const [mine, setMine] = useState<ComplaintResponse[] | null>(null)
  const [mineLoading, setMineLoading] = useState(false)
  const [mineError, setMineError] = useState<string | null>(null)

  useEffect(() => setQuery(id), [id])

  // GET /complaints/my scopes to the JWT, so a signed-in user never has to
  // remember a tracking reference to find their own cases.
  useEffect(() => {
    if (!session) {
      setMine(null)
      setMineError(null)
      return
    }
    const controller = new AbortController()
    setMineLoading(true)
    setMineError(null)
    getMyComplaints(session.accessToken, controller.signal)
      .then(setMine)
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setMine(null)
        if (isExpiredSession(caught)) setExpired(true)
        setMineError(
          caught instanceof Error
            ? caught.message
            : 'Your complaints could not be loaded.',
        )
      })
      .finally(() => {
        if (!controller.signal.aborted) setMineLoading(false)
      })
    return () => controller.abort()
  }, [session, reload])

  useEffect(() => {
    if (!id || !session) {
      setComplaint(null)
      setError(null)
      setLoading(false)
      return
    }

    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getComplaint(id.trim(), session.accessToken, controller.signal)
      .then(setComplaint)
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setComplaint(null)
        setExpired(isExpiredSession(caught))
        setError(
          caught instanceof Error
            ? caught.message
            : 'The complaint could not be loaded.',
        )
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [id, session, reload])

  return (
    <main id="main" className="wrap page max-w-2xl">
      <p className="kicker">Live case status</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">Track a case</h1>
      <p className="mt-2 text-sm muted">
        Enter the exact <span className="mono">tracking_id</span> returned by
        FastAPI, for example <span className="mono">TRK-a3f8b2c1</span>.
      </p>

      {!hydrated || !session ? (
        <div className="mt-5">
          <AuthPanel />
        </div>
      ) : (
        <>
          <div className="mt-4">
            <AuthPanel />
          </div>
          <form
            className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault()
              void navigate({ search: { id: query.trim() } })
            }}
          >
            <div className="flex-1">
              <Field label="Tracking reference" htmlFor="track-id" required>
                <input
                  id="track-id"
                  className="input"
                  value={query}
                  placeholder="TRK-a3f8b2c1"
                  autoComplete="off"
                  spellCheck={false}
                  required
                  onChange={(event) => setQuery(event.target.value)}
                />
              </Field>
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
            >
              {loading ? <Spinner /> : null}
              {loading ? 'Checking…' : 'Check status'}
            </button>
          </form>
        </>
      )}

      <div className="mt-6" aria-live="polite" aria-busy={loading}>
        {loading ? (
          <LoadingState label="Requesting the current record from FastAPI…" />
        ) : null}

        {error && !loading ? (
          <ErrorState
            title="Complaint could not be loaded"
            message={error}
            onRetry={() => setReload((n) => n + 1)}
            onReauth={expired ? signOut : undefined}
          />
        ) : null}

        {complaint && !loading ? (
          <div className="grid gap-4">
            <section className="card card-pad">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <span className="kicker">Tracking reference</span>
                  <p className="mono mt-0.5 text-lg font-extrabold">
                    {complaint.tracking_id}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <BackendStatusPill status={complaint.status} />
                  <BackendPriorityPill priority={complaint.priority} />
                </div>
              </div>

              <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="kicker">Created</dt>
                  <dd className="m-0">
                    {formatDateTime(complaint.created_at)}
                  </dd>
                </div>
                <div>
                  <dt className="kicker">Department</dt>
                  <dd className="m-0">
                    {complaint.department ?? 'Not yet assigned'}
                  </dd>
                </div>
              </dl>
            </section>

            <SectionCard title="Original complaint">
              <p className="original-text m-0">{complaint.complaint_text}</p>
            </SectionCard>

            <Callout tone="info" title="Approved replies are not on this route">
              An admin approval is stored by{' '}
              <span className="mono">
                POST /admin/responses/{'{id}'}/approve
              </span>
              , but{' '}
              <span className="mono">GET /complaints/{'{tracking_id}'}</span>{' '}
              returns only the six fields above. The reply text is withheld here
              rather than guessed; exposing it to the complainant needs a
              backend field.
            </Callout>
          </div>
        ) : null}
      </div>

      {session ? (
        <section className="mt-8" aria-labelledby="mine-heading">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="mine-heading" className="text-base font-extrabold">
              Your complaints
            </h2>
            <button
              type="button"
              className="btn btn-sm"
              disabled={mineLoading}
              onClick={() => setReload((n) => n + 1)}
            >
              {mineLoading ? <Spinner /> : null}
              {mineLoading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>

          <div className="mt-3" aria-busy={mineLoading}>
            {mineError ? (
              <ErrorState
                title="Your complaints could not be loaded"
                message={mineError}
                onRetry={() => setReload((n) => n + 1)}
                onReauth={expired ? signOut : undefined}
              />
            ) : mineLoading && !mine ? (
              <LoadingState label="Loading your complaints…" />
            ) : mine && mine.length > 0 ? (
              <ul className="m-0 grid list-none gap-2 p-0">
                {mine.map((entry) => (
                  <li key={entry.tracking_id}>
                    <Link
                      to="/track"
                      search={{ id: entry.tracking_id }}
                      className="card card-pad flex flex-wrap items-center justify-between gap-2 no-underline"
                    >
                      <span className="min-w-0">
                        <span className="mono block font-bold text-(--fg)">
                          {entry.tracking_id}
                        </span>
                        <span className="mt-0.5 block truncate text-xs muted">
                          {entry.complaint_text}
                        </span>
                      </span>
                      <span className="flex shrink-0 flex-wrap gap-1.5">
                        <BackendStatusPill status={entry.status} />
                        <BackendPriorityPill priority={entry.priority} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-sm muted">
                You have not submitted any complaints yet.{' '}
                <Link to="/submit">Submit a grievance</Link>.
              </p>
            )}
          </div>
        </section>
      ) : null}
    </main>
  )
}
