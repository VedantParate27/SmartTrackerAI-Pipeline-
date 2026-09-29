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
import {
  SEVERITIES,
  WASTE_TYPES,
  allowedDecisions,
  assignCleaner,
  fieldErrors,
  recordAIDecision,
} from '#/lib/api'
import type {
  AIDecisionResponse,
  AIOutput,
  AdminQueueItem,
  AssignCleanerResponse,
  Decision,
  Severity,
  WasteType,
} from '#/lib/api'
import { isExpiredSession, signOut } from '#/lib/auth'
import {
  backendResolution,
  severityLabel,
  wasteLabel,
} from '#/lib/complaint-format'

const isWaste = (value: string | null | undefined): value is WasteType =>
  (WASTE_TYPES as ReadonlyArray<string>).includes(value ?? '')
const isSeverity = (value: string | null | undefined): value is Severity =>
  (SEVERITIES as ReadonlyArray<string>).includes(value ?? '')

interface Receipt {
  decision: AIDecisionResponse
  assignment: AssignCleanerResponse | null
  assignError: string | null
}

function Changed({ show }: { show: boolean }) {
  return show ? <span className="changed-tag">Corrected</span> : null
}

/**
 * The human-in-the-loop form: accept or correct the AI fields, then dispatch
 * a cleaner or resolve with guidance — one POST to /ai-decision, plus an
 * optional /assign so a dispatch leaves with its cleaner in the same step.
 *
 * Mount with `key` = complaint + latest prediction id, so the form re-seeds
 * when a new prediction arrives but keeps its receipt across refetches.
 */
