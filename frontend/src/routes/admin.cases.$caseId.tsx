import { useEffect, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  approveComplaint,
  getBackendImageUrl,
  getComplaint,
  listCleaners,
  reviewWasteComplaint,
  type CleanerUser,
} from '#/lib/api'
import {
  Callout,
  ConfidenceMeter,
  EmptyState,
  PriorityPill,
  SectionCard,
  StatusPill,
} from '#/components/ui'
import {
  formatAge,
  formatBytes,
  formatDate,
  formatDateTime,
  percent,
} from '#/lib/format'
import {
  activeDraft,
  addComment,
  escalate,
  isVisible,
  markDuplicate,
  overrideClassification,
  reassign,
  reject,
  saveDraftEdit,
  setStatus,
  useAppState,
} from '#/lib/store'
import {
  ALLOWED_TRANSITIONS,
  CONFIG,
  DEPARTMENTS,
  EMBEDDING_MODEL,
  can,
} from '#/lib/taxonomy'
import type { Complaint } from '#/lib/types'

export const Route = createFileRoute('/admin/cases/$caseId')({
  component: CaseDetailPage,
})

function CaseDetailPage() {
  const { caseId } = Route.useParams()
  const { session, now } = useAppState()
  const [item, setItem] = useState<Complaint | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)

    getComplaint(caseId)
      .then((complaint) => {
        setItem(complaint)
      })
      .catch((error) => {
        console.error('Failed to load complaint:', error)
        setItem(null)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [caseId])

  if (loading) {
    return <p>Loading case...</p>
  }

  if (!item) {
    return (
      <Callout tone="warn" title="Case not found">
        No case is stored against <span className="mono">{caseId}</span>.{' '}
        <Link to="/admin">Back to the queue</Link>.
      </Callout>
    )
  }

  // AC-09 / UR-05: cross-department case data stays hidden.
  if (!isVisible(item, session)) {
    return (
      <Callout tone="danger" title="Not authorised">
        This case is not routed to your department, so its contents are not
        available to you. <Link to="/admin">Back to the queue</Link>.
      </Callout>
    )
  }

  const draftReady =
    item.status === 'Pending Review' || item.status === 'Manual Triage'

  return (
    <div className="grid gap-4">
      <Link to="/admin" className="text-sm no-underline">
        ← Back to queue
      </Link>

      <header className="card card-pad">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="kicker">Grievance</span>
            <h2 className="mono mt-0.5 text-lg font-extrabold">{item.id}</h2>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <StatusPill status={item.status} />
            <PriorityPill priority={item.priority} />
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm lg:grid-cols-4">
          <div>
            <dt className="kicker">Requester</dt>
            <dd className="m-0">{item.requesterName}</dd>
          </div>
          <div className="min-w-0">
            <dt className="kicker">Contact</dt>
            <dd className="m-0 truncate">{item.contact}</dd>
          </div>
          <div>
            <dt className="kicker">Submitted</dt>
            <dd className="m-0">{formatDateTime(item.submittedAt)}</dd>
          </div>
          <div>
            <dt className="kicker">Age</dt>
            <dd className="m-0">{formatAge(item.submittedAt, now)}</dd>
          </div>
          <div>
            <dt className="kicker">Channel</dt>
            <dd className="m-0">{item.channel}</dd>
          </div>
          <div>
            <dt className="kicker">Language</dt>
            <dd className="m-0">{item.language}</dd>
          </div>
          <div>
            <dt className="kicker">Assigned to</dt>
            <dd className="m-0">{item.assignedDepartment ?? 'Not assigned'}</dd>
          </div>
          <div className="min-w-0">
            <dt className="kicker">Location</dt>
            <dd className="m-0 truncate">
              {item.location?.type === 'gps'
                ? `${item.location.latitude?.toFixed(5)}, ${item.location.longitude?.toFixed(5)}`
                : item.location?.type === 'manual'
                  ? item.location.manualAddress
                  : 'Not provided'}
            </dd>
          </div>
          <div>
            <dt className="kicker">Last updated</dt>
            <dd className="m-0">{formatDateTime(item.updatedAt)}</dd>
          </div>
        </dl>
      </header>

      {item.status === 'Manual Triage' ? (
        <Callout
          tone="warn"
          title="Manual triage required — not approval ready"
        >
          <ul className="m-0 mt-1 list-disc space-y-0.5 pl-4">
            {item.audit
              .filter((event) => event.action === 'Status set to Manual Triage')
              .map((event) => (
                <li key={event.id}>{event.detail}</li>
              ))}
          </ul>
        </Callout>
      ) : null}

      {item.duplicateOf ? (
        <Callout tone="info" title="Linked as a duplicate">
          This case is linked to{' '}
          <span className="mono">{item.duplicateOf}</span>.
        </Callout>
      ) : null}

      <WasteReviewPanel item={item} onRefresh={() => {
        getComplaint(caseId).then(setItem).catch(console.error)
      }} />

      <OriginalComplaint item={item} />
      <ClassificationPanel
        item={item}
        canOverride={can(session, 'case.override')}
      />
      <EvidencePanel item={item} />
      <DraftPanel
        item={item}
        canEdit={can(session, 'case.edit_draft')}
        canApprove={can(session, 'case.approve') && draftReady}
      />
      <ActionsPanel item={item} />
      <CommentsPanel item={item} canComment={can(session, 'case.comment')} />
      <AuditPanel item={item} />
    </div>
  )
}

