import { useEffect, useState } from 'react'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import AuthPanel from '#/components/AuthPanel'
import PhotoCheck from '#/components/PhotoCheck'
import {
  AIStatusPill,
  BackendPriorityPill,
  BackendStatusPill,
  Callout,
  ErrorState,
  Field,
  LoadingState,
  SectionCard,
  Spinner,
  StatusSteps,
  WastePill,
} from '#/components/ui'
import {
  citizenWasteType,
  getComplaint,
  getMyComplaints,
  needsReview,
} from '#/lib/api'
import type { ComplaintResponse } from '#/lib/api'
import { signOut, useAuth } from '#/lib/auth'
import {
  formatCoordinates,
  mapsUrl,
  severityLabel,
} from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'
import { useApi } from '#/lib/use-api'

export const Route = createFileRoute('/track')({
  validateSearch: (search: Record<string, unknown>): { id?: string } =>
    typeof search.id === 'string' && search.id ? { id: search.id } : {},
  component: TrackPage,
})

function TrackPage() {
  const { id = '' } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { session, hydrated } = useAuth()
  const token = session?.accessToken
  const [query, setQuery] = useState(id)

  useEffect(() => setQuery(id), [id])

  const complaint = useApi(
    id && token ? (signal) => getComplaint(id.trim(), token, signal) : null,
    [id, token],
  )
  // GET /complaints/my scopes to the JWT, so a signed-in user never has to
  // remember a tracking reference to find their own cases.
  const mine = useApi(
    token ? (signal) => getMyComplaints(token, signal) : null,
    [token],
  )

  return (
    <main id="main" className="wrap page max-w-2xl">
      <p className="kicker">Live status</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
        Track a complaint
      </h1>
      <p className="mt-2 text-sm muted">
        Enter the reference you received, for example{' '}
        <span className="mono">TRK-a3f8b2c1</span>.
      </p>

      <div className="mt-5">
        <AuthPanel />
      </div>

      {hydrated && session ? (
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
            disabled={complaint.loading}
          >
            {complaint.loading ? <Spinner /> : null}
            {complaint.loading ? 'Checking…' : 'Check status'}
          </button>
        </form>
      ) : null}

      <div className="mt-6" aria-busy={complaint.loading}>
        {complaint.loading && !complaint.data ? (
          <LoadingState label="Requesting the current record…" />
        ) : null}

        {complaint.error && !complaint.loading ? (
          <ErrorState
            title="Complaint could not be loaded"
            message={complaint.error}
            onRetry={complaint.reload}
            onReauth={complaint.expired ? signOut : undefined}
          />
        ) : null}

        {complaint.data && token ? (
          <ComplaintCard
            item={complaint.data}
            token={token}
            // Owners and admins may upload; an assigned cleaner can read it but would get a 403.
            mayUpload={session.role !== 'cleaner'}
            onPhotoChange={() => {
              complaint.reload()
              mine.reload()
            }}
          />
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
              disabled={mine.loading}
              onClick={mine.reload}
            >
              {mine.loading ? <Spinner /> : null}
              {mine.loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>

          <div className="mt-3" aria-busy={mine.loading}>
            {mine.error ? (
              <ErrorState
                title="Your complaints could not be loaded"
                message={mine.error}
                onRetry={mine.reload}
                onReauth={mine.expired ? signOut : undefined}
              />
            ) : mine.loading && !mine.data ? (
              <LoadingState label="Loading your complaints…" />
            ) : mine.data && mine.data.length > 0 ? (
              <ul className="m-0 grid list-none gap-2 p-0">
                {mine.data.map((entry) => (
                  <li key={entry.tracking_id} className="min-w-0">
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
                        {citizenWasteType(entry) ? (
                          <WastePill wasteType={citizenWasteType(entry)} />
                        ) : null}
                        <AIStatusPill status={entry.ai_status} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-sm muted">
                You have not reported anything yet.{' '}
                <Link to="/submit">Report a waste problem</Link>.
              </p>
            )}
          </div>
        </section>
      ) : null}
    </main>
  )
}

function ComplaintCard({
  item,
  token,
  mayUpload,
  onPhotoChange,
}: {
  item: ComplaintResponse
  token: string
  mayUpload: boolean
  /** A photo was uploaded or its check finished: refetch the summaries. */
  onPhotoChange: () => void
}) {
  const map = mapsUrl(item.latitude, item.longitude)
  const coordinates = formatCoordinates(item.latitude, item.longitude)
  const status = item.status.toLowerCase()
  const closed = status === 'resolved' || status === 'closed'
  // Once a photo is analysed the response's waste_type is the AI's, not yours.
  const ownType = citizenWasteType(item)

  return (
    <div className="grid gap-4">
      <section className="card card-pad">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <span className="kicker">Tracking reference</span>
            <p className="mono mt-0.5 text-lg font-extrabold">
              {item.tracking_id}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <BackendStatusPill status={item.status} />
            <BackendPriorityPill priority={item.priority} />
          </div>
        </div>

        <div className="mt-5">
          <StatusSteps status={item.status} />
        </div>

        <dl className="mt-5 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="kicker">Submitted</dt>
            <dd className="m-0">{formatDateTime(item.created_at)}</dd>
          </div>
          <div>
            <dt className="kicker">Resolved</dt>
            <dd className="m-0">
              {item.resolved_at ? formatDateTime(item.resolved_at) : 'Not yet'}
            </dd>
          </div>
          <div>
            <dt className="kicker">Waste</dt>
            <dd className="m-0 flex flex-wrap items-center gap-1.5">
              {item.ai_status === null ? (
                <WastePill wasteType={ownType} />
              ) : (
                <span className="text-sm muted">
                  See the photo check{item.quantity_severity ? ' ·' : ''}
                </span>
              )}
              {item.quantity_severity ? (
                <span className="text-sm muted">
                  {severityLabel(item.quantity_severity)} amount
                </span>
              ) : null}
            </dd>
          </div>
          <div>
            <dt className="kicker">Cleaner visit</dt>
            <dd className="m-0">
              {item.intervention_required ? 'Needed' : 'Not requested'}
            </dd>
          </div>
          {item.department ? (
            <div className="sm:col-span-2">
              <dt className="kicker">Handled by</dt>
              <dd className="m-0 wrap-break-word">{item.department}</dd>
            </div>
          ) : null}
          <div className="sm:col-span-2">
            <dt className="kicker">Location</dt>
            <dd className="m-0">
              {item.address_text ?? (coordinates ? null : 'Not given')}
              {coordinates ? (
                <span className="block text-xs muted">
                  {coordinates}
                  {map ? (
                    <>
                      {' · '}
                      <a href={map} target="_blank" rel="noreferrer">
                        Open map
                      </a>
                    </>
                  ) : null}
                </span>
              ) : null}
            </dd>
          </div>
        </dl>
      </section>

      {needsReview(item) ? (
        <Callout tone="info" title="A staff member is reviewing this">
          The automatic check was not confident enough to route it alone, so a
          person is looking at it before anything is sent out.
        </Callout>
      ) : null}

      <SectionCard title="Your description">
        <p className="original-text m-0">{item.complaint_text}</p>
        {item.waste_context ? (
          <p className="mt-3 mb-0 text-sm muted">{item.waste_context}</p>
        ) : null}
      </SectionCard>

      <SectionCard title="Photo">
        <PhotoCheck
          trackingId={item.tracking_id}
          token={token}
          canUpload={!closed && mayUpload}
          onUploaded={onPhotoChange}
          onSettled={onPhotoChange}
        />
      </SectionCard>

      {item.recommended_action ? (
        <SectionCard title="Recommended action">
          <div className="draft-box">{item.recommended_action}</div>
        </SectionCard>
      ) : null}

      {status === 'closed' ? (
        <Callout tone="info" title="This complaint was closed">
          Staff closed this complaint. The tracking service does not share the
          reason yet.
        </Callout>
      ) : null}
    </div>
  )
}
