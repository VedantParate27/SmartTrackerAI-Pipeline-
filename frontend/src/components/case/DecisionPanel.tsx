import { useState } from 'react'
import CleanerPicker, { parseCleanerId } from './CleanerPicker'
import type { KnownCleaner } from './CleanerPicker'
import {
  BackendPriorityPill,
  Callout,
  ErrorState,
  Field,
  SectionCard,
  Spinner,
  WastePill,
} from '#/components/ui'
import { allowedDecisions, assignCleaner, recordAdminDecision } from '#/lib/api'
import type {
  AdminDecisionResult,
  AdminDecisionValue,
  AdminQueueItem,
  AssignCleanerResponse,
  EventLogEntry,
  WasteAIAnalysis,
} from '#/lib/api'
import { isExpiredSession, signOut } from '#/lib/auth'
import {
  backendResolution,
  decisionLabel,
  severityLabel,
} from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'

const DESCRIPTIONS: Record<AdminDecisionValue, string> = {
  assign_cleaner:
    'Creates a cleanup task. Pick the cleaner now or from the task panel.',
  resolve: 'Marks the complaint resolved now, without a field visit.',
  escalate_authority:
    'Records the escalation only — nobody outside is contacted.',
  request_information:
    'Records what you need. The citizen is not notified automatically.',
  dismiss: 'Closes the complaint as invalid, duplicate or out of scope.',
}

/** Decisions whose note is the point of the decision. */
const NOTE_REQUIRED: ReadonlySet<AdminDecisionValue> = new Set([
  'request_information',
  'dismiss',
])

const NOTE_LABEL: Record<AdminDecisionValue, string> = {
  assign_cleaner: 'Note for the record',
  resolve: 'Resolution note',
  escalate_authority: 'Why escalate',
  request_information: 'What do you need from the citizen?',
  dismiss: 'Reason for dismissing',
}

interface Receipt {
  result: AdminDecisionResult
  assignment: AssignCleanerResponse | null
  assignError: string | null
}

/**
 * The authoritative decision ("AI recommends, admin decides"): one PUT to
 * /admin/complaints/{id}/decision, plus an optional /assign so an
 * assign_cleaner decision can leave with its cleaner. The photo AI only
 * annotates an option; nothing is preselected.
 */