/* ------------------------------------------------------------------ *
 * FR-18 - original text, attachments and extracted entities
 * ------------------------------------------------------------------ */

function OriginalComplaint({ item }: { item: Complaint }) {
  return (
    <SectionCard title="Original complaint" meta="Stored unchanged (SRS 7.3)">
      <p className="original-text m-0">{item.text}</p>

      {item.attachments.length > 0 ? (
        <ul className="m-0 mt-4 list-none space-y-1 p-0 text-xs muted">
          {item.attachments.map((file) => (
            <li key={file.name} className="flex justify-between gap-3">
              <span className="min-w-0 truncate">{file.name}</span>
              <span className="subtle shrink-0">{formatBytes(file.size)}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <h3 className="kicker mt-5">Extracted entities</h3>
      {item.entities.length === 0 ? (
        <p className="mt-1 text-sm muted">
          No configured entity was found in this complaint.
        </p>
      ) : (
        <div className="table-scroll mt-2">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Type</th>
                <th scope="col">Value</th>
                <th scope="col">Normalized</th>
                <th scope="col">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {item.entities.map((entity) => (
                <tr key={`${entity.type}-${entity.span[0]}`}>
                  <td className="whitespace-nowrap font-bold">{entity.type}</td>
                  <td>{entity.value}</td>
                  <td className="mono">{entity.normalized}</td>
                  <td>{percent(entity.confidence)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  )
}

/* ------------------------------------------------------------------ *
 * FR-06, FR-07, FR-11 - classification, alternatives and override
 * ------------------------------------------------------------------ */

function ClassificationPanel({
  item,
  canOverride,
}: {
  item: Complaint
  canOverride: boolean
}) {
  const classification = item.classification
  const [open, setOpen] = useState(false)
  const [intent, setIntent] = useState(classification?.intent ?? '')
  const [department, setDepartment] = useState(classification?.department ?? '')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')

  if (!classification) {
    return (
      <SectionCard title="AI classification">
        <p className="m-0 text-sm muted">
          Analysis has not finished for this case yet.
        </p>
      </SectionCard>
    )
  }

  return (
    <SectionCard
      title="AI classification and routing"
      meta={`Model ${classification.modelVersion} · taxonomy ${classification.taxonomyVersion}`}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <span className="kicker">Predicted intent</span>
          <p className="m-0 text-sm font-bold">{classification.intent}</p>
        </div>
        <div>
          <span className="kicker">Recommended department</span>
          <p className="m-0 text-sm font-bold">{classification.department}</p>
        </div>
      </div>

      <div className="mt-4">
        <ConfidenceMeter
          value={classification.confidence}
          threshold={CONFIG.confidenceThreshold}
        />
      </div>

      {classification.ruleApplied ? (
        <p className="mt-3 text-xs muted">
          <strong>Routing rule applied:</strong> {classification.ruleApplied}
        </p>
      ) : null}

      {classification.overriddenBy ? (
        <div className="mt-3">
          <Callout tone="info" title="Overridden by a human">
            {classification.overriddenBy} replaced the predicted intent or
            department. The original prediction is kept in the audit trail.
          </Callout>
        </div>
      ) : null}

      <h3 className="kicker mt-5">Alternative predictions</h3>
      {classification.alternatives.length === 0 ? (
        <p className="mt-1 text-sm muted">No alternative scored above zero.</p>
      ) : (
        <ul className="m-0 mt-2 list-none space-y-1 p-0 text-sm">
          {classification.alternatives.map((alternative) => (
            <li
              key={alternative.intent}
              className="flex flex-wrap justify-between gap-2"
            >
              <span>
                {alternative.intent}{' '}
                <span className="subtle">→ {alternative.department}</span>
              </span>
              <span className="muted">{percent(alternative.confidence)}</span>
            </li>
          ))}
        </ul>
      )}

      {canOverride ? (
        <div className="mt-5 border-t border-(--line) pt-4">
          {open ? (
            <form
              className="grid gap-3"
              onSubmit={(event) => {
                event.preventDefault()
                if (reason.trim().length < 4) {
                  setError('A reason is mandatory for an override (BR-02).')
                  return
                }
                overrideClassification(item.id, {
                  intent,
                  department,
                  reason: reason.trim(),
                })
                setOpen(false)
                setReason('')
                setError('')
              }}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="ov-intent">
                    Intent
                  </label>
                  <input
                    id="ov-intent"
                    className="input"
                    value={intent}
                    onChange={(event) => setIntent(event.target.value)}
                  />
                </div>
                <div>
                  <label className="label" htmlFor="ov-dept">
                    Department
                  </label>
                  <select
                    id="ov-dept"
                    className="select"
                    value={department}
                    onChange={(event) => setDepartment(event.target.value)}
                  >
                    {DEPARTMENTS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="label" htmlFor="ov-reason">
                  Reason<span className="req">*</span>
                </label>
                <input
                  id="ov-reason"
                  className="input"
                  value={reason}
                  aria-invalid={Boolean(error)}
                  onChange={(event) => setReason(event.target.value)}
                />
                {error ? (
                  <p className="field-error">
                    <span aria-hidden="true">!</span>
                    <span>{error}</span>
                  </p>
                ) : null}
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <button type="submit" className="btn btn-primary btn-sm">
                  Save override
                </button>
                <button
                  type="button"
                  className="btn btn-quiet btn-sm"
                  onClick={() => setOpen(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setOpen(true)}
            >
              Override intent or department
            </button>
          )}
        </div>
      ) : null}
    </SectionCard>
  )
}

/* ------------------------------------------------------------------ *
 * FR-12 to FR-14, UI-03 - retrieved evidence, kept visually separate
 * ------------------------------------------------------------------ */

function EvidencePanel({ item }: { item: Complaint }) {
  const citedIds = item.aiDraft?.evidenceIds ?? []

  return (
    <SectionCard
      title="Retrieved policy evidence"
      meta={`Hybrid retrieval · dense ${CONFIG.denseWeight} / BM25 ${CONFIG.keywordWeight} · ${EMBEDDING_MODEL}`}
    >
      {item.evidence.length === 0 ? (
        <Callout tone="warn" title="No evidence cleared the threshold">
          Nothing in the active policy set scored at or above{' '}
          {CONFIG.evidenceThreshold} for this complaint, so no grounded draft
          can be produced (FR-16, BR-03).
        </Callout>
      ) : (
        <ul className="m-0 grid list-none gap-3 p-0">
          {item.evidence.map((evidence, index) => {
            const cited = citedIds.indexOf(evidence.chunkId)
            return (
              <li key={evidence.chunkId} className="evidence">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="m-0 text-sm font-bold">
                      {evidence.documentTitle}
                    </p>
                    <p className="m-0 text-xs muted">
                      {evidence.section} · page {evidence.page} · version{' '}
                      {evidence.version} · effective{' '}
                      {formatDate(evidence.effectiveDate)}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-1.5">
                    <span className="pill">rank {index + 1}</span>
                    {cited >= 0 ? (
                      <span className="pill" data-tone="ok">
                        cited [{cited + 1}]
                      </span>
                    ) : null}
                  </div>
                </div>

                <p className="evidence-quote">{evidence.snippet}</p>

                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs subtle">
                  <span>dense {evidence.denseScore.toFixed(3)}</span>
                  <span>bm25 {evidence.keywordScore.toFixed(3)}</span>
                  <span className="font-bold">
                    hybrid {evidence.hybridScore.toFixed(3)}
                  </span>
                  <span className="mono">{evidence.chunkId}</span>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      <p className="hint">
        Only chunks belonging to an active policy version and the routed
        department are searched (FR-13, FR-27).
      </p>
    </SectionCard>
  )
}

/* ------------------------------------------------------------------ *
 * FR-15, FR-19, FR-20 - draft, edit and approve
 * ------------------------------------------------------------------ */

function DraftPanel({
  item,
  canEdit,
  canApprove,
}: {
  item: Complaint
  canEdit: boolean
  canApprove: boolean
}) {
  const draft = item.aiDraft
  const [text, setText] = useState(activeDraft(item))
  const [nextStatus, setNextStatus] = useState<
    'Assigned to Department' | 'Resolved'
  >('Assigned to Department')

  // Keep the editor in step when the case changes underneath it.
  useEffect(() => {
    setText(activeDraft(item))
  }, [item.id, item.aiDraft?.createdAt, item.editedDraft])

  if (!draft) {
    return (
      <SectionCard title="AI draft response">
        <p className="m-0 text-sm muted">No draft has been generated yet.</p>
      </SectionCard>
    )
  }

  const abstained = draft.grounding === 'Insufficient Evidence'
  const untouched = item.editedDraft === null
  // BR-03: an abstained draft may not be sent unless a human writes the reply.
  const approvalBlocked = abstained && untouched
  const dirty = text !== activeDraft(item)

  return (
    <SectionCard
      title="Draft response"
      meta={`${draft.generationModel} · generated ${formatDateTime(draft.createdAt)}`}
    >
      <div className="grid gap-3">
        <Callout
          tone={abstained ? 'warn' : 'ok'}
          title={`Grounding check: ${draft.grounding}`}
        >
          <ul className="m-0 mt-1 list-disc space-y-0.5 pl-4">
            {draft.groundingNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Callout>

        {item.resolution ? (
          <Callout tone="ok" title="Already approved and sent">
            Approved by {item.resolution.approver} on{' '}
            {formatDateTime(item.resolution.sentAt)}.
          </Callout>
        ) : null}

        <details className="card card-pad">
          <summary className="cursor-pointer text-sm font-bold">
            Original AI draft (immutable)
          </summary>
          <div className="draft-box mt-3">{draft.text}</div>
        </details>

        {canEdit ? (
          <div>
            <label className="label" htmlFor="draft-editor">
              Working copy {item.editedDraft !== null ? '(edited)' : ''}
            </label>
            <textarea
              id="draft-editor"
              className="textarea min-h-64"
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
            <p className="hint">
              Editing never changes the stored AI original; the edit is saved as
              a new version and recorded in the audit trail (FR-19).
            </p>
          </div>
        ) : (
          <div className="draft-box">{activeDraft(item)}</div>
        )}

        {approvalBlocked ? (
          <Callout tone="warn" title="Approval blocked">
            This draft abstained because no active policy evidence supports a
            reply. Write a response in the working copy and save it, or reassign
            the case, before approving.
          </Callout>
        ) : null}

        {canEdit ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <button
              type="button"
              className="btn btn-sm"
              disabled={!dirty}
              onClick={() => saveDraftEdit(item.id, text)}
            >
              Save edit
            </button>
            {dirty ? (
              <button
                type="button"
                className="btn btn-quiet btn-sm"
                onClick={() => setText(activeDraft(item))}
              >
                Discard changes
              </button>
            ) : null}
          </div>
        ) : null}

        {canApprove ? (
          <form
            className="grid gap-2 border-t border-(--line) pt-4 sm:grid-cols-[1fr_auto] sm:items-end"
            onSubmit={async (event) => {
              event.preventDefault()

              try {
                await approveComplaint(item.id, {
                  admin_id: 2,
                  final_response: text,
                })

                window.location.reload()
              } catch (error) {
                console.error('Failed to approve complaint:', error)
              }
            }}
          >
            <div>
              <label className="label" htmlFor="next-status">
                Status after sending
              </label>
              <select
                id="next-status"
                className="select"
                value={nextStatus}
                onChange={(event) =>
                  setNextStatus(
                    event.target.value as 'Assigned to Department' | 'Resolved',
                  )
                }
              >
                <option value="Assigned to Department">
                  Assigned to Department
                </option>
                <option value="Resolved">Resolved</option>
              </select>
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={approvalBlocked || Boolean(item.resolution)}
            >
              Approve and send
            </button>
            <p className="hint sm:col-span-2">
              Your name is recorded as the approver. Nothing leaves the system
              without this action (FR-20, BR-01, AI-08).
            </p>
          </form>
        ) : null}
      </div>
    </SectionCard>
  )
}

/* ------------------------------------------------------------------ *
 * FR-21, FR-22 - reassign, escalate, reject, duplicate, status change
 * ------------------------------------------------------------------ */

type ActionKind = 'reassign' | 'escalate' | 'reject' | 'duplicate' | 'status'

function ActionsPanel({ item }: { item: Complaint }) {
  const { session } = useAppState()
  const [kind, setKind] = useState<ActionKind>('reassign')
  const [department, setDepartment] = useState<string>(DEPARTMENTS[0])
  const [duplicateOf, setDuplicateOf] = useState('')
  const [status, setStatusValue] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  const allowedActions: ActionKind[] = can(session, 'case.reassign')
    ? ['reassign', 'escalate', 'reject', 'duplicate', 'status']
    : can(session, 'case.status')
      ? ['escalate', 'status']
      : []

  const transitions = ALLOWED_TRANSITIONS[item.status]
  // Clamp at render time so switching role cannot leave an unavailable action.
  const active = allowedActions.includes(kind) ? kind : allowedActions[0]

  if (allowedActions.length === 0) {
    return (
      <SectionCard title="Administrator actions">
        <p className="m-0 text-sm muted">
          Your role cannot change this case. Sign in as a support administrator
          to review it.
        </p>
      </SectionCard>
    )
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    setDone('')

    if (reason.trim().length < 4) {
      setError('A reason is mandatory and is written to the audit log (BR-02).')
      return
    }

    if (active === 'reassign') {
      reassign(item.id, department, reason.trim())
    } else if (active === 'escalate') {
      escalate(item.id, reason.trim())
    } else if (active === 'reject') {
      reject(item.id, reason.trim())
    } else if (active === 'duplicate') {
      if (!/^grv-\d{4}-\d{4}$/i.test(duplicateOf.trim())) {
        setError(
          'Enter the reference of the original case, for example GRV-2026-0431.',
        )
        return
      }
      markDuplicate(item.id, duplicateOf.trim(), reason.trim())
    } else {
      if (!status) {
        setError('Choose the status to move this case to.')
        return
      }
      if (!setStatus(item.id, status as Complaint['status'], reason.trim())) {
        setError(
          'That transition is not permitted from the current status (BR-06).',
        )
        return
      }
    }

    setError('')
    setReason('')
    setDuplicateOf('')
    setDone('Action applied and recorded in the audit trail.')
  }

  const LABELS: Record<ActionKind, string> = {
    reassign: 'Reassign to another department',
    escalate: 'Escalate for senior review',
    reject: 'Reject as invalid or out of scope',
    duplicate: 'Mark as duplicate of another case',
    status: 'Change status',
  }

  return (
    <SectionCard title="Administrator actions">
      <form className="grid gap-3" onSubmit={submit}>
        <div>
          <label className="label" htmlFor="action-kind">
            Action
          </label>
          <select
            id="action-kind"
            className="select"
            value={active}
            onChange={(event) => {
              setKind(event.target.value as ActionKind)
              setError('')
              setDone('')
            }}
          >
            {allowedActions.map((option) => (
              <option key={option} value={option}>
                {LABELS[option]}
              </option>
            ))}
          </select>
        </div>

        {active === 'reassign' ? (
          <div>
            <label className="label" htmlFor="action-dept">
              New department
            </label>
            <select
              id="action-dept"
              className="select"
              value={department}
              onChange={(event) => setDepartment(event.target.value)}
            >
              {DEPARTMENTS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {active === 'duplicate' ? (
          <div>
            <label className="label" htmlFor="action-duplicate">
              Original case reference
            </label>
            <input
              id="action-duplicate"
              className="input mono"
              placeholder="GRV-2026-0431"
              value={duplicateOf}
              onChange={(event) => setDuplicateOf(event.target.value)}
            />
          </div>
        ) : null}

        {active === 'status' ? (
          <div>
            <label className="label" htmlFor="action-status">
              New status
            </label>
            <select
              id="action-status"
              className="select"
              value={status}
              onChange={(event) => setStatusValue(event.target.value)}
            >
              <option value="">Select a status…</option>
              {transitions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <p className="hint">
              Only transitions permitted from <strong>{item.status}</strong> are
              listed (BR-06).
            </p>
          </div>
        ) : null}

        <div>
          <label className="label" htmlFor="action-reason">
            Reason<span className="req">*</span>
          </label>
          <textarea
            id="action-reason"
            className="textarea min-h-20"
            value={reason}
            aria-invalid={Boolean(error)}
            onChange={(event) => setReason(event.target.value)}
          />
          {error ? (
            <p className="field-error">
              <span aria-hidden="true">!</span>
              <span>{error}</span>
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <button
            type="submit"
            className={
              active === 'reject' ? 'btn btn-danger' : 'btn btn-primary'
            }
          >
            Apply action
          </button>
          {done ? (
            <span className="text-xs font-bold text-(--ok)" role="status">
              {done}
            </span>
          ) : null}
        </div>
      </form>
    </SectionCard>
  )
}

/* ------------------------------------------------------------------ *
 * FR-22 - comments, and the audit trail behind every action
 * ------------------------------------------------------------------ */

function CommentsPanel({
  item,
  canComment,
}: {
  item: Complaint
  canComment: boolean
}) {
  const [text, setText] = useState('')

  return (
    <SectionCard title="Internal comments" bodyClassName="">
      {item.comments.length === 0 ? (
        <EmptyState>No internal comments on this case yet.</EmptyState>
      ) : (
        <ul className="m-0 list-none divide-rows p-0">
          {item.comments.map((comment) => (
            <li key={comment.id} className="px-4 py-3">
              <p className="m-0 text-sm">{comment.text}</p>
              <p className="m-0 mt-1 text-xs subtle">
                {comment.author} · {formatDateTime(comment.at)}
              </p>
            </li>
          ))}
        </ul>
      )}

      {canComment ? (
        <form
          className="border-t border-(--line) p-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (text.trim().length < 2) return
            addComment(item.id, text.trim())
            setText('')
          }}
        >
          <label className="label" htmlFor="comment">
            Add a comment
          </label>
          <textarea
            id="comment"
            className="textarea min-h-20"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <button
            type="submit"
            className="btn btn-sm mt-2"
            disabled={text.trim().length < 2}
          >
            Add comment
          </button>
        </form>
      ) : null}
    </SectionCard>
  )
}

function AuditPanel({ item }: { item: Complaint }) {
  return (
    <SectionCard
      title="Audit trail"
      meta={`${item.audit.length} events`}
      bodyClassName=""
    >
      <ol className="m-0 list-none divide-rows p-0">
        {[...item.audit].reverse().map((event) => (
          <li key={event.id} className="px-4 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="m-0 text-sm font-bold">{event.action}</p>
              <p className="m-0 text-xs subtle">{formatDateTime(event.at)}</p>
            </div>
            {event.detail ? (
              <p className="m-0 mt-1 text-xs muted">{event.detail}</p>
            ) : null}
            <p className="m-0 mt-1 text-xs subtle">
              {event.actor} · <span className="mono">{event.requestId}</span>
            </p>
          </li>
        ))}
      </ol>
    </SectionCard>
  )
}

function WasteReviewPanel({ item, onRefresh }: { item: Complaint; onRefresh: () => void }) {
  const [cleaners, setCleaners] = useState<CleanerUser[]>([])
  const [decision, setDecision] = useState<'approve_cleanup' | 'reject'>('approve_cleanup')
  const [cleanerId, setCleanerId] = useState<string>('')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  
  useEffect(() => {
    let cancelled = false

    listCleaners()
      .then((data) => {
        if (cancelled) return

        setCleaners(data)
        setCleanerId((current) => {
          if (current && data.some((cleaner) => String(cleaner.id) === current)) {
            return current
          }

          return data.length > 0 ? String(data[0].id) : ''
        })

        if (data.length === 0) {
          setError('No cleaner accounts were found. Create a cleaner account before assigning this complaint.')
        } else {
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return

        console.error('Failed to list cleaners:', err)
        setError(
          err instanceof Error
            ? `Could not load cleaners: ${err.message}`
            : 'Could not load cleaners. Check your Admin login and API connection.',
        )
      })

    return () => {
      cancelled = true
    }
  }, [])


  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)

    if (decision === 'approve_cleanup' && !cleanerId) {
      setError('Please select a cleaner for assignment.')
      return
    }

    setLoading(true)

    try {
      await reviewWasteComplaint(item.id, {
        decision,
        cleaner_id: decision === 'approve_cleanup' ? Number(cleanerId) : null,
        notes: notes.trim() || null,
      })
      setSuccess(`Waste complaint review submitted! Status set to ${decision === 'approve_cleanup' ? 'assigned' : 'rejected'}.`)
      onRefresh()
    } catch (err: any) {
      setError(err?.message || 'Failed to submit review.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <SectionCard title="Waste Complaint Review & Assignment" meta="AI Waste Classification & Dispatch">
      {success ? (
        <Callout tone="ok" title="Review Complete">
          {success}
        </Callout>
      ) : null}

      {error ? (
        <Callout tone="danger" title="Review Error">
          {error}
        </Callout>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h3 className="kicker">AI Waste Analysis</h3>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
            <div className="bg-(--surface-2) p-2.5 rounded">
              <dt className="kicker">Waste Type</dt>
              <dd className="m-0 font-bold capitalize">{item.wasteType ?? item.classification?.intent ?? 'General Waste'}</dd>
            </div>
            <div className="bg-(--surface-2) p-2.5 rounded">
              <dt className="kicker">Severity</dt>
              <dd className="m-0 font-bold capitalize">{item.severity ?? 'Normal'}</dd>
            </div>
          </dl>

          {item.aiReasoning ? (
            <div className="mt-3 text-xs muted">
              <span className="kicker">AI Reasoning</span>
              <p className="m-0 italic">{item.aiReasoning}</p>
            </div>
          ) : null}

          {item.imagePath ? (
            <div className="mt-4">
              <span className="kicker">Submitted Image (Before)</span>
              <div className="mt-1 max-w-xs rounded overflow-hidden border border-(--line)">
                <img
                  src={getBackendImageUrl(item.imagePath) ?? undefined}
                  alt="Before cleanup waste complaint"
                  className="w-full h-auto max-h-48 object-cover"
                />
              </div>
            </div>
          ) : null}
        </div>

        <div className="border-t border-(--line) pt-4 md:border-t-0 md:border-l md:pl-4 md:pt-0">
          <h3 className="kicker">Admin Decision</h3>
          <form className="mt-2 grid gap-3" onSubmit={handleSubmit}>
            <div>
              <label className="label">Review Decision</label>
              <div className="flex gap-4 mt-1">
                <label className="flex items-center gap-1.5 cursor-pointer text-sm font-semibold">
                  <input
                    type="radio"
                    name="decision"
                    value="approve_cleanup"
                    checked={decision === 'approve_cleanup'}
                    onChange={() => setDecision('approve_cleanup')}
                  />
                  Approve & Assign Cleanup
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer text-sm font-semibold">
                  <input
                    type="radio"
                    name="decision"
                    value="reject"
                    checked={decision === 'reject'}
                    onChange={() => setDecision('reject')}
                  />
                  Reject Complaint
                </label>
              </div>
            </div>

            {decision === 'approve_cleanup' ? (
              <div>
                <label className="label" htmlFor="cleaner-select">
                  Assign Cleaner
                </label>
                <select
                  id="cleaner-select"
                  className="select"
                  value={cleanerId}
                  onChange={(e) => setCleanerId(e.target.value)}
                >
                  {cleaners.length === 0 ? (
                    <option value="">No available cleaners found</option>
                  ) : (
                    cleaners.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} ({c.email})
                      </option>
                    ))
                  )}
                </select>
              </div>
            ) : null}

            <div>
              <label className="label" htmlFor="review-notes">
                Notes (Optional)
              </label>
              <input
                id="review-notes"
                className="input"
                value={notes}
                placeholder="Enter assignment notes or rejection reason..."
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary mt-2"
              
              disabled={
                loading ||
                (decision === 'approve_cleanup' &&
                  (!cleanerId ||
                    !cleaners.some((cleaner) => String(cleaner.id) === cleanerId)))
              }

            >
              {loading ? 'Submitting...' : decision === 'approve_cleanup' ? 'Approve & Assign Cleaner' : 'Reject Complaint'}
            </button>
          </form>
        </div>
      </div>
    </SectionCard>
  )
}
