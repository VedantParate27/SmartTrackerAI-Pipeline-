import { useState } from 'react'
import {
  BackendPriorityPill,
  Callout,
  ErrorState,
  Field,
  SectionCard,
  Spinner,
} from '#/components/ui'
import {
  PRIORITIES,
  fieldErrors,
  statusMoves,
  updateAdminComplaint,
} from '#/lib/api'
import type {
  AdminComplaintUpdateRequest,
  AdminQueueItem,
  ComplaintResponse,
  Priority,
} from '#/lib/api'
import { isExpiredSession, signOut } from '#/lib/auth'
import { humanize } from '#/lib/complaint-format'

/**
 * The complaint's admin fields — PUT /admin/complaints/{id}. Priority and
 * department have no other route. A status move made here is logged in the
 * case history but is not a decision, so routing stays with the decision panel.
 */
export default function DetailsPanel({
  item,
  complaintId,
  hasTask,
  token,
  onSaved,
}: {
  item: AdminQueueItem
  complaintId: number | null
  hasTask: boolean
  token: string
  onSaved: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [priority, setPriority] = useState('')
  const [department, setDepartment] = useState('')
  const [status, setStatus] = useState('')
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [saved, setSaved] = useState<ComplaintResponse | null>(null)

  const currentPriority = item.priority.toLowerCase()
  const currentDepartment = item.department ?? ''
  const currentStatus = item.status.toLowerCase()
  const moves = statusMoves(item.status)
  // A refresh can move the case on while the form is open.
  const nextStatus = moves.find((move) => move === status) ?? null

  function changes(): AdminComplaintUpdateRequest {
    const body: AdminComplaintUpdateRequest = {}
    if (priority !== currentPriority) body.priority = priority as Priority
    const nextDepartment = department.trim()
    if (nextDepartment && nextDepartment !== currentDepartment) {
      body.department = nextDepartment
    }
    if (nextStatus) body.status = nextStatus
    return body
  }

  function startEditing() {
    setPriority(currentPriority)
    setDepartment(currentDepartment)
    setStatus('')
    setErrors({})
    setError(null)
    setSaved(null)
    setEditing(true)
  }

  const update = changes()
  const unchanged = Object.keys(update).length === 0
  const departmentError =
    currentDepartment && !department.trim()
      ? 'A department can be replaced but not cleared.'
      : undefined
  const closesOpenTask =
    hasTask &&
    (nextStatus === 'resolved' || nextStatus === 'closed') &&
    (currentStatus === 'pending' || currentStatus === 'in_progress')

  return (
    <SectionCard title="Details" meta="priority · department">
      <div className="grid gap-3">
        {saved ? (
          <Callout tone="ok" title="Saved by the backend" announce>
            Priority {humanize(saved.priority)} ·{' '}
            {saved.department ?? 'no department'} · {humanize(saved.status)}.
          </Callout>
        ) : null}

        {!editing ? (
          <>
            <dl className="m-0 grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="kicker">Priority</dt>
                <dd className="m-0 mt-1">
                  <BackendPriorityPill priority={item.priority} />
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="kicker">Department</dt>
                <dd className="m-0 mt-1 wrap-break-word">
                  {item.department ?? <span className="muted">Not set</span>}
                </dd>
              </div>
            </dl>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-sm"
                disabled={complaintId === null}
                onClick={startEditing}
              >
                Edit details
              </button>
              {complaintId === null ? (
                <span className="text-xs muted">Resolving the case id…</span>
              ) : null}
            </div>
          </>
        ) : (
          <form
            className="grid gap-3"
            noValidate
            onSubmit={async (event) => {
              event.preventDefault()
              setErrors({})
              if (departmentError || unchanged || complaintId === null) return
              setSaving(true)
              setError(null)
              try {
                const result = await updateAdminComplaint(
                  complaintId,
                  update,
                  token,
                )
                setSaved(result)
                setEditing(false)
                onSaved()
              } catch (caught) {
                setErrors(fieldErrors(caught))
                setExpired(isExpiredSession(caught))
                setError(
                  caught instanceof Error ? caught.message : 'Update failed.',
                )
              } finally {
                setSaving(false)
              }
            }}
          >
            {error ? (
              <ErrorState
                title="Not saved"
                message={error}
                onReauth={expired ? signOut : undefined}
              />
            ) : null}

            <Field
              label="Priority"
              htmlFor="details-priority"
              hint="Set by the backend from the waste type and amount; override it here."
              error={errors.priority}
            >
              <select
                id="details-priority"
                className="select"
                value={priority}
                disabled={saving}
                aria-invalid={Boolean(errors.priority)}
                onChange={(event) => setPriority(event.target.value)}
              >
                {PRIORITIES.map((value) => (
                  <option key={value} value={value}>
                    {humanize(value)}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              label="Department"
              htmlFor="details-department"
              hint="Who handles it. Can be replaced, not cleared."
              error={errors.department ?? departmentError}
            >
              <input
                id="details-department"
                className="input"
                maxLength={100}
                value={department}
                disabled={saving}
                aria-invalid={Boolean(errors.department ?? departmentError)}
                placeholder="e.g. Ward 3 sanitation"
                onChange={(event) => setDepartment(event.target.value)}
              />
            </Field>

            {moves.length > 0 ? (
              <Field
                label="Status"
                htmlFor="details-status"
                hint="Logged in the case history, but not as a decision."
                error={errors.status}
              >
                <select
                  id="details-status"
                  className="select"
                  value={nextStatus ?? ''}
                  disabled={saving}
                  aria-invalid={Boolean(errors.status)}
                  onChange={(event) => setStatus(event.target.value)}
                >
                  <option value="">Keep {humanize(currentStatus)}</option>
                  {moves.map((move) => (
                    <option key={move} value={move}>
                      Move to {humanize(move).toLowerCase()}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            {closesOpenTask ? (
              <Callout tone="warn" title="A cleanup task is still open">
                This ends the case without a verified proof photo.
              </Callout>
            ) : null}

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={
                  saving ||
                  unchanged ||
                  Boolean(departmentError) ||
                  complaintId === null
                }
              >
                {saving ? <Spinner /> : null}
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                className="btn btn-quiet btn-sm"
                disabled={saving}
                onClick={() => setEditing(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </SectionCard>
  )
}