export default function DecisionPanel({
  item,
  complaintId,
  idError,
  onRetryId,
  hasTask,
  analysis,
  events,
  cleaners,
  token,
  onSaved,
}: {
  item: AdminQueueItem
  complaintId: number | null
  idError: string | null
  onRetryId: () => void
  /** null while the task lookup has not answered yet. */
  hasTask: boolean | null
  /** Latest photo analysis, for the "AI suggests" hint only. */
  analysis: WasteAIAnalysis | null
  events: EventLogEntry[]
  cleaners: KnownCleaner[]
  token: string
  onSaved: () => void
}) {
  const [decision, setDecision] = useState<AdminDecisionValue | null>(null)
  const [note, setNote] = useState('')
  const [cleaner, setCleaner] = useState('')
  const [instructions, setInstructions] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [receipt, setReceipt] = useState<Receipt | null>(null)

  const options = allowedDecisions(item.status, hasTask)
  const history = events.filter(
    (event) => event.activity === 'admin_decision_made',
  )
  const aiSuggests: AdminDecisionValue | null =
    analysis?.ai_status === 'completed' && analysis.escalate_to_authority
      ? 'escalate_authority'
      : null

  function choose(next: AdminDecisionValue) {
    setDecision(next)
    setErrors({})
  }

  function validate() {
    const found: Record<string, string> = {}
    if (!decision) found.decision = 'Choose a decision.'
    if (decision && NOTE_REQUIRED.has(decision) && !note.trim()) {
      found.note =
        decision === 'request_information'
          ? 'Say what information you need.'
          : 'Give the reason for dismissing.'
    }
    if (note.length > 2000) found.note = 'Keep the note under 2000 characters.'
    if (
      decision === 'assign_cleaner' &&
      cleaner.trim() &&
      parseCleanerId(cleaner) === null
    ) {
      found.cleaner =
        'Enter a whole-number user ID, or leave it blank to assign later.'
    }
    return found
  }

  const summary = (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-1.5">
        <WastePill wasteType={item.waste_type} />
        {item.quantity_severity ? (
          <span className="pill">{severityLabel(item.quantity_severity)}</span>
        ) : null}
        <BackendPriorityPill priority={item.priority} />
      </div>
      {history.length > 0 ? <DecisionHistory history={history} /> : null}
    </div>
  )

  if (options.length === 0) {
    const resolution = backendResolution(item.resolution)
    return (
      <SectionCard
        title="Decision"
        meta={`Status: ${item.status.replaceAll('_', ' ')}`}
      >
        <div className="grid gap-3">
          {receipt ? <ReceiptNote receipt={receipt} /> : null}
          <p className="m-0 text-sm muted">
            This case is {item.status.replaceAll('_', ' ')}, so no further
            decision can be made.
          </p>
          {resolution ? (
            <div>
              <span className="kicker">Guidance sent</span>
              <div className="draft-box mt-1">{resolution.text}</div>
            </div>
          ) : null}
          {summary}
        </div>
      </SectionCard>
    )
  }

  return (
    <SectionCard title="Decision" meta="PUT /admin/complaints/{id}/decision">
      <div className="grid gap-4">
        {idError ? (
          <ErrorState
            title="Can't act on this case yet"
            message={`The internal complaint id could not be resolved: ${idError}`}
            onRetry={onRetryId}
          />
        ) : null}
        {receipt ? <ReceiptNote receipt={receipt} /> : null}
        {error ? (
          <ErrorState
            title="Decision was not recorded"
            message={error}
            onReauth={expired ? signOut : undefined}
          />
        ) : null}

        <form
          className="grid gap-4"
          noValidate
          onSubmit={async (event) => {
            event.preventDefault()
            const found = validate()
            setErrors(found)
            if (
              Object.keys(found).length > 0 ||
              !decision ||
              complaintId === null
            ) {
              return
            }
            setSaving(true)
            setError(null)
            try {
              const result = await recordAdminDecision(
                complaintId,
                { decision, note: note.trim() || null },
                token,
              )
              let assignment: AssignCleanerResponse | null = null
              let assignError: string | null = null
              const cleanerId = parseCleanerId(cleaner)
              if (decision === 'assign_cleaner' && cleanerId !== null) {
                try {
                  assignment = await assignCleaner(
                    complaintId,
                    {
                      cleaner_id: cleanerId,
                      notes: instructions.trim() || null,
                    },
                    token,
                  )
                } catch (caught) {
                  assignError =
                    caught instanceof Error
                      ? caught.message
                      : 'Assignment failed.'
                }
              }
              setReceipt({ result, assignment, assignError })
              setDecision(null)
              setNote('')
              setCleaner('')
              setInstructions('')
              onSaved()
            } catch (caught) {
              setExpired(isExpiredSession(caught))
              setError(
                caught instanceof Error
                  ? caught.message
                  : 'The decision failed.',
              )
            } finally {
              setSaving(false)
            }
          }}
        >
          <fieldset className="grid gap-2">
            <legend className="label">
              Outcome
              <span className="req" aria-hidden="true">
                *
              </span>
            </legend>
            <div className="choice-grid">
              {options.map((value) => (
                <label key={value} className="choice">
                  <input
                    type="radio"
                    name="admin-decision"
                    value={value}
                    checked={decision === value}
                    disabled={saving}
                    onChange={() => choose(value)}
                  />
                  <span>
                    <strong className="block text-sm">
                      {decisionLabel(value)}
                      {aiSuggests === value ? (
                        <span className="changed-tag ai-tag">AI suggests</span>
                      ) : null}
                    </strong>
                    <span className="text-xs muted">{DESCRIPTIONS[value]}</span>
                  </span>
                </label>
              ))}
            </div>
            {errors.decision ? (
              <p className="field-error m-0">
                <span aria-hidden="true">!</span>
                <span>{errors.decision}</span>
              </p>
            ) : null}
            {hasTask === null ? (
              <p className="hint m-0">
                “Assign a cleaner” appears once the task lookup answers.
              </p>
            ) : null}
          </fieldset>

          {decision === 'resolve' && hasTask === true ? (
            <Callout tone="warn" title="A cleanup task is still open">
              Resolving now closes the case without a verified proof photo.
            </Callout>
          ) : null}

          {decision === 'assign_cleaner' ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <CleanerPicker
                id="decision-cleaner"
                label="Assign cleaner now (optional)"
                value={cleaner}
                onChange={setCleaner}
                cleaners={cleaners}
                error={errors.cleaner}
                disabled={saving}
              />
              <Field
                label="Instructions for the cleaner"
                htmlFor="decision-instructions"
                hint="Sent with the assignment."
              >
                <input
                  id="decision-instructions"
                  className="input"
                  value={instructions}
                  disabled={saving || !cleaner.trim()}
                  placeholder="e.g. Bring gloves; the bags are torn."
                  onChange={(event) => setInstructions(event.target.value)}
                />
              </Field>
            </div>
          ) : null}

          {decision ? (
            <Field
              label={NOTE_LABEL[decision]}
              htmlFor="decision-note"
              required={NOTE_REQUIRED.has(decision)}
              error={errors.note}
              hint={
                decision === 'assign_cleaner'
                  ? 'Kept with the decision — and saved as the cleaner’s instructions unless you add some above.'
                  : 'Kept with the decision and the case history.'
              }
            >
              <textarea
                id="decision-note"
                className="textarea"
                maxLength={2000}
                value={note}
                disabled={saving}
                aria-invalid={Boolean(errors.note)}
                onChange={(event) => setNote(event.target.value)}
              />
            </Field>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving || complaintId === null || !decision}
            >
              {saving ? <Spinner /> : null}
              {saving
                ? 'Recording…'
                : decision === 'assign_cleaner' &&
                    parseCleanerId(cleaner) !== null
                  ? 'Record & assign'
                  : 'Record decision'}
            </button>
            {complaintId === null && !idError ? (
              <span className="text-xs muted">Resolving the case id…</span>
            ) : null}
          </div>
        </form>

        {history.length > 0 ? <DecisionHistory history={history} /> : null}
      </div>
    </SectionCard>
  )
}

