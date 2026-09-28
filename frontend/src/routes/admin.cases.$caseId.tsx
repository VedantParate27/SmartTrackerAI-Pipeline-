import { useMemo } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { AiSuggestion, CorrectionHistory } from '#/components/case/AiSuggestion'
import CaseTimeline from '#/components/case/CaseTimeline'
import DecisionPanel from '#/components/case/DecisionPanel'
import TaskPanel from '#/components/case/TaskPanel'
import type { Assignee } from '#/components/case/TaskPanel'
import {
  BackendPriorityPill,
  BackendStatusPill,
  Callout,
  ErrorState,
  LoadingState,
  ReviewPill,
  SectionCard,
  Spinner,
  WastePill,
} from '#/components/ui'
import {
  findTaskForComplaint,
  getAIOutputs,
  getAdminQueueItem,
  getCorrections,
  getEvents,
  getKnownCleaners,
  resolveComplaintId,
} from '#/lib/api'
import { signOut, useAuth } from '#/lib/auth'
import {
  formatCoordinates,
  mapsUrl,
  severityLabel,
  triageModeLabel,
} from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'
import { useApi } from '#/lib/use-api'

export const Route = createFileRoute('/admin/cases/$caseId')({
  component: CaseDetailPage,
})

function CaseDetailPage() {
  const { caseId } = Route.useParams()
  const { session } = useAuth()
  const token = session?.role === 'admin' ? session.accessToken : undefined

  const item = useApi(
    token ? (signal) => getAdminQueueItem(caseId, token, signal) : null,
    [caseId, token],
  )
  const complaintId = useApi(
    token ? (signal) => resolveComplaintId(caseId, token, signal) : null,
    [caseId, token],
  )
  const cid = complaintId.data
  const ai = useApi(
    token && cid !== null ? (signal) => getAIOutputs(cid, token, signal) : null,
    [cid, token],
  )
  const corrections = useApi(
    token && cid !== null
      ? (signal) => getCorrections(cid, token, signal)
      : null,
    [cid, token],
  )
  const task = useApi(
    token ? (signal) => findTaskForComplaint(caseId, token, signal) : null,
    [caseId, token],
  )
  const events = useApi(
    token
      ? (signal) => getEvents({ case_id: caseId, limit: 500 }, token, signal)
      : null,
    [caseId, token],
  )
  const cleaners = useApi(
    token ? (signal) => getKnownCleaners(token, signal) : null,
    [token],
  )

  const knownCleaners = useMemo(() => cleaners.data ?? [], [cleaners.data])

  // The latest assignment event is the only record of who holds the task:
  // CleanerTaskResponse carries no cleaner id.
  const assignee = useMemo<Assignee | null>(() => {
    const latest = events.data?.find((event) =>
      ['cleaner_assigned', 'cleaner_reassigned'].includes(event.activity),
    )
    const id = Number(latest?.new_value)
    if (!latest || !Number.isInteger(id)) return null
    const fromEvent = latest.meta?.cleaner_name
    return {
      id,
      name:
        typeof fromEvent === 'string'
          ? fromEvent
          : (knownCleaners.find((cleaner) => cleaner.id === id)?.name ?? null),
    }
  }, [events.data, knownCleaners])

  function refreshAll() {
    item.reload()
    ai.reload()
    corrections.reload()
    task.reload()
    events.reload()
    cleaners.reload()
  }

  if (!token) {
    return (
      <Callout tone="danger" title="Admin session required">
        Sign in with a backend admin account to view this complaint.
      </Callout>
    )
  }

  if (item.loading && !item.data) {
    return <LoadingState label="Loading this complaint…" />
  }

  if (item.error || !item.data) {
    return (
      <div className="grid gap-4">
        <ErrorState
          title="Complaint could not be loaded"
          message={item.error ?? 'Complaint not found.'}
          onRetry={item.reload}
          onReauth={item.expired ? signOut : undefined}
        />
        <Link to="/admin" className="text-sm no-underline">
          ← Back to queue
        </Link>
      </div>
    )
  }

  const complaint = item.data
  const latestAi = ai.data?.at(-1) ?? null
  // Wait for the prediction before seeding the form, unless it can't load.
  const aiSettled =
    ai.data !== null || ai.error !== null || complaintId.error !== null
  const map = mapsUrl(complaint.latitude, complaint.longitude)
  const coordinates = formatCoordinates(complaint.latitude, complaint.longitude)
  const busy = item.loading || task.loading || events.loading

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to="/admin" className="text-sm no-underline">
          ← Back to queue
        </Link>
        <button
          type="button"
          className="btn btn-sm"
          disabled={busy}
          onClick={refreshAll}
        >
          {busy ? <Spinner /> : null}
          {busy ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <header className="card card-pad" aria-busy={item.loading}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <span className="kicker">Tracking reference</span>
            <h2 className="mono mt-0.5 text-lg font-extrabold">
              {complaint.tracking_id}
            </h2>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <BackendStatusPill status={complaint.status} />
            <BackendPriorityPill priority={complaint.priority} />
            <ReviewPill
              required={complaint.review_required}
              reason={complaint.review_reason}
            />
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm lg:grid-cols-4">
          <div>
            <dt className="kicker">Requester</dt>
            <dd className="m-0">{complaint.name}</dd>
          </div>
          <div>
            <dt className="kicker">Contact</dt>
            <dd className="m-0 wrap-break-word">{complaint.email}</dd>
          </div>
          <div>
            <dt className="kicker">Submitted</dt>
            <dd className="m-0">{formatDateTime(complaint.created_at)}</dd>
          </div>
          <div>
            <dt className="kicker">Last updated</dt>
            <dd className="m-0">{formatDateTime(complaint.updated_at)}</dd>
          </div>
          <div>
            <dt className="kicker">Waste</dt>
            <dd className="m-0 flex flex-wrap items-center gap-1.5">
              <WastePill wasteType={complaint.waste_type} />
              {complaint.quantity_severity ? (
                <span className="text-xs muted">
                  {severityLabel(complaint.quantity_severity)}
                </span>
              ) : null}
            </dd>
          </div>
          <div>
            <dt className="kicker">Cleaner needed</dt>
            <dd className="m-0">
              {complaint.intervention_required ? 'Yes' : 'No'}
            </dd>
          </div>
          <div>
            <dt className="kicker">Triage</dt>
            <dd className="m-0">{triageModeLabel(complaint.triage_mode)}</dd>
          </div>
          <div>
            <dt className="kicker">Location</dt>
            <dd className="m-0">
              {complaint.address_text ?? (coordinates ? null : 'Not given')}
              {coordinates ? (
                <span className="block text-xs muted">
                  {map ? (
                    <a href={map} target="_blank" rel="noreferrer">
                      {coordinates}
                    </a>
                  ) : (
                    coordinates
                  )}
                </span>
              ) : null}
            </dd>
          </div>
        </dl>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="grid content-start gap-4">
          <SectionCard title="Complaint" meta="complaint_text">
            <p className="original-text m-0">{complaint.complaint_text}</p>
            {complaint.waste_context ? (
              <p className="mt-3 mb-0 text-sm muted">
                <strong>Context:</strong> {complaint.waste_context}
              </p>
            ) : null}
          </SectionCard>

          {complaintId.error ? null : ai.error ? (
            <SectionCard title="AI suggestion">
              <ErrorState
                title="AI output could not be loaded"
                message={ai.error}
                onRetry={ai.reload}
              />
            </SectionCard>
          ) : ai.data ? (
            <AiSuggestion outputs={ai.data} />
          ) : (
            <SectionCard title="AI suggestion">
              <LoadingState label="Loading the AI prediction…" />
            </SectionCard>
          )}

          {aiSettled ? (
            <DecisionPanel
              key={`${complaint.tracking_id}:${latestAi?.id ?? 'none'}`}
              item={complaint}
              complaintId={cid}
              idError={complaintId.error}
              onRetryId={complaintId.reload}
              latest={latestAi}
              cleaners={knownCleaners}
              token={token}
              onSaved={refreshAll}
            />
          ) : (
            <SectionCard title="Decision">
              <LoadingState label="Preparing the decision form…" />
            </SectionCard>
          )}

          <TaskPanel
            complaintStatus={complaint.status}
            complaintId={cid}
            task={task.data}
            loading={task.loading}
            error={task.error}
            onRetry={task.reload}
            assignee={assignee}
            cleaners={knownCleaners}
            token={token}
            onChanged={refreshAll}
          />
        </div>

        <aside className="grid content-start gap-4">
          <SectionCard title="Case history" meta="event_log">
            {events.error ? (
              <ErrorState
                title="History unavailable"
                message={events.error}
                onRetry={events.reload}
              />
            ) : events.data ? (
              <CaseTimeline events={events.data} />
            ) : (
              <LoadingState label="Loading events…" />
            )}
          </SectionCard>

          <SectionCard title="AI accept / correct" meta="ai_corrections">
            {corrections.error ? (
              <ErrorState
                title="Corrections unavailable"
                message={corrections.error}
                onRetry={corrections.reload}
              />
            ) : corrections.data ? (
              <CorrectionHistory corrections={corrections.data} />
            ) : complaintId.error ? (
              <p className="m-0 text-sm muted">
                Needs the internal complaint id, which could not be resolved.
              </p>
            ) : (
              <LoadingState label="Loading…" />
            )}
          </SectionCard>
        </aside>
      </div>
    </div>
  )
}
