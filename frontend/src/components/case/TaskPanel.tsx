import { useState } from 'react'
import CleanerPicker, { parseCleanerId } from './CleanerPicker'
import type { KnownCleaner } from './CleanerPicker'
import { AiErrorList } from './PhotoAiPanel'
import {
  BackendPhoto,
  Callout,
  ConfidenceMeter,
  ErrorState,
  Field,
  LoadingState,
  ProofStatusPill,
  SectionCard,
  Spinner,
  TaskStatusPill,
} from '#/components/ui'
import {
  aiRunLost,
  assignCleaner,
  backendFileUrl,
  verifyProof,
} from '#/lib/api'
import type { AdminProofReview, CleanerTask, ProofReviewItem } from '#/lib/api'
import { isExpiredSession, signOut } from '#/lib/auth'
import { formatDateTime } from '#/lib/format'

/**
 * Field execution for a dispatched case: who holds the task, every proof with
 * its before/after photos and advisory AI comparison, and the admin's
 * verify/reject on each. A rejection sends the task back to the cleaner — the
 * resubmission loop process mining measures.
 */
export default function TaskPanel({
  complaintStatus,
  complaintId,
  task,
  review,
  loading,
  error,
  onRetry,
  cleanerName,
  cleaners,
  token,
  onChanged,
  aiStalled,
}: {
  complaintStatus: string
  complaintId: number | null
  /** From /cleaner/tasks: existence, id and the admin's instructions. */
  task: CleanerTask | null
  /** From /admin/tasks/{id}/proof: cleaner, proofs and AI comparison. */
  review: AdminProofReview | null
  loading: boolean
  error: string | null
  onRetry: () => void
  cleanerName: (id: number) => string | null
  cleaners: KnownCleaner[]
  token: string
  onChanged: () => void
  aiStalled: boolean
}) {
  const status = complaintStatus.toLowerCase()
  // Keep the proofs, and anything typed into them, when only a refresh failed.
  const refreshError = error && task && review ? error : null

  if (error && !refreshError) {
    return (
      <SectionCard title="Cleanup task">
        <ErrorState
          title="The task could not be loaded"
          message={error}
          onRetry={onRetry}
        />
      </SectionCard>
    )
  }

  if (loading && !task) {
    return (
      <SectionCard title="Cleanup task">
        <LoadingState label="Looking up the cleanup task…" />
      </SectionCard>
    )
  }

  if (!task) {
    return (
      <SectionCard title="Cleanup task">
        {status === 'in_progress' ? (
          <div className="grid gap-3">
            <Callout tone="warn" title="In progress, but there is no task">
              Assign a cleaner to create the task and put it in their list.
            </Callout>
            <AssignForm
              complaintId={complaintId}
              cleaners={cleaners}
              token={token}
              onDone={onChanged}
              submitLabel="Assign cleaner"
            />
          </div>
        ) : status === 'pending' ? (
          <p className="m-0 text-sm muted">
            Choose <strong>Assign a cleaner</strong> in the decision panel to
            create a cleanup task.
          </p>
        ) : (
          <p className="m-0 text-sm muted">
            No cleanup task — this case ended without a field visit.
          </p>
        )}
      </SectionCard>
    )
  }

  if (!review) {
    return (
      <SectionCard
        title="Cleanup task"
        meta={<span className="mono">{task.task_id}</span>}
      >
        <LoadingState label="Loading the proof history…" />
      </SectionCard>
    )
  }

  const cleanerId = review.task_assigned_cleaner_id
  const proofs = [...review.proofs].reverse()
  const finished = review.task_status === 'verified'
  // Assigning moves the complaint to in_progress, which a resolved or closed
  // case can no longer reach (VALID_TRANSITIONS).
  const open = status === 'pending' || status === 'in_progress'

  return (
    <SectionCard
      title="Cleanup task"
      meta={<span className="mono">{review.task_id}</span>}
    >
      <div className="grid gap-4">
        {refreshError ? (
          <ErrorState
            title="The task could not be refreshed"
            message={refreshError}
            onRetry={onRetry}
          />
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <TaskStatusPill status={review.task_status} />
          <span className="text-sm muted">
            {cleanerId === null
              ? 'No cleaner yet'
              : `Assigned to ${cleanerName(cleanerId) ?? `cleaner #${cleanerId}`}`}{' '}
            · {formatDateTime(review.assigned_at)}
          </span>
        </div>

        {cleanerId === null && open ? (
          <div className="grid gap-3">
            <Callout tone="warn" title="Waiting for a cleaner">
              The task exists but nobody is on it, so it is in no cleaner's list
              yet.
            </Callout>
            <AssignForm
              complaintId={complaintId}
              cleaners={cleaners}
              token={token}
              onDone={onChanged}
              submitLabel="Assign cleaner"
            />
          </div>
        ) : cleanerId === null ? (
          <p className="m-0 text-sm muted">
            No cleaner was assigned before this case ended.
          </p>
        ) : null}

        {review.completed_at ? (
          <p className="m-0 text-sm muted">
            Completed {formatDateTime(review.completed_at)}
          </p>
        ) : null}

        {task.notes ? (
          <div>
            <span className="kicker">Instructions</span>
            <p className="mt-1 mb-0 text-sm">{task.notes}</p>
          </div>
        ) : null}

        {cleanerId !== null ? (
          <div>
            <span className="kicker">Proof photos</span>
            {proofs.length === 0 ? (
              <p className="mt-1 mb-0 text-sm muted">
                Waiting for the cleaner to upload a photo of the cleaned spot.
              </p>
            ) : (
              <ul className="mt-2 grid list-none gap-3 p-0">
                {proofs.map((proof) => (
                  <li key={proof.id}>
                    <ProofCard
                      proof={proof}
                      token={token}
                      complaintStatus={status}
                      onDone={onChanged}
                      aiStalled={aiStalled}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {cleanerId !== null && !finished && open ? (
          <details className="card card-pad">
            <summary className="cursor-pointer text-sm font-bold">
              Reassign to another cleaner
            </summary>
            <div className="mt-3">
              <AssignForm
                complaintId={complaintId}
                cleaners={cleaners}
                token={token}
                onDone={onChanged}
                submitLabel="Reassign"
              />
            </div>
          </details>
        ) : null}
      </div>
    </SectionCard>
  )
}

/**
 * The background before/after comparison. Advisory: it never approves or
 * rejects — and it is drawn on a dashed surface so it never reads as one.
 */
function AiVerdict({
  proof,
  stalled,
}: {
  proof: ProofReviewItem
  stalled: boolean
}) {
  const errors = proof.ai_errors ?? []

  if (proof.ai_processed_at === null) {
    // Only an undecided proof is still waiting on the comparison.
    if (proof.verification_status !== 'pending_verification') return null
    if (aiRunLost(proof.uploaded_at)) {
      return (
        <p className="m-0 text-xs muted">
          No AI comparison was recorded for this photo — check it by eye.
        </p>
      )
    }
    return (
      <p className="m-0 flex items-center gap-2 text-xs muted">
        <Spinner />
        {stalled
          ? 'The AI comparison is still running. Refresh later.'
          : 'The AI is comparing the before and after photos…'}
      </p>
    )
  }

  if (errors.length > 0) {
    return (
      <div className="ai-note">
        <span className="kicker">AI comparison unavailable</span>
        <div className="mt-1">
          <AiErrorList errors={errors} />
        </div>
      </div>
    )
  }

  if (proof.ai_after_image_usable === false) {
    return (
      <div className="ai-note">
        <span className="kicker">AI comparison</span>
        <p className="mt-1 mb-0">
          The after photo was not usable
          {proof.ai_unusable_reason ? `: ${proof.ai_unusable_reason}` : ''}.
        </p>
      </div>
    )
  }

  const complete = proof.ai_cleanup_appears_complete
  return (
    <div className="ai-note grid gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="kicker">AI comparison</span>
        {proof.ai_admin_review_recommended ? (
          <span className="pill" data-tone="warn">
            Look closely
          </span>
        ) : null}
      </div>
      <p className="m-0 font-bold">
        {complete === true
          ? 'Cleanup appears complete'
          : complete === false
            ? 'Waste still appears present'
            : 'No verdict given'}
      </p>
      <ConfidenceMeter label="Confidence" value={proof.ai_confidence} />
      {proof.ai_reasoning ? (
        <p className="m-0 text-xs">{proof.ai_reasoning}</p>
      ) : null}
    </div>
  )
}

function ProofCard({
  proof,
  token,
  complaintStatus,
  onDone,
  aiStalled,
}: {
  proof: ProofReviewItem
  token: string
  complaintStatus: string
  onDone: () => void
  aiStalled: boolean
}) {
  const [reason, setReason] = useState('')
  const [nextStatus, setNextStatus] = useState<'resolved' | 'closed'>(
    'resolved',
  )
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const pending = proof.verification_status === 'pending_verification'
  const uploaded = formatDateTime(proof.uploaded_at)
  // A closed complaint can only stay closed (VALID_TRANSITIONS).
  const target = complaintStatus === 'closed' ? 'closed' : nextStatus

  async function decide(approved: boolean) {
    if (!approved && !reason.trim()) {
      // The backend accepts a blank reason, but the cleaner needs to know what to fix.
      setReasonError('Tell the cleaner what is still wrong.')
      return
    }
    setBusy(approved ? 'approve' : 'reject')
    setError(null)
    setReasonError(null)
    try {
      await verifyProof(
        proof.id,
        approved
          ? { approved: true, next_status: target }
          : { approved: false, rejection_reason: reason.trim() },
        token,
      )
      setDone(
        approved
          ? 'Proof approved — the complaint is updated.'
          : 'Proof rejected — the task is back with the cleaner.',
      )
      onDone()
    } catch (caught) {
      setExpired(isExpiredSession(caught))
      setError(
        caught instanceof Error ? caught.message : 'Verification failed.',
      )
    } finally {
      setBusy(null)
    }
  }

  return (
    <article className="proof-card">
      <div className="compare-grid p-2">
        <div className="compare-cell">
          <span className="compare-tag">Before</span>
          {proof.before_image_url ? (
            <BackendPhoto
              src={backendFileUrl(proof.before_image_url)}
              alt="Complaint photo before cleanup"
            />
          ) : (
            <div
              className="proof-image proof-missing"
              role="img"
              aria-label="No before photo"
            >
              <span>No complaint photo</span>
            </div>
          )}
        </div>
        <div className="compare-cell">
          <span className="compare-tag">After</span>
          <BackendPhoto
            src={backendFileUrl(proof.image_url)}
            alt={`Cleanup proof uploaded ${uploaded}`}
          />
        </div>
      </div>

      <div className="proof-body grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <ProofStatusPill status={proof.verification_status} />
          <span className="text-xs muted">{uploaded}</span>
        </div>

        <div aria-live="polite" className="empty:hidden">
          <AiVerdict proof={proof} stalled={aiStalled} />
        </div>

        {done ? (
          <Callout tone="ok" announce>
            {done}
          </Callout>
        ) : null}

        {proof.rejection_reason ? (
          <p className="m-0 text-xs">
            <strong>Rejected:</strong> {proof.rejection_reason}
          </p>
        ) : null}

        {error ? (
          <ErrorState
            title="Not saved"
            message={error}
            onReauth={expired ? signOut : undefined}
          />
        ) : null}

        {pending ? (
          <div className="grid gap-2">
            <Field
              label="Reason if rejecting"
              htmlFor={`reject-${proof.id}`}
              error={reasonError ?? undefined}
            >
              <input
                id={`reject-${proof.id}`}
                className="input"
                value={reason}
                disabled={busy !== null}
                aria-invalid={Boolean(reasonError)}
                placeholder="e.g. Bags still visible on the left"
                onChange={(event) => setReason(event.target.value)}
              />
            </Field>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="select w-auto"
                aria-label="Complaint status after approval"
                value={target}
                disabled={busy !== null}
                onChange={(event) =>
                  setNextStatus(event.target.value as 'resolved' | 'closed')
                }
              >
                {complaintStatus !== 'closed' ? (
                  <option value="resolved">Approve → resolved</option>
                ) : null}
                <option value="closed">Approve → closed</option>
              </select>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={busy !== null}
                onClick={() => void decide(true)}
              >
                {busy === 'approve' ? <Spinner /> : null}
                Approve
              </button>
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy !== null}
                onClick={() => void decide(false)}
              >
                {busy === 'reject' ? <Spinner /> : null}
                Reject
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </article>
  )
}

function AssignForm({
  complaintId,
  cleaners,
  token,
  onDone,
  submitLabel,
}: {
  complaintId: number | null
  cleaners: KnownCleaner[]
  token: string
  onDone: () => void
  submitLabel: string
}) {
  const [cleaner, setCleaner] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [fieldError, setFieldError] = useState<string | undefined>()
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const slug = submitLabel.toLowerCase().replaceAll(' ', '-')

  return (
    <form
      className="grid gap-3"
      noValidate
      onSubmit={async (event) => {
        event.preventDefault()
        const cleanerId = parseCleanerId(cleaner)
        if (cleanerId === null) {
          setFieldError('Enter the whole-number user ID of a cleaner.')
          return
        }
        if (complaintId === null) return
        setBusy(true)
        setError(null)
        setFieldError(undefined)
        try {
          await assignCleaner(
            complaintId,
            { cleaner_id: cleanerId, notes: notes.trim() || null },
            token,
          )
          setCleaner('')
          setNotes('')
          onDone()
        } catch (caught) {
          setExpired(isExpiredSession(caught))
          setError(
            caught instanceof Error ? caught.message : 'Assignment failed.',
          )
        } finally {
          setBusy(false)
        }
      }}
    >
      {error ? (
        <ErrorState
          title="Not assigned"
          message={error}
          onReauth={expired ? signOut : undefined}
        />
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <CleanerPicker
          id={`assign-${slug}`}
          value={cleaner}
          onChange={(value) => {
            setCleaner(value)
            setFieldError(undefined)
          }}
          cleaners={cleaners}
          error={fieldError}
          disabled={busy}
        />
        <Field label="Instructions" htmlFor={`assign-notes-${slug}`}>
          <input
            id={`assign-notes-${slug}`}
            className="input"
            value={notes}
            disabled={busy}
            onChange={(event) => setNotes(event.target.value)}
          />
        </Field>
      </div>
      <div>
        <button
          type="submit"
          className="btn btn-primary btn-sm"
          disabled={busy || complaintId === null}
        >
          {busy ? <Spinner /> : null}
          {busy ? 'Assigning…' : submitLabel}
        </button>
      </div>
    </form>
  )
}
