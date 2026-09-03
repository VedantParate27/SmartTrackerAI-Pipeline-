import { percent } from './format'

/**
 * The AI-facing fields on AdminQueueItem are declared `Any` / `[]` by
 * backend/schemas.py, so every reader here tolerates a missing value, a plain
 * string, or an object envelope, and returns null rather than a placeholder
 * when the backend produced nothing.
 */
function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null
    ? (value as Record<string, unknown>)
    : null
}

function firstString(body: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const candidate = body[key]
    if (typeof candidate === 'string' && candidate.trim()) return candidate
  }
  return null
}

/** Accept a plain response string or a common `{ text: string }` envelope. */
export function backendText(value: unknown) {
  if (typeof value === 'string' && value.trim()) return value
  const body = record(value)
  if (!body) return null
  return firstString(body, ['text', 'response', 'content', 'draft'])
}

/** Display either a 0–1 score or an already-percent value without guessing. */
export function backendConfidence(value: unknown) {
  const numeric =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && value.trim()
        ? Number(value)
        : Number.NaN
  if (Number.isFinite(numeric)) {
    return numeric >= 0 && numeric <= 1 ? percent(numeric) : `${numeric}%`
  }
  return typeof value === 'string' && value.trim() ? value : null
}

/** Category from AdminQueueItem.classification, as a string or an envelope. */
export function backendCategory(classification: unknown) {
  if (typeof classification === 'string' && classification.trim()) {
    return classification
  }
  const body = record(classification)
  if (!body) return null
  return firstString(body, ['category', 'label', 'name', 'value'])
}

/** Confidence carried alongside the category, when the backend returns one. */
export function backendClassificationConfidence(classification: unknown) {
  const body = record(classification)
  if (!body) return null
  return backendConfidence(body.confidence ?? body.score)
}

/** Department suggested by classification, distinct from the assigned one. */
export function backendSuggestedDepartment(classification: unknown) {
  const body = record(classification)
  if (!body) return null
  return firstString(body, ['department', 'routed_department'])
}

export function backendEntityLabel(entity: unknown) {
  if (typeof entity === 'string') return entity
  const body = record(entity)
  if (!body) return 'Unrecognized entity'
  const type = typeof body.type === 'string' ? body.type : 'Entity'
  const value =
    typeof body.value === 'string'
      ? body.value
      : typeof body.normalized === 'string'
        ? body.normalized
        : 'No value'
  return `${type}: ${value}`
}

export function backendEntityConfidence(entity: unknown) {
  return backendConfidence(record(entity)?.confidence)
}

export function backendEvidenceLabel(evidence: unknown) {
  if (typeof evidence === 'string') return evidence
  const body = record(evidence)
  if (!body) return 'Unlabelled evidence'
  return (
    firstString(body, ['title', 'source', 'document', 'policy_id', 'id']) ??
    'Unlabelled evidence'
  )
}

export function backendEvidenceQuote(evidence: unknown) {
  const body = record(evidence)
  if (!body) return null
  return firstString(body, ['quote', 'snippet', 'text', 'chunk'])
}

/**
 * AdminQueueItem.resolution is produced by the Complaint.resolution property in
 * backend/models.py as `{ text, approver, sentAt }`, but the schema types it as
 * `Any`, so it is read defensively here too.
 */
export function backendResolution(value: unknown) {
  const text = backendText(value)
  if (!text) return null
  const body = record(value) ?? {}
  return {
    text,
    approver: firstString(body, ['approver', 'approved_by']),
    sentAt: firstString(body, ['sentAt', 'approved_at', 'sent_at']),
  }
}
