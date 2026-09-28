import { useState } from 'react'
import CleanerPicker, { parseCleanerId } from './CleanerPicker'
import type { KnownCleaner } from './CleanerPicker'
import {
  Callout,
  ErrorState,
  Field,
  LoadingState,
  ProofImage,
  ProofStatusPill,
  SectionCard,
  Spinner,
  TaskStatusPill,
} from '#/components/ui'
import { assignCleaner, backendFileUrl, verifyProof } from '#/lib/api'
import type { CleanerTask, CleanupProof } from '#/lib/api'
import { isExpiredSession, signOut } from '#/lib/auth'
import { formatDateTime } from '#/lib/format'

export interface Assignee {
  id: number
  name: string | null
}

/**
 * Field execution for a dispatched case: who holds the task, the proof photos
 * they uploaded, and the admin's verify/reject decision on each. A rejection
 * sends the task back to the cleaner — the resubmission loop process mining
 * measures.
 */
export default function TaskPanel({
  complaintStatus,
  complaintId,
  task,
  loading,
  error,
  onRetry,
  assignee,
  cleaners,
  token,
  onChanged,
}: {
  complaintStatus: string
  complaintId: number | null
  task: CleanerTask | null
  loading: boolean
  error: string | null
  onRetry: () => void
  assignee: Assignee | null
  cleaners: KnownCleaner[]
  token: string
  onChanged: () => void
}) {
  const status = complaintStatus.toLowerCase()

  if (loading && !task) {
    return (
      <SectionCard title="Cleanup task">
        <LoadingState label="Looking up the cleanup task…" />
      </SectionCard>
    )
  }

  if (error) {
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

  if (!task) {
    return (
      <SectionCard title="Cleanup task">
        {status === 'in_progress' ? (
          <div className="grid gap-3">
            <Callout tone="warn" title="Dispatched, but nobody is assigned">
              Assign a cleaner so the task appears in their list.
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
            Choose <strong>Dispatch a cleaner</strong> in the decision panel to
            create a cleanup task.
          </p>
        ) : (
          <p className="m-0 text-sm muted">
            No cleanup task — this case was closed without a field visit.
          </p>
        )}
      </SectionCard>
    )
  }

  const proofs = [...task.proofs].reverse()
  const finished = task.status === 'verified'

  return (
    <SectionCard
      title="Cleanup task"
      meta={<span className="mono">{task.task_id}</span>}
    >
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <TaskStatusPill status={task.status} />
          <span className="text-sm muted">
            {assignee
              ? `Assigned to ${assignee.name ?? `cleaner #${assignee.id}`}`
              : 'Assigned'}{' '}
            · {formatDateTime(task.assigned_at)}
          </span>
        </div>

        {task.completed_at ? (
          <p className="m-0 text-sm muted">
            Completed {formatDateTime(task.completed_at)}
          </p>
        ) : null}

        {task.notes ? (
          <div>
            <span className="kicker">Instructions</span>
            <p className="mt-1 mb-0 text-sm">{task.notes}</p>
          </div>
        ) : null}

        <div>
          <span className="kicker">Proof photos</span>
          {proofs.length === 0 ? (
            <p className="mt-1 mb-0 text-sm muted">
              Waiting for the cleaner to upload a photo of the cleaned spot.
            </p>
          ) : (
            <ul className="proof-grid mt-2 list-none p-0">
              {proofs.map((proof) => (
                <li key={proof.id}>
                  <ProofCard
                    proof={proof}
                    token={token}
                    complaintStatus={status}
                    onDone={onChanged}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>

        {!finished ? (
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

function ProofCard({
  proof,
  token,
  complaintStatus,
  onDone,
}: {
  proof: CleanupProof
  token: string
  complaintStatus: string
  onDone: () => void
}) {
  const [reason, setReason] = useState('')
  const [nextStatus, setNextStatus] = useState<'resolved' | 'closed'>(
    'resolved',
  )
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const pending = proof.verification_status === 'pending_verification'
  const image = backendFileUrl(proof.image_url)

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
          ? { approved: true, next_status: nextStatus }
          : { approved: false, rejection_reason: reason.trim() },
        token,
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
      <ProofImage
        src={image}
        alt={`Cleanup proof uploaded ${formatDateTime(proof.uploaded_at)}`}
      />
      <div className="proof-body grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <ProofStatusPill status={proof.verification_status} />
          <span className="text-xs muted">
            {formatDateTime(proof.uploaded_at)}
          </span>
        </div>

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
                value={nextStatus}
                disabled={busy !== null}
                onChange={(event) =>
                  setNextStatus(event.target.value as 'resolved' | 'closed')
                }
              >
                <option value="resolved">Approve → resolved</option>
                {complaintStatus !== 'closed' ? (
                  <option value="closed">Approve → closed</option>
                ) : null}
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
