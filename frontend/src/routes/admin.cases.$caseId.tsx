import { useCallback, useMemo } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { AiSuggestion, CorrectionHistory } from '#/components/case/AiSuggestion'
import CaseTimeline from '#/components/case/CaseTimeline'
import DecisionPanel from '#/components/case/DecisionPanel'
import DetailsPanel from '#/components/case/DetailsPanel'
import PhotoAiPanel from '#/components/case/PhotoAiPanel'
import TaskPanel from '#/components/case/TaskPanel'
import {
  AIStatusPill,
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
  aiRunLost,
  findTaskForComplaint,
  getAIOutputs,
  getAIReview,
  getAdminQueueItem,
  getCorrections,
  getEvents,
  getKnownCleaners,
  getTaskProofReview,
  needsReview,
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
import { useApi, usePolling } from '#/lib/use-api'

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

  // The photo analysis runs in the background; poll until it settles.
  const aiReview = useApi(
    token && cid !== null ? (signal) => getAIReview(cid, token, signal) : null,
    [cid, token],
  )
  const analysis = aiReview.data?.analysis ?? null
  const analysisLost =
    analysis?.ai_status === 'pending' && aiRunLost(analysis.created_at)
  const reviewStalled = usePolling(
    analysis?.ai_status === 'pending' && !analysisLost,
    aiReview.reload,
    { busy: aiReview.loading, runKey: analysis?.id ?? null },
  )

  const textAi = useApi(
    token && cid !== null ? (signal) => getAIOutputs(cid, token, signal) : null,
    [cid, token],
  )
  const corrections = useApi(
    token && cid !== null
      ? (signal) => getCorrections(cid, token, signal)
      : null,
    [cid, token],
  )

  // /cleaner/tasks finds the task; the admin proof review then supplies the
  // cleaner (null until picked), the before photos and the AI comparison.
  const task = useApi(
    token ? (signal) => findTaskForComplaint(caseId, token, signal) : null,
    [caseId, token],
  )
  const taskId = task.data?.task_id ?? null
  const taskReview = useApi(
    token && taskId
      ? (signal) => getTaskProofReview(taskId, token, signal)
      : null,
    [taskId, token],
  )
  // The newest proof whose before/after comparison is still running.
  const comparing =
    taskReview.data?.proofs
      .filter(
        (proof) =>
          proof.verification_status === 'pending_verification' &&
          proof.ai_processed_at === null &&
          !aiRunLost(proof.uploaded_at),
      )
      .at(-1) ?? null
  const proofStalled = usePolling(comparing !== null, taskReview.reload, {
    busy: taskReview.loading,
    runKey: comparing?.id ?? null,
  })

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

  // Assignment events are the only place cleaner names are recorded.
  const cleanerName = useCallback(
    (id: number) => {
      for (const event of events.data ?? []) {
        if (
          (event.activity === 'cleaner_assigned' ||
            event.activity === 'cleaner_reassigned') &&
          Number(event.new_value) === id &&
          typeof event.meta?.cleaner_name === 'string'
        ) {
          return event.meta.cleaner_name
        }
      }
      return knownCleaners.find((cleaner) => cleaner.id === id)?.name ?? null
    },
    [events.data, knownCleaners],
  )

  function refreshAll() {
    item.reload()
    aiReview.reload()
    textAi.reload()
    corrections.reload()
    task.reload()
    taskReview.reload()
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

  if (!item.data) {
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
  const map = mapsUrl(complaint.latitude, complaint.longitude)
  const coordinates = formatCoordinates(complaint.latitude, complaint.longitude)
  const busy = item.loading || task.loading || events.loading
  // Unknown until /cleaner/tasks answers; DecisionPanel won't offer assign_cleaner then.
  const hasTask =
    task.data !== null ? true : task.loading || task.error ? null : false

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

      {item.error ? (
        <ErrorState
          title="This complaint could not be refreshed"
          message={item.error}
          onRetry={item.reload}
          onReauth={item.expired ? signOut : undefined}
        />
      ) : null}

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
              required={needsReview(complaint)}
              reason={complaint.review_reason}
            />
            <AIStatusPill
              status={analysis?.ai_status ?? null}
              usable={analysis?.image_usable}
              lost={analysisLost}
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
            <dt className="kicker">Waste (complaint)</dt>
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
            <dt className="kicker">Text-AI triage</dt>
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

          <PhotoAiPanel
            review={aiReview.data}
            loading={aiReview.loading || (cid === null && !complaintId.error)}
            error={aiReview.error}
            onRetry={aiReview.reload}
            stalled={reviewStalled}
            needsId={complaintId.error !== null}
            trackingId={complaint.tracking_id}
            token={token}
            canUpload={
              complaint.status === 'pending' ||
              complaint.status === 'in_progress'
            }
            onUploaded={aiReview.reload}
          />

          {textAi.error ? (
            <SectionCard title="Text-AI triage">
              <ErrorState
                title="Text-AI output could not be loaded"
                message={textAi.error}
                onRetry={textAi.reload}
              />
            </SectionCard>
          ) : textAi.data ? (
            <AiSuggestion outputs={textAi.data} />
          ) : null}

          <DecisionPanel
            item={complaint}
            complaintId={cid}
            idError={complaintId.error}
            onRetryId={complaintId.reload}
            hasTask={hasTask}
            analysis={analysis}
            events={events.data ?? []}
            cleaners={knownCleaners}
            token={token}
            onSaved={refreshAll}
          />

          <TaskPanel
            complaintStatus={complaint.status}
            complaintId={cid}
            task={task.data}
            review={taskReview.data}
            loading={task.loading}
            error={task.error ?? taskReview.error}
            onRetry={() => {
              task.reload()
              taskReview.reload()
            }}
            cleanerName={cleanerName}
            cleaners={knownCleaners}
            token={token}
            onChanged={refreshAll}
            aiStalled={proofStalled}
          />
        </div>

        <aside className="grid content-start gap-4">
          <DetailsPanel
            item={complaint}
            complaintId={cid}
            hasTask={task.data !== null}
            token={token}
            onSaved={refreshAll}
          />

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

          {corrections.error ? (
            <SectionCard title="Text-AI accept / correct">
              <ErrorState
                title="Corrections unavailable"
                message={corrections.error}
                onRetry={corrections.reload}
              />
            </SectionCard>
          ) : corrections.data && corrections.data.length > 0 ? (
            <SectionCard title="Text-AI accept / correct" meta="ai_corrections">
              <CorrectionHistory corrections={corrections.data} />
            </SectionCard>
          ) : null}
        </aside>
      </div>
    </div>
  )
}
