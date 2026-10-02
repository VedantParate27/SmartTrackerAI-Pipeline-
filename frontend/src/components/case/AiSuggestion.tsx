import { Callout, ConfidenceBadge, SectionCard } from '#/components/ui'
import type { AICorrection, AIOutput } from '#/lib/api'
import {
  backendConfidence,
  humanize,
  reviewReasonLabel,
  severityLabel,
  wasteLabel,
} from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'

function yesNo(value: boolean | null) {
  return value === null ? null : value ? 'Yes' : 'No'
}

/**
 * The latest text-model prediction the AI team posted to /ai-output — the
 * research triage model, separate from the photo AI. Read-only: decisions now
 * go through PUT /decision, which records no corrections against it. Render
 * only when there is at least one output.
 */
export function AiSuggestion({ outputs }: { outputs: AIOutput[] }) {
  const latest = outputs.at(-1)
  if (!latest) return null

  return (
    <SectionCard
      title="Text-AI triage"
      meta={`${latest.model_name} ${latest.model_version} · ${formatDateTime(latest.predicted_at)}`}
    >
      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <ConfidenceBadge
            confidence={latest.confidence}
            threshold={latest.threshold_used}
          />
          <span className="text-xs muted">
            Threshold {backendConfidence(latest.threshold_used)}
            {latest.latency_ms !== null ? ` · ${latest.latency_ms} ms` : ''}
          </span>
        </div>

        <div className="ai-grid">
          <div className="ai-cell">
            <span className="kicker">Waste type</span>
            <p className="ai-value m-0">
              {wasteLabel(latest.waste_type_pred) ?? 'Not predicted'}
            </p>
          </div>
          <div className="ai-cell">
            <span className="kicker">Amount</span>
            <p className="ai-value m-0">
              {severityLabel(latest.severity_pred) ?? 'Not predicted'}
            </p>
          </div>
          <div className="ai-cell">
            <span className="kicker">Cleaner needed</span>
            <p className="ai-value m-0">
              {yesNo(latest.intervention_required_pred) ?? 'Not predicted'}
            </p>
          </div>
        </div>

        {latest.escalated ? (
          <Callout tone="warn" title="Escalated for human review">
            {reviewReasonLabel(latest.escalation_reason) ??
              'The escalation gate flagged this prediction.'}
            .
          </Callout>
        ) : (
          <p className="m-0 text-sm muted">
            Confident and not hazardous, so the escalation gate let it through.
          </p>
        )}

        {latest.model_name === 'seed_simulated_triage' ? (
          <p className="m-0 text-xs subtle">
            This is a seeded placeholder prediction for workflow testing, not a
            real model result.
          </p>
        ) : null}

        {outputs.length > 1 ? (
          <p className="m-0 text-xs subtle">
            {outputs.length} predictions on record; the latest is shown.
          </p>
        ) : null}
      </div>
    </SectionCard>
  )
}

/** Stored accept/correct records — the evidence the research evaluates. */
export function CorrectionHistory({
  corrections,
}: {
  corrections: AICorrection[]
}) {
  if (corrections.length === 0) {
    return (
      <p className="m-0 text-sm muted">
        No decisions recorded against an AI prediction yet.
      </p>
    )
  }
  return (
    <ul className="m-0 grid list-none gap-2 p-0">
      {corrections.map((entry) => {
        const accepted = entry.ai_value === entry.admin_value
        return (
          <li key={entry.id} className="entity-row">
            <span className="min-w-0">
              <strong className="block">{humanize(entry.field_name)}</strong>
              <span className="text-xs muted">
                AI {entry.ai_value ?? '—'} → Admin {entry.admin_value ?? '—'}
              </span>
            </span>
            <span
              className="pill shrink-0"
              data-tone={accepted ? 'ok' : 'warn'}
            >
              {accepted ? 'Accepted' : 'Corrected'}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
