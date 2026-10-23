import { percent } from './format'

/** Display labels for the backend's closed vocabularies. Unknown values fall back to a humanized form. */
const WASTE_LABELS: Record<string, string> = {
  dry: 'Dry waste',
  wet: 'Wet waste',
  e_waste: 'E-waste',
  medical: 'Medical waste',
  hazardous: 'Hazardous waste',
  bulk: 'Bulk waste',
}

const SEVERITY_LABELS: Record<string, string> = {
  small: 'Small',
  medium: 'Medium',
  large: 'Large',
}

const REVIEW_REASON_LABELS: Record<string, string> = {
  low_confidence: 'Low AI confidence',
  hazardous_waste: 'Hazardous or medical waste',
  missing_prediction: 'AI prediction missing',
}

const ACTIVITY_LABELS: Record<string, string> = {
  complaint_created: 'Complaint submitted',
  ai_prediction_generated: 'AI prediction received',
  human_review_required: 'Human review required',
  human_review_completed: 'Human review completed',
  admin_decision_made: 'Admin decision',
  dispatch_decided: 'Dispatch chosen',
  guidance_decided: 'Guidance sent',
  cleaner_assigned: 'Cleaner assigned',
  cleaner_reassigned: 'Cleaner reassigned',
  task_started: 'Cleanup started',
  proof_submitted: 'Proof uploaded',
  proof_verified: 'Proof verified',
  proof_rejected: 'Proof rejected',
  complaint_resolved: 'Complaint resolved',
  complaint_closed: 'Complaint closed',
  complaint_updated: 'Complaint updated',
  ai_correction_recorded: 'AI value corrected',
}

export function humanize(value: string) {
  const text = value.replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function label(map: Record<string, string>, value: string | null | undefined) {
  if (!value) return null
  return map[value.toLowerCase()] ?? humanize(value)
}

export const wasteLabel = (value: string | null | undefined) =>
  label(WASTE_LABELS, value)
export const severityLabel = (value: string | null | undefined) =>
  label(SEVERITY_LABELS, value)
export const reviewReasonLabel = (value: string | null | undefined) =>
  label(REVIEW_REASON_LABELS, value)
export const activityLabel = (value: string) =>
  label(ACTIVITY_LABELS, value) ?? value

export function triageModeLabel(value: string | null | undefined) {
  if (value === 'ai_assisted') return 'AI-assisted'
  if (value === 'manual') return 'Manual'
  return 'Not triaged'
}

/* The photo AI has its own vocabulary, returned verbatim by the backend. */
const AI_WASTE_LABELS: Record<string, string> = {
  wet: 'Wet waste',
  dry: 'Dry waste',
  hazardous: 'Hazardous waste',
  sanitary: 'Sanitary waste',
  e_waste: 'E-waste',
  mixed: 'Mixed waste',
  none: 'No waste visible',
}

const AI_SEVERITY_LABELS: Record<string, string> = {
  domestic: 'Household amount',
  moderate: 'Moderate pile',
  dump_scale: 'Dump-scale',
  none: 'Nothing to clear',
}

const DECISION_LABELS: Record<string, string> = {
  assign_cleaner: 'Assign a cleaner',
  resolve: 'Resolve',
  escalate_authority: 'Escalate to authority',
  request_information: 'Request information',
  dismiss: 'Dismiss',
  // Recorded by the earlier ai-decision endpoint.
  dispatch: 'Dispatch',
  guidance: 'Send guidance',
}

export const aiWasteLabel = (value: string | null | undefined) =>
  label(AI_WASTE_LABELS, value)
export const aiSeverityLabel = (value: string | null | undefined) =>
  label(AI_SEVERITY_LABELS, value)
export const decisionLabel = (value: string) =>
  label(DECISION_LABELS, value) ?? value

/** "low_waste_type_confidence: 0.42" -> "Low waste type confidence · 42%". */
export function reviewReasonText(reason: unknown) {
  const text = typeof reason === 'string' ? reason : JSON.stringify(reason)
  const match = /^([a-z_]+):\s*(.+)$/i.exec(text)
  if (!match) return humanize(text)
  const value = backendConfidence(match[2]) ?? match[2]
  return `${humanize(match[1])} · ${value}`
}

const AI_ERROR_MESSAGES: Record<string, string> = {
  AI_SOURCE_NOT_CONFIGURED: 'The AI service is not set up on this server.',
  AI_SOURCE_NOT_FOUND: 'The AI service is not set up on this server.',
  AI_SETUP_FAILED: 'The AI service could not start.',
  AI_DISABLED: 'AI checks are switched off on this server.',
  AI_TIMEOUT: 'The AI took too long to answer.',
  AI_INVALID_RESPONSE: 'The AI returned an answer that could not be read.',
  IMAGE_UNAVAILABLE: 'The stored photo could not be found.',
  IMAGE_UNREADABLE: 'The stored photo could not be read.',
  BEFORE_IMAGE_UNAVAILABLE: 'There is no complaint photo to compare against.',
  AFTER_IMAGE_UNAVAILABLE: 'The proof photo could not be found.',
  AI_RUN_EXCEPTION: 'The AI run failed unexpectedly.',
  AI_UNKNOWN_ERROR: 'The AI run failed for an unknown reason.',
}

/** One errors_json entry ({ error, details }) as a code and a plain message. */
export function aiErrorInfo(entry: unknown) {
  const body = record(entry)
  const code =
    typeof body?.error === 'string'
      ? body.error
      : typeof entry === 'string'
        ? entry
        : 'AI_UNKNOWN_ERROR'
  const details =
    typeof body?.details === 'string' && body.details ? body.details : null
  return {
    code,
    message: AI_ERROR_MESSAGES[code] ?? humanize(code.toLowerCase()),
    details,
  }
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
  return null
}

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

/**
 * AdminQueueItem.resolution is produced by the Complaint.resolution property in
 * backend/models.py as `{ text, approver, sentAt }` — the latest approved
 * response, which is where guidance text lands — but the schema types it as
 * `dict`, so it is read defensively.
 */
export function backendResolution(value: unknown) {
  const body = record(value)
  if (!body) return null
  const text = firstString(body, ['text', 'response', 'content'])
  if (!text) return null
  return {
    text,
    approver: firstString(body, ['approver', 'approved_by']),
    sentAt: firstString(body, ['sentAt', 'approved_at', 'sent_at']),
  }
}

/** A map link for a coordinate pair, or null when the backend sent none. */
export function mapsUrl(latitude: number | null, longitude: number | null) {
  if (latitude === null || longitude === null) return null
  return `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=17/${latitude}/${longitude}`
}

export function formatCoordinates(
  latitude: number | null,
  longitude: number | null,
) {
  if (latitude === null || longitude === null) return null
  return `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`
}
