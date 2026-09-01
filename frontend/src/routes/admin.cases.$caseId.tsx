import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
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
import {
  allowedApprovalStatuses,
  approveResponse,
  getAdminQueueItem,
} from '#/lib/api'
import type { AdminQueueItem, ApproveResponseResult } from '#/lib/api'
import { isExpiredSession, signOut, useAuth } from '#/lib/auth'
import {
  backendCategory,
  backendClassificationConfidence,
  backendEntityConfidence,
  backendEntityLabel,
  backendEvidenceLabel,
  backendEvidenceQuote,
  backendResolution,
  backendSuggestedDepartment,
  backendText,
} from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'

export const Route = createFileRoute('/admin/cases/$caseId')({
  component: CaseDetailPage,
})

const MAX_RESPONSE = 5000

function CaseDetailPage() {
  const { caseId } = Route.useParams()
  const { session } = useAuth()
  const accessToken = session?.accessToken
  const isAdmin = session?.role === 'admin'

  const [item, setItem] = useState<AdminQueueItem | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)

  const [responseText, setResponseText] = useState('')
  const [nextStatus, setNextStatus] = useState<'in_progress' | 'resolved'>(
    'in_progress',
  )
  const [approving, setApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [approveExpired, setApproveExpired] = useState(false)
  const [approved, setApproved] = useState<ApproveResponseResult | null>(null)
  const seededFor = useRef<string | null>(null)

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!accessToken || !isAdmin) return Promise.resolve()
      setLoading(true)
      setLoadError(null)
      return getAdminQueueItem(caseId, accessToken, signal)
        .then(setItem)
        .catch((caught: unknown) => {
          if (signal?.aborted) return
          setExpired(isExpiredSession(caught))
          setLoadError(
            caught instanceof Error
              ? caught.message
              : 'The complaint could not be loaded.',
          )
        })
        .finally(() => {
          if (!signal?.aborted) setLoading(false)
        })
    },
    [accessToken, caseId, isAdmin],
  )

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  // Everything transient belongs to one complaint; drop it when the route
  // points at a different one.
  useEffect(() => {
    seededFor.current = null
    setResponseText('')
    setApproved(null)
    setApproveError(null)
    setApproveExpired(false)
  }, [caseId])

  // Seed the editor from what the backend actually returned: the human-edited
  // draft first, then the AI draft, and nothing at all when generation produced
  // neither. Guarded by a ref so the post-approval refetch neither clobbers
  // text the admin has typed nor wipes the approval receipt.
  useEffect(() => {
    if (!item || seededFor.current === item.tracking_id) return
    seededFor.current = item.tracking_id
    setResponseText(item.edited_draft ?? backendText(item.ai_draft) ?? '')
  }, [item])

  // Keep the selector inside what the lifecycle allows for the current status.
  useEffect(() => {
    if (!item) return
    const targets = allowedApprovalStatuses(item.status)
    if (targets.length > 0 && !targets.includes(nextStatus)) {
      setNextStatus(targets[0])
    }
  }, [item, nextStatus])

  if (!session || !isAdmin || !accessToken) {
    return (
      <Callout tone="danger" title="Admin session required">
        Sign in with a backend admin account to view this complaint.
      </Callout>
    )
  }

  if (loading && !item) {
    return <LoadingState label="Loading this complaint from the admin queue…" />
  }

  if (loadError || !item) {
    return (
      <div className="grid gap-4">
        <ErrorState
          title="Complaint could not be loaded"
          message={loadError ?? 'Complaint not found.'}
          onRetry={() => void load()}
          onReauth={expired ? signOut : undefined}
        />
        <Link to="/admin" className="text-sm no-underline">
          ← Back to queue
        </Link>
      </div>
    )
  }

  const category = backendCategory(item.classification)
  const confidence = backendClassificationConfidence(item.classification)
  const suggestedDepartment = backendSuggestedDepartment(item.classification)
  const aiDraft = backendText(item.ai_draft)
  const resolution = backendResolution(item.resolution)
  const approvalTargets = allowedApprovalStatuses(item.status)
  const trimmedResponse = responseText.trim()

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to="/admin" className="text-sm no-underline">
          ← Back to queue
        </Link>
        <button
          type="button"
          className="btn btn-sm"
          disabled={loading}
          onClick={() => void load()}
        >
          {loading ? <Spinner /> : null}
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <header className="card card-pad" aria-busy={loading}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <span className="kicker">Backend tracking ID</span>
            <h2 className="mono mt-0.5 text-lg font-extrabold">
              {item.tracking_id}
            </h2>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <BackendStatusPill status={item.status} />
            <BackendPriorityPill priority={item.priority} />
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm lg:grid-cols-4">
          <div>
            <dt className="kicker">Requester</dt>
            <dd className="m-0">{item.name}</dd>
          </div>
          <div>
            <dt className="kicker">Contact</dt>
            <dd className="m-0 wrap-break-word">{item.email}</dd>
          </div>
          <div>
            <dt className="kicker">Submitted</dt>
            <dd className="m-0">{formatDateTime(item.created_at)}</dd>
          </div>
          <div>
            <dt className="kicker">Last updated</dt>
            <dd className="m-0">{formatDateTime(item.updated_at)}</dd>
          </div>
          <div>
            <dt className="kicker">Department</dt>
            <dd className="m-0">{item.department ?? 'Not assigned'}</dd>
          </div>
          <div>
            <dt className="kicker">Category</dt>
            <dd className="m-0">{category ?? 'Not returned'}</dd>
          </div>
          <div>
            <dt className="kicker">AI confidence</dt>
            <dd className="m-0">{confidence ?? 'Not returned'}</dd>
          </div>
          <div>
            <dt className="kicker">Channel · language</dt>
            <dd className="m-0">
              {item.channel} · {item.language}
            </dd>
          </div>
          {suggestedDepartment ? (
            <div>
              <dt className="kicker">Suggested routing</dt>
              <dd className="m-0">{suggestedDepartment}</dd>
            </div>
          ) : null}
          {item.duplicate_of ? (
            <div>
              <dt className="kicker">Duplicate of</dt>
              <dd className="m-0 mono">{item.duplicate_of}</dd>
            </div>
          ) : null}
          {item.closure_reason ? (
            <div className="col-span-2">
              <dt className="kicker">Closure reason</dt>
              <dd className="m-0">{item.closure_reason}</dd>
            </div>
          ) : null}
        </dl>
      </header>

      <SectionCard title="Original complaint" meta="complaint_text">
        <p className="original-text m-0">{item.complaint_text}</p>
      </SectionCard>

      <SectionCard title="Extracted entities" meta="entities">
        {item.entities.length > 0 ? (
          <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2">
            {item.entities.map((entity, index) => (
              <li
                key={`${backendEntityLabel(entity)}-${index}`}
                className="entity-row"
              >
                <span>{backendEntityLabel(entity)}</span>
                {backendEntityConfidence(entity) ? (
                  <span className="subtle">
                    {backendEntityConfidence(entity)}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-sm muted">
            The backend returned no extracted entities for this complaint.
          </p>
        )}
      </SectionCard>

      <SectionCard title="Retrieved policy evidence" meta="evidence">
        {item.evidence.length > 0 ? (
          <ul className="m-0 grid list-none gap-2 p-0">
            {item.evidence.map((entry, index) => (
              <li
                key={`${backendEvidenceLabel(entry)}-${index}`}
                className="evidence"
              >
                <strong className="block text-sm">
                  {backendEvidenceLabel(entry)}
                </strong>
                {backendEvidenceQuote(entry) ? (
                  <p className="evidence-quote m-0 mt-1">
                    {backendEvidenceQuote(entry)}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <Callout tone="warn" title="No policy evidence returned">
            Retrieval found nothing for this complaint, or the pipeline has not
            run. No substitute evidence is displayed.
          </Callout>
        )}
      </SectionCard>

      <SectionCard title="AI draft response" meta="ai_draft · edited_draft">
        {aiDraft ? (
          <div className="draft-box">{aiDraft}</div>
        ) : (
          <Callout tone="warn" title="No draft returned">
            The UI does not assume a successful AI run. This can mean low
            confidence, no retrieved policy, a generation failure, or a
            complaint the pipeline has not processed yet.
          </Callout>
        )}
        {item.edited_draft ? (
          <div className="mt-3">
            <span className="kicker">Human-edited draft</span>
            <div className="draft-box mt-1">{item.edited_draft}</div>
          </div>
        ) : null}
      </SectionCard>

      <SectionCard
        title="Approve a response"
        meta="POST /admin/responses/{id}/approve"
      >
        {approvalTargets.length === 0 ? (
          <Callout tone="warn" title="Approval is closed for this complaint">
            The backend lifecycle allows no further approval from status{' '}
            <span className="mono">{item.status}</span>.
          </Callout>
        ) : null}

        {approveError ? (
          <div className="mt-3">
            <ErrorState
              title="Approval failed"
              message={approveError}
              onReauth={approveExpired ? signOut : undefined}
            />
          </div>
        ) : null}

        {approved ? (
          <div className="mt-3">
            <Callout tone="ok" title="Saved by the backend">
              <span className="mono">{approved.tracking_id}</span> is now{' '}
              <span className="mono">{approved.status}</span>, approved by{' '}
              {approved.approved_by} on {formatDateTime(approved.approved_at)}.
            </Callout>
          </div>
        ) : null}

        <form
          className="mt-4 grid gap-3"
          onSubmit={async (event) => {
            event.preventDefault()
            if (approvalTargets.length === 0) return
            if (!trimmedResponse) {
              setApproveError('Enter the response text before approving.')
              return
            }

            setApproving(true)
            setApproveError(null)
            setApproved(null)
            try {
              const result = await approveResponse(
                item.tracking_id,
                { text: trimmedResponse, next_status: nextStatus },
                accessToken,
              )
              setApproved(result)
              // The approval result is authoritative, but it carries only part
              // of the record, so the full item is re-read from the backend
              // rather than patched locally.
              await load()
            } catch (caught) {
              setApproveExpired(isExpiredSession(caught))
              setApproveError(
                caught instanceof Error
                  ? caught.message
                  : 'The response could not be approved.',
              )
            } finally {
              setApproving(false)
            }
          }}
        >
          <Field
            label="Response sent to the complainant"
            htmlFor="approve-text"
            required
            hint={`${trimmedResponse.length} of ${MAX_RESPONSE} characters. This exact text is stored by the backend.`}
          >
            <textarea
              id="approve-text"
              className="textarea"
              maxLength={MAX_RESPONSE}
              required
              value={responseText}
              disabled={approving || approvalTargets.length === 0}
              placeholder="Write or edit the reply a named human approves."
              onChange={(event) => setResponseText(event.target.value)}
            />
          </Field>

          <div className="grid gap-3 sm:grid-cols-[minmax(0,16rem)_auto] sm:items-end">
            <Field label="Next status" htmlFor="approve-status" required>
              <select
                id="approve-status"
                className="select"
                value={nextStatus}
                disabled={approving || approvalTargets.length === 0}
                onChange={(event) =>
                  setNextStatus(
                    event.target.value as 'in_progress' | 'resolved',
                  )
                }
              >
                {approvalTargets.map((target) => (
                  <option key={target} value={target}>
                    {target.replaceAll('_', ' ')}
                  </option>
                ))}
              </select>
            </Field>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={
                approving ||
                approvalTargets.length === 0 ||
                trimmedResponse.length === 0
              }
            >
              {approving ? <Spinner /> : null}
              {approving ? 'Approving…' : 'Approve and save'}
            </button>
          </div>
        </form>
      </SectionCard>

      <SectionCard title="Approved response on record" meta="resolution">
        {resolution ? (
          <>
            <div className="draft-box">{resolution.text}</div>
            <p className="mt-2 text-xs muted">
              Approved by {resolution.approver ?? 'an unnamed admin'}
              {resolution.sentAt
                ? ` on ${formatDateTime(resolution.sentAt)}`
                : ''}
              .
            </p>
          </>
        ) : (
          <p className="m-0 text-sm muted">
            The backend holds no approved response for this complaint yet.
          </p>
        )}
      </SectionCard>

      <Callout tone="warn" title="Two admin actions still lack a contract">
        <span className="mono">PUT /admin/complaints/{'{complaint_id}'}</span>{' '}
        needs the numeric database ID, which no response model exposes, so
        priority and department cannot be edited here. There is also no reject
        or close endpoint, and nothing writes{' '}
        <span className="mono">closure_reason</span>. Both need a backend change
        rather than a browser-side workaround.
      </Callout>
    </div>
  )
}