export default function DecisionPanel({
  item,
  complaintId,
  idError,
  onRetryId,
  latest,
  cleaners,
  token,
  onSaved,
}: {
  item: AdminQueueItem
  complaintId: number | null
  idError: string | null
  onRetryId: () => void
  latest: AIOutput | null
  cleaners: KnownCleaner[]
  token: string
  onSaved: () => void
}) {
  const predWaste = latest?.waste_type_pred ?? null
  const predSeverity = latest?.severity_pred ?? null
  const aiWaste = isWaste(predWaste) ? predWaste : null
  const aiSeverity = isSeverity(predSeverity) ? predSeverity : null
  const aiIntervention = latest?.intervention_required_pred ?? null

  const initialIntervention =
    aiIntervention ?? item.intervention_required ?? false
  const [waste, setWaste] = useState<WasteType | ''>(
    aiWaste ?? (isWaste(item.waste_type) ? item.waste_type : ''),
  )
  const [severity, setSeverity] = useState<Severity | ''>(
    aiSeverity ??
      (isSeverity(item.quantity_severity) ? item.quantity_severity : ''),
  )
  const [intervention, setIntervention] = useState(initialIntervention)
  const [decision, setDecision] = useState<Decision>(
    initialIntervention ? 'dispatch' : 'guidance',
  )
  const [guidance, setGuidance] = useState(item.recommended_action ?? '')
  const [notes, setNotes] = useState('')
  const [cleaner, setCleaner] = useState('')
  const [instructions, setInstructions] = useState('')

  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [receipt, setReceipt] = useState<Receipt | null>(null)

  const options = allowedDecisions(item.status)
  const locked = options.length === 0
  const resolution = backendResolution(item.resolution)

  function chooseDecision(next: Decision) {
    setDecision(next)
    // The backend rejects guidance with intervention_required=true (422).
    if (next === 'guidance') setIntervention(false)
  }

  function useSuggestion() {
    if (aiWaste) setWaste(aiWaste)
    if (aiSeverity) setSeverity(aiSeverity)
    if (aiIntervention !== null) {
      setIntervention(aiIntervention)
      setDecision(aiIntervention ? 'dispatch' : 'guidance')
    }
  }

  function validate() {
    const found: Record<string, string> = {}
    if (!waste) found.waste_type = 'Choose the waste type.'
    if (!severity) found.quantity_severity = 'Choose the amount.'
    if (decision === 'guidance' && !guidance.trim()) {
      found.guidance_text = 'Write the guidance the citizen will receive.'
    }
    if (guidance.length > 5000)
      found.guidance_text = 'Keep guidance under 5000 characters.'
    if (notes.length > 2000) found.notes = 'Keep notes under 2000 characters.'
    if (
      decision === 'dispatch' &&
      cleaner.trim() &&
      parseCleanerId(cleaner) === null
    ) {
      found.cleaner =
        'Enter a whole-number user ID, or leave it blank to assign later.'
    }
    return found
  }

  if (locked) {
    return (
      <SectionCard
        title="Decision"
        meta={`Status: ${item.status.replaceAll('_', ' ')}`}
      >
        {receipt ? <ReceiptNote receipt={receipt} /> : null}
        <div className={receipt ? 'mt-3 grid gap-3' : 'grid gap-3'}>
          <p className="m-0 text-sm muted">
            This case is {item.status.replaceAll('_', ' ')}, so no further
            triage decision can be made.
          </p>
          <div className="flex flex-wrap gap-1.5">
            <WastePill wasteType={item.waste_type} />
            {item.quantity_severity ? (
              <span className="pill">
                {severityLabel(item.quantity_severity)}
              </span>
            ) : null}
            <BackendPriorityPill priority={item.priority} />
          </div>
          {resolution ? (
            <div>
              <span className="kicker">Guidance sent</span>
              <div className="draft-box mt-1">{resolution.text}</div>
              <p className="mt-1 mb-0 text-xs muted">
                By {resolution.approver ?? 'an admin'}
              </p>
            </div>
          ) : null}
        </div>
      </SectionCard>
    )
  }

  const form = (
    <form
      className="grid gap-4"
      noValidate
      onSubmit={async (event) => {
        event.preventDefault()
        const found = validate()
        setErrors(found)
        if (
          Object.keys(found).length > 0 ||
          complaintId === null ||
          !waste ||
          !severity
        ) {
          return
        }

        setSaving(true)
        setError(null)
        try {
          // Explicit `corrections` are deliberately not sent: the backend
          // compares against the latest AI output itself, and adding rows
          // for fields with no prediction would inflate correction_count
          // for manual cases in the research dataset.
          const saved = await recordAIDecision(
            complaintId,
            {
              waste_type: waste,
              quantity_severity: severity,
              intervention_required:
                decision === 'guidance' ? false : intervention,
              decision,
              guidance_text: decision === 'guidance' ? guidance.trim() : null,
              notes: notes.trim() || null,
            },
            token,
          )
          let assignment: AssignCleanerResponse | null = null
          let assignError: string | null = null
          const cleanerId = parseCleanerId(cleaner)
          if (decision === 'dispatch' && cleanerId !== null) {
            try {
              assignment = await assignCleaner(
                complaintId,
                { cleaner_id: cleanerId, notes: instructions.trim() || null },
                token,
              )
            } catch (caught) {
              assignError =
                caught instanceof Error ? caught.message : 'Assignment failed.'
            }
          }
          setReceipt({ decision: saved, assignment, assignError })
          onSaved()
        } catch (caught) {
          setExpired(isExpiredSession(caught))
          setErrors(fieldErrors(caught))
          setError(
            caught instanceof Error ? caught.message : 'The decision failed.',
          )
        } finally {
          setSaving(false)
        }
      }}
    >
      {latest ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="m-0 text-sm muted">
            Pre-filled from the AI. Fields you change are recorded as
            corrections.
          </p>
          <button
            type="button"
            className="btn btn-sm"
            disabled={saving}
            onClick={useSuggestion}
          >
            Reset to AI suggestion
          </button>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label={
            <>
              Waste type
              <Changed show={aiWaste !== null && waste !== aiWaste} />
            </>
          }
          htmlFor="decision-waste"
          required
          error={errors.waste_type}
        >
          <select
            id="decision-waste"
            className="select"
            value={waste}
            disabled={saving}
            aria-invalid={Boolean(errors.waste_type)}
            onChange={(event) => setWaste(event.target.value as WasteType | '')}
          >
            <option value="">Choose…</option>
            {WASTE_TYPES.map((type) => (
              <option key={type} value={type}>
                {wasteLabel(type)}
                {type === aiWaste ? ' (AI)' : ''}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={
            <>
              Amount
              <Changed show={aiSeverity !== null && severity !== aiSeverity} />
            </>
          }
          htmlFor="decision-severity"
          required
          error={errors.quantity_severity}
        >
          <select
            id="decision-severity"
            className="select"
            value={severity}
            disabled={saving}
            aria-invalid={Boolean(errors.quantity_severity)}
            onChange={(event) =>
              setSeverity(event.target.value as Severity | '')
            }
          >
            <option value="">Choose…</option>
            {SEVERITIES.map((value) => (
              <option key={value} value={value}>
                {severityLabel(value)}
                {value === aiSeverity ? ' (AI)' : ''}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <fieldset className="grid gap-2">
        <legend className="label">
          Outcome
          <span className="req" aria-hidden="true">
            *
          </span>
        </legend>
        <div className="choice-grid">
          <label className="choice">
            <input
              type="radio"
              name="decision"
              value="dispatch"
              checked={decision === 'dispatch'}
              disabled={saving || !options.includes('dispatch')}
              onChange={() => chooseDecision('dispatch')}
            />
            <span>
              <strong className="block text-sm">Dispatch a cleaner</strong>
              <span className="text-xs muted">
                Creates a cleanup task. The cleaner must upload photo proof.
              </span>
            </span>
          </label>
          <label className="choice">
            <input
              type="radio"
              name="decision"
              value="guidance"
              checked={decision === 'guidance'}
              disabled={saving || !options.includes('guidance')}
              onChange={() => chooseDecision('guidance')}
            />
            <span>
              <strong className="block text-sm">Send disposal guidance</strong>
              <span className="text-xs muted">
                Resolves now with instructions for the citizen. No field visit.
              </span>
            </span>
          </label>
        </div>
      </fieldset>

      <label className="check-row" htmlFor="decision-intervention">
        <input
          id="decision-intervention"
          type="checkbox"
          checked={decision === 'guidance' ? false : intervention}
          disabled={saving || decision === 'guidance'}
          onChange={(event) => {
            setIntervention(event.target.checked)
            if (event.target.checked) setDecision('dispatch')
          }}
        />
        <span>
          Cleaner intervention required
          <Changed
            show={
              aiIntervention !== null &&
              (decision === 'guidance' ? false : intervention) !==
                aiIntervention
            }
          />
          {decision === 'guidance' ? (
            <span className="block text-xs muted">
              Guidance means the citizen handles it, so this is off.
            </span>
          ) : null}
        </span>
      </label>

      {decision === 'guidance' ? (
        <Field
          label="Guidance for the citizen"
          htmlFor="decision-guidance"
          required
          error={errors.guidance_text}
          hint="Stored as the approved response and resolves the complaint."
        >
          <textarea
            id="decision-guidance"
            className="textarea"
            maxLength={5000}
            value={guidance}
            disabled={saving}
            aria-invalid={Boolean(errors.guidance_text)}
            placeholder="e.g. Please put wet waste in the green bin at the corner of Market Road."
            onChange={(event) => setGuidance(event.target.value)}
          />
        </Field>
      ) : (
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
              placeholder="e.g. Bring gloves; batteries are leaking."
              onChange={(event) => setInstructions(event.target.value)}
            />
          </Field>
        </div>
      )}

      <Field
        label="Internal notes"
        htmlFor="decision-notes"
        hint="Optional. Kept with the decision, not shown to the citizen."
        error={errors.notes}
      >
        <input
          id="decision-notes"
          className="input"
          maxLength={2000}
          value={notes}
          disabled={saving}
          onChange={(event) => setNotes(event.target.value)}
        />
      </Field>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={saving || complaintId === null}
        >
          {saving ? <Spinner /> : null}
          {saving
            ? 'Saving…'
            : decision === 'dispatch'
              ? parseCleanerId(cleaner) !== null
                ? 'Dispatch & assign'
                : 'Dispatch'
              : 'Send guidance & resolve'}
        </button>
        {complaintId === null && !idError ? (
          <span className="text-xs muted">Resolving the case id…</span>
        ) : null}
      </div>
    </form>
  )

  const dispatched = item.status.toLowerCase() === 'in_progress'

  return (
    <SectionCard
      title="Decision"
      meta="POST /admin/complaints/{id}/ai-decision"
    >
      {idError ? (
        <div className="mb-4">
          <ErrorState
            title="Can't act on this case yet"
            message={`The internal complaint id could not be resolved: ${idError}`}
            onRetry={onRetryId}
          />
        </div>
      ) : null}

      {receipt ? (
        <div className="mb-4">
          <ReceiptNote receipt={receipt} />
        </div>
      ) : null}

      {error ? (
        <div className="mb-4">
          <ErrorState
            title="Decision was not saved"
            message={error}
            onReauth={expired ? signOut : undefined}
          />
        </div>
      ) : null}

      {dispatched ? (
        <div className="grid gap-3">
          <p className="m-0 text-sm">
            <strong>Dispatched.</strong>{' '}
            <span className="muted">
              The cleanup task below tracks the field work.
            </span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            <WastePill wasteType={item.waste_type} />
            {item.quantity_severity ? (
              <span className="pill">
                {severityLabel(item.quantity_severity)}
              </span>
            ) : null}
            <BackendPriorityPill priority={item.priority} />
          </div>
          {/* Re-deciding is allowed, but each submission writes another
              decision into the research event log, so it is opt-in. */}
          <details>
            <summary className="cursor-pointer text-sm font-bold">
              Revise the decision
            </summary>
            <div className="mt-3">{form}</div>
          </details>
        </div>
      ) : (
        form
      )}
    </SectionCard>
  )
}

function ReceiptNote({ receipt }: { receipt: Receipt }) {
  const { decision, assignment, assignError } = receipt
  return (
    <div className="grid gap-2">
      <Callout tone="ok" title="Decision saved by the backend">
        Now <span className="mono">{decision.status}</span> at{' '}
        <span className="mono">{decision.priority}</span> priority ·{' '}
        {decision.corrections_recorded} corrected ·{' '}
        {decision.acceptance_rate_fields} accepted
        {decision.review_completed ? ' · review completed' : ''}.
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
        <Callout
          tone="warn"
          title="Dispatched, but the cleaner was not assigned"
        >
          {assignError} Assign one from the cleanup task panel.
        </Callout>
      ) : null}
    </div>
  )
}
