import { useEffect, useState } from 'react'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { Callout, Field, PriorityPill, StatusPill } from '#/components/ui'
import { getBackendImageUrl, getComplaint } from '#/lib/api'
import { formatDateTime } from '#/lib/format'
import { STATUS_MEANING } from '#/lib/taxonomy'
import type { Complaint } from '#/lib/types'

export const Route = createFileRoute('/track')({
  validateSearch: (search: Record<string, unknown>): { id?: string } =>
    typeof search.id === 'string' && search.id ? { id: search.id } : {},
  component: TrackPage,
})

function TrackPage() {
  const { id = '' } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const [query, setQuery] = useState(id)
  const [found, setFound] = useState<Complaint | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id.trim()) {
      setFound(null)
      setError(null)
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)

    getComplaint(id.trim())
      .then((complaint) => {
        setFound(complaint)
      })
      .catch((err: any) => {
        setFound(null)
        setError(err?.message || `No grievance found for reference ${id}`)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [id])

  return (
    <main id="main" className="wrap page max-w-2xl">
      <p className="kicker">Case status</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">Track a case</h1>
      <p className="mt-2 text-sm muted">
        Enter the reference or tracking ID from your acknowledgement, for example{' '}
        <span className="mono">1</span> or <span className="mono">TRK-a1b2c3d4</span>.
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
              placeholder="1 or TRK-a1b2c3d4"
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
        {loading ? (
          <div className="card card-pad text-center muted">
            <p className="m-0">Loading complaint status from backend...</p>
          </div>
        ) : null}

        {!loading && id && error ? (
          <Callout tone="warn" title="No case found">
            {error}
          </Callout>
        ) : null}

        {!loading && found ? (
          <div className="grid gap-4">
            <section className="card card-pad">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <span className="kicker">Reference</span>
                  <p className="mono mt-0.5 text-lg font-extrabold">
                    ID #{found.id}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <StatusPill status={found.status} />
                  <PriorityPill priority={found.priority} />
                </div>
              </div>

              <p className="mt-3 text-sm muted">
                {STATUS_MEANING[found.status] ?? `Status: ${found.status}`}
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
                  <dt className="kicker">Department</dt>
                  <dd className="m-0">
                    {found.assignedDepartment ?? 'Sanitation & Waste Management'}
                  </dd>
                </div>
                <div>
                  <dt className="kicker">Location</dt>
                  <dd className="m-0">
                    {found.location?.type === 'gps'
                      ? `GPS (${found.location.latitude?.toFixed(4)}, ${found.location.longitude?.toFixed(4)})`
                      : found.location?.type === 'manual'
                        ? found.location.manualAddress
                        : 'Not specified'}
                  </dd>
                </div>
              </dl>
            </section>

            <section className="card card-pad">
              <h2 className="card-title text-base font-bold">Complaint Details</h2>
              <p className="mt-2 text-sm text-(--fg)">{found.text}</p>

              {found.wasteType || found.severity ? (
                <div className="mt-4 grid grid-cols-2 gap-2 text-xs bg-(--surface-2) p-3 rounded-lg">
                  <div>
                    <span className="kicker">AI Waste Type</span>
                    <p className="font-semibold capitalize m-0">{found.wasteType ?? 'Unclassified'}</p>
                  </div>
                  <div>
                    <span className="kicker">Severity Level</span>
                    <p className="font-semibold capitalize m-0">{found.severity ?? 'Normal'}</p>
                  </div>
                </div>
              ) : null}

              {found.aiReasoning ? (
                <div className="mt-3 text-xs muted">
                  <span className="kicker">AI Analysis Note</span>
                  <p className="m-0 italic">{found.aiReasoning}</p>
                </div>
              ) : null}

              {found.imagePath ? (
                <div className="mt-4">
                  <span className="kicker">Submitted Image</span>
                  <div className="mt-1 max-w-sm rounded overflow-hidden border border-(--line)">
                    <img
                      src={getBackendImageUrl(found.imagePath) ?? undefined}
                      alt="Complaint waste evidence"
                      className="w-full h-auto max-h-64 object-cover"
                    />
                  </div>
                </div>
              ) : null}
            </section>
          </div>
        ) : null}
      </div>

      {!found && !loading ? (
        <p className="mt-6 text-sm muted">
          Do not have a reference yet?{' '}
          <Link to="/submit">Submit a grievance</Link>.
        </p>
      ) : null}
    </main>
  )
}