/** Newest first, from the event log — it holds every decision, old and new. */
function DecisionHistory({ history }: { history: EventLogEntry[] }) {
  return (
    <div>
      <span className="kicker">Earlier decisions</span>
      <ul className="m-0 mt-1 grid list-none gap-1.5 p-0">
        {history.slice(0, 5).map((event) => {
          const note = event.meta?.note
          return (
            <li key={event.event_id} className="text-xs">
              <strong>{decisionLabel(event.new_value ?? '')}</strong>
              <span className="muted">
                {' '}
                · {formatDateTime(event.timestamp)}
                {event.actor_id !== null ? ` · admin #${event.actor_id}` : ''}
              </span>
              {typeof note === 'string' && note ? (
                <span className="block muted">“{note}”</span>
              ) : null}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function ReceiptNote({ receipt }: { receipt: Receipt }) {
  const { result, assignment, assignError } = receipt
  return (
    <div className="grid gap-2">
      <Callout tone="ok" title="Decision recorded by the backend" announce>
        {decisionLabel(result.decision)} by {result.decided_by_name} · complaint
        now <span className="mono">{result.complaint_status}</span>.
        {result.cleanup_task && !assignment ? (
          <>
            {' '}
            Task <span className="mono">
              {result.cleanup_task.task_id}
            </span>{' '}
            {result.cleanup_task.assigned_cleaner_id === null
              ? 'is waiting for a cleaner — pick one in the task panel.'
              : 'keeps its current cleaner.'}
          </>
        ) : null}
        {assignment ? (
          <>
            {' '}
            Assigned to{' '}
            {assignment.cleaner_name ?? `#${assignment.assigned_cleaner_id}`} (
            <span className="mono">{assignment.task_id}</span>).
          </>
        ) : null}
      </Callout>
      {assignError ? (
        <Callout tone="warn" title="Recorded, but the cleaner was not assigned">
          {assignError} Assign one from the task panel.
        </Callout>
      ) : null}
    </div>
  )
}
