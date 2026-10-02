import { secondsSince } from './format'

export const API_BASE_URL = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/$/, '')

/* ------------------------------------------------------------------ *
 * Closed vocabularies — mirror backend/taxonomy.py (§0 of
 * backend/INTEGRATION_CONTRACTS.md). The backend rejects anything else
 * with 422, and exposes no endpoint listing them, so they live here once.
 * ------------------------------------------------------------------ */

export const WASTE_TYPES = [
  'dry',
  'wet',
  'e_waste',
  'medical',
  'hazardous',
  'bulk',
] as const
export type WasteType = (typeof WASTE_TYPES)[number]

export const SEVERITIES = ['small', 'medium', 'large'] as const
export type Severity = (typeof SEVERITIES)[number]

export type TriageMode = 'manual' | 'ai_assisted'

export const COMPLAINT_STATUSES = [
  'pending',
  'in_progress',
  'resolved',
  'closed',
] as const
export type ComplaintStatus = (typeof COMPLAINT_STATUSES)[number]

export const PRIORITIES = ['low', 'medium', 'high', 'urgent'] as const
export type Priority = (typeof PRIORITIES)[number]

export const EVENT_ACTIVITIES = [
  'complaint_created',
  'ai_prediction_generated',
  'human_review_required',
  'human_review_completed',
  'admin_decision_made',
  'dispatch_decided',
  'guidance_decided',
  'cleaner_assigned',
  'cleaner_reassigned',
  'task_started',
  'proof_submitted',
  'proof_verified',
  'proof_rejected',
  'complaint_resolved',
  'complaint_closed',
  'complaint_updated',
  'ai_correction_recorded',
] as const

export const ACTOR_ROLES = [
  'citizen',
  'ai_system',
  'admin',
  'cleaner',
  'system',
] as const

/* ------------------------------------------------------------------ *
 * Auth
 * ------------------------------------------------------------------ */

export interface RegisterRequest {
  name: string
  email: string
  password: string
  role?: 'citizen'
  department?: string | null
}

export interface RegisterResponse {
  id: number
  name: string
  email: string
  role: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer' | string
}

/* ------------------------------------------------------------------ *
 * Complaints
 * ------------------------------------------------------------------ */

/** Exact request body accepted by POST /complaints/. Priority is derived server-side. */
export interface CreateComplaintRequest {
  complaint_text: string
  phone?: string | null
  waste_type?: WasteType | null
  waste_context?: string | null
  quantity_severity?: Severity | null
  intervention_required?: boolean | null
  latitude?: number | null
  longitude?: number | null
  address_text?: string | null
}

/** State of the latest waste-photo analysis; null when no photo was ever analysed. */
export type AIStatus = 'pending' | 'completed' | 'failed'

/**
 * Exact ComplaintResponse returned by POST /complaints/, /complaints/my,
 * /complaints/{id} and POST /complaints/{id}/image.
 *
 * Once a photo has been analysed (`ai_status` not null), the backend merges
 * the AI summary into this body, and its `waste_type` overwrites the
 * complaint's own: the AI's verbatim value ("sanitary", "mixed"…) when
 * completed, null while pending or failed. Only trust `waste_type` here as
 * the complaint's type when `ai_status` is null — see citizenWasteType().
 */
export interface ComplaintResponse {
  tracking_id: string
  complaint_text: string
  status: string
  priority: string
  department: string | null
  waste_type: string | null
  waste_context: string | null
  quantity_severity: string | null
  recommended_action: string | null
  intervention_required: boolean | null
  latitude: number | null
  longitude: number | null
  address_text: string | null
  triage_mode: TriageMode | null
  review_required: boolean | null
  review_reason: string | null
  resolved_at: string | null
  source: string
  ai_status: AIStatus | null
  created_at: string
}

/** The complaint's own waste type, or null when the response's value is the AI's. */
export function citizenWasteType(item: ComplaintResponse) {
  return item.ai_status === null ? item.waste_type : null
}

/**
 * review_required is set by the text-AI triage and cleared only by the legacy
 * ai-decision route, which the UI no longer calls, so on a resolved or closed
 * case it is stale. Only open cases count as waiting for review.
 */
export function needsReview(item: {
  review_required: boolean | null
  status: string
}) {
  const status = item.status.toLowerCase()
  return (
    Boolean(item.review_required) &&
    (status === 'pending' || status === 'in_progress')
  )
}

/**
 * Exact request body accepted by PUT /admin/complaints/{id}. Send only what
 * changes; at least one field is required. A blank department is read as "no
 * change", so a department can be replaced but never cleared.
 */
export interface AdminComplaintUpdateRequest {
  status?: ComplaintStatus
  priority?: Priority
  department?: string
}

/**
 * The AdminQueueItem body GET /admin/queue and /admin/queue/{id} actually
 * return, verified against the running app and its /openapi.json.
 *
 * The schema declares renamed fields (id, requester_name, contact, text,
 * submitted_at, assigned_department), but Pydantic v2 treats `alias=` as the
 * serialization alias too, so the database column names reach the wire. It
 * also omits `source` and `resolved_at`, which INTEGRATION_CONTRACTS.md says
 * the queue carries. These names track the real response.
 *
 * classification/entities/evidence/ai_draft are placeholders that are always
 * empty; real AI output comes from /admin/complaints/{id}/ai-output.
 */
export interface AdminQueueItem {
  tracking_id: string
  name: string
  email: string
  complaint_text: string
  status: string
  priority: string
  language: string
  created_at: string
  updated_at: string
  department: string | null
  waste_type: string | null
  waste_context: string | null
  quantity_severity: string | null
  recommended_action: string | null
  intervention_required: boolean | null
  latitude: number | null
  longitude: number | null
  address_text: string | null
  triage_mode: TriageMode | null
  review_required: boolean | null
  review_reason: string | null
  channel: string
  classification: unknown
  entities: unknown[]
  evidence: unknown[]
  ai_draft: unknown
  edited_draft: string | null
  resolution: unknown
  closure_reason: string | null
  duplicate_of: string | null
  comments: unknown[]
  audit: unknown[]
  attachments: unknown[]
}

/* ------------------------------------------------------------------ *
 * Waste-photo AI — advisory analysis of the citizen's photo
 * ------------------------------------------------------------------ */

/**
 * Background AI runs live inside the API process (FastAPI BackgroundTasks):
 * a server restart drops them, and seeded proofs never get one, so their rows
 * stay unfinished for good. The backend gives up after WASTE_AI_TIMEOUT_S
 * (120 s); a run still open ten minutes after it started is treated as lost —
 * no spinner, no polling.
 */
export function aiRunLost(startedAt: string) {
  return secondsSince(startedAt) > 600
}

/** Mirrors backend/image_utils.py: content-sniffed JPEG/PNG/WebP, 8 MB cap. */
export const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024

/**
 * Exact WasteAIResultResponse from GET /complaints/{id}/ai-analysis. One row
 * per photo upload. The AI's vocabulary is returned verbatim and differs from
 * the complaint taxonomy: waste_type wet|dry|hazardous|sanitary|e_waste|mixed|
 * none, severity domestic|moderate|dump_scale|none. Predictions are null while
 * pending and on failure; errors_json then explains why.
 */
export interface WasteAIAnalysis {
  id: number
  complaint_id: number
  created_at: string
  ai_status: AIStatus
  image_url: string | null
  image_mime_type: string | null
  image_usable: boolean | null
  unusable_reason: string | null
  waste_type: string | null
  waste_type_confidence: number | null
  severity: string | null
  severity_confidence: number | null
  reasoning: string | null
  follow_up_question: string | null
  recurring_flag: boolean | null
  prior_reports_count: number | null
  radius_m: number | null
  escalate_to_authority: boolean | null
  needs_human_review: boolean | null
  review_reasons_json: string | null
  disposal_guidance: string | null
  errors_json: string | null
  model_name: string | null
  model_version: string | null
  latency_ms: number | null
}

/* ------------------------------------------------------------------ *
 * Admin decision — "AI recommends, admin decides"
 * ------------------------------------------------------------------ */

export const ADMIN_DECISIONS = [
  'assign_cleaner',
  'resolve',
  'escalate_authority',
  'request_information',
  'dismiss',
] as const
export type AdminDecisionValue = (typeof ADMIN_DECISIONS)[number]

/** Exact request body accepted by PUT /admin/complaints/{id}/decision. */
export interface AdminDecisionRequest {
  decision: AdminDecisionValue
  note?: string | null
}

export interface AdminDecisionSummary {
  id: number
  decision: string
  admin_id: number
  /** Declared by the schema but never populated by the backend — always null. */
  admin_name: string | null
  note: string | null
  created_at: string
}

/** Exact AdminAIReviewResponse from GET /admin/complaints/{id}/ai-review. */
export interface AdminAIReview {
  complaint_id: number
  tracking_id: string
  complaint_status: string
  complaint_text: string
  waste_context: string | null
  latitude: number | null
  longitude: number | null
  address_text: string | null
  complaint_created_at: string
  analysis: WasteAIAnalysis
  review_reasons: unknown[] | null
  errors: unknown[] | null
  latest_decision: AdminDecisionSummary | null
}

export interface CleanupTaskHandoff {
  task_id: string
  status: string
  assigned_cleaner_id: number | null
}

/** Exact AdminDecisionResult from PUT /admin/complaints/{id}/decision. */
export interface AdminDecisionResult {
  complaint_id: number
  tracking_id: string
  decision: string
  note: string | null
  decided_by: number
  decided_by_name: string
  decided_at: string
  complaint_status: string
  /** Set by assign_cleaner: the task is created with no cleaner yet. */
  cleanup_task: CleanupTaskHandoff | null
  ai_status: AIStatus | null
}

/* ------------------------------------------------------------------ *
 * Text-AI triage (research model) — read-only in the UI
 * ------------------------------------------------------------------ */

/** Exact AIOutputResponse from GET /admin/complaints/{id}/ai-output. */
export interface AIOutput {
  id: number
  complaint_id: number
  waste_type_pred: string | null
  severity_pred: string | null
  intervention_required_pred: boolean | null
  confidence: number | null
  model_name: string
  model_version: string
  threshold_used: number
  escalated: boolean
  escalation_reason: string | null
  latency_ms: number | null
  predicted_at: string
}

/** Exact AICorrectionResponse from GET /admin/complaints/{id}/corrections. */
export interface AICorrection {
  id: number
  complaint_id: number
  field_name: string
  ai_value: string | null
  admin_value: string | null
  admin_id: number
  created_at: string
}

/* ------------------------------------------------------------------ *
 * Cleaner tasks + proof
 * ------------------------------------------------------------------ */

export interface AssignCleanerRequest {
  cleaner_id: number
  notes?: string | null
}

export interface AssignCleanerResponse {
  task_id: string
  tracking_id: string
  assigned_cleaner_id: number | null
  cleaner_name: string | null
  status: string
  assigned_at: string
}

export interface CleanupProof {
  id: number
  task_id: number
  image_url: string
  uploaded_by: number
  uploaded_at: string
  verification_status: string
  verified_by: number | null
  verified_at: string | null
  rejection_reason: string | null
}

/** Exact CleanerTaskResponse from /cleaner/tasks and /cleaner/tasks/{id}. */
export interface CleanerTask {
  task_id: string
  tracking_id: string
  status: string
  assigned_at: string
  completed_at: string | null
  notes: string | null
  complaint_text: string
  waste_type: string | null
  quantity_severity: string | null
  recommended_action: string | null
  latitude: number | null
  longitude: number | null
  address_text: string | null
  proofs: CleanupProof[]
}

export interface VerifyProofRequest {
  approved: boolean
  rejection_reason?: string | null
  next_status?: 'resolved' | 'closed' | null
}

export interface VerifyProofResult {
  proof_id: number
  task_id: string
  tracking_id: string
  verification_status: string
  task_status: string
  complaint_status: string
  verified_at: string
}

/**
 * One proof as the admin review sees it. The ai_* fields are the background
 * before/after comparison — advisory only; verify/reject stays human. All are
 * null until the comparison has run (ai_processed_at set), and on failure
 * ai_errors explains why.
 */
export interface ProofReviewItem {
  id: number
  image_url: string
  before_image_url: string | null
  uploaded_by: number
  uploaded_at: string
  verification_status: string
  verified_by: number | null
  verified_at: string | null
  rejection_reason: string | null
  ai_after_image_usable: boolean | null
  ai_unusable_reason: string | null
  ai_cleanup_appears_complete: boolean | null
  ai_confidence: number | null
  ai_reasoning: string | null
  ai_admin_review_recommended: boolean | null
  ai_processed_at: string | null
  ai_errors: unknown[] | null
}

/** Exact AdminProofReviewResponse from GET /admin/tasks/{task_id}/proof. */
export interface AdminProofReview {
  task_id: string
  task_status: string
  /** Null after an assign_cleaner decision until a cleaner is picked. */
  task_assigned_cleaner_id: number | null
  assigned_at: string
  completed_at: string | null
  complaint_id: number
  tracking_id: string
  complaint_text: string
  complaint_status: string
  latitude: number | null
  longitude: number | null
  address_text: string | null
  proofs: ProofReviewItem[]
}

/* ------------------------------------------------------------------ *
 * Event log + mining dataset
 * ------------------------------------------------------------------ */

export interface EventLogEntry {
  event_id: number
  case_id: string
  activity: string
  actor_id: number | null
  actor_role: string | null
  timestamp: string
  old_value: string | null
  new_value: string | null
  meta: Record<string, unknown> | null
}

export interface EventFilters {
  case_id?: string
  activity?: string
  actor_role?: string
  limit?: number
}

export interface MiningRow {
  complaint_id: number
  tracking_id: string
  cleaner_assigned: number | null
  [field: string]: unknown
}

export interface MiningDataset {
  fieldnames: string[]
  count: number
  rows: MiningRow[]
}

/* ------------------------------------------------------------------ *
 * Lifecycle rules mirrored for the UI
 * ------------------------------------------------------------------ */

/**
 * Decisions the panel offers. Mirrors record_admin_decision + VALID_TRANSITIONS
 * in backend/routers/admin.py: assign_cleaner moves to in_progress, resolve to
 * resolved, dismiss to closed; escalate/request-information record only. Only
 * open cases are offered decisions, and assign_cleaner is hidden unless no
 * task is known to exist (`null` = still checking): on a live task the follow-
 * up /assign would reset it to "assigned". The backend stays the authority and
 * its 400 is shown verbatim.
 */
export function allowedDecisions(
  status: string,
  hasTask: boolean | null,
): AdminDecisionValue[] {
  const value = status.toLowerCase()
  if (value !== 'pending' && value !== 'in_progress') return []
  return ADMIN_DECISIONS.filter(
    (decision) => !(decision === 'assign_cleaner' && hasTask !== false),
  )
}

/**
 * Statuses PUT /admin/complaints/{id} can move a complaint to — VALID_TRANSITIONS
 * in backend/routers/admin.py: forward only, and closed is final.
 */
export function statusMoves(status: string): ComplaintStatus[] {
  const index = COMPLAINT_STATUSES.indexOf(
    status.toLowerCase() as ComplaintStatus,
  )
  return index === -1 ? [] : COMPLAINT_STATUSES.slice(index + 1)
}

/* ------------------------------------------------------------------ *
 * Transport
 * ------------------------------------------------------------------ */

interface ValidationIssue {
  loc?: Array<string | number>
  msg?: string
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly issues: ValidationIssue[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/**
 * Turn a 422 body into `{ field: message }` so a rejected value can be shown
 * under the input that caused it instead of as one long banner. FastAPI sends
 * `loc: ["body", "complaint_text"]`, so the field name is the last segment.
 */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {}
  const mapped: Record<string, string> = {}
  for (const issue of error.issues) {
    const field = issue.loc?.at(-1)
    if (typeof field !== 'string' || field === 'body' || !issue.msg) continue
    // Pydantic prefixes messages with "Value error, "; it adds nothing here.
    mapped[field] = issue.msg.replace(/^Value error,\s*/i, '')
  }
  return mapped
}

/** Photo uploads answer 422 with a bare code (backend/image_utils.py). */
const DETAIL_CODES: Record<string, string> = {
  IMAGE_REQUIRED: 'Choose a photo to upload.',
  IMAGE_EMPTY: 'That file is empty. Choose another photo.',
  IMAGE_TOO_LARGE: 'That photo is over 8 MB. Choose a smaller one.',
  IMAGE_UNSUPPORTED_TYPE: 'Only JPEG, PNG or WebP photos are accepted.',
  IMAGE_MIME_MISMATCH:
    "The file's contents don't match its type. Save it again as JPEG or PNG.",
}

function errorMessage(status: number, body: unknown) {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = body.detail
    if (typeof detail === 'string') {
      return { message: DETAIL_CODES[detail] ?? detail, issues: [] }
    }
    if (Array.isArray(detail)) {
      const issues = detail.filter(
        (issue): issue is ValidationIssue =>
          typeof issue === 'object' && issue !== null,
      )
      const message = issues
        .map((issue) => {
          const field = issue.loc?.slice(1).join('.')
          const text = issue.msg?.replace(/^Value error,\s*/i, '')
          return [field, text].filter(Boolean).join(': ')
        })
        .filter(Boolean)
        .join(' ')
      if (message) return { message, issues }
    }
  }

  const fallback: Record<number, string> = {
    400: 'The backend rejected this request. Check the submitted values.',
    401: 'Your session is missing or expired. Sign in again.',
    403: 'You do not have permission to perform this action.',
    404: 'The requested record was not found.',
    422: 'Some submitted fields do not match the API contract.',
    500: 'The backend could not complete the request. Try again later.',
  }
  return {
    message: fallback[status] ?? `Backend request failed with HTTP ${status}.`,
    issues: [],
  }
}

function requestSignal(timeoutMs: number, signal?: AbortSignal) {
  const timeout = AbortSignal.timeout(timeoutMs)
  return signal ? AbortSignal.any([signal, timeout]) : timeout
}

/** Every request goes through here: base URL, timeout, headers, error translation. */
async function send(
  path: string,
  init: RequestInit = {},
  timeoutMs = 8_000,
): Promise<Response> {
  // FormData needs the browser to write its own multipart boundary header.
  const isForm = init.body instanceof FormData
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: requestSignal(timeoutMs, init.signal ?? undefined),
      headers: {
        Accept: 'application/json',
        ...(init.body && !isForm ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch (error) {
    const timedOut =
      error instanceof DOMException &&
      (error.name === 'AbortError' || error.name === 'TimeoutError')
    if (timedOut) {
      throw new ApiError(
        0,
        'The backend request timed out. Check the connection and try again.',
      )
    }
    // An unhandled exception in FastAPI answers without CORS headers, which
    // the browser reports exactly like an unreachable server; /health tells
    // the two apart.
    const alive =
      path !== '/health' &&
      (await fetch(`${API_BASE_URL}/health`, {
        signal: AbortSignal.timeout(3_000),
      }).then(
        (reply) => reply.ok,
        () => false,
      ))
    throw new ApiError(
      alive ? 500 : 0,
      alive
        ? 'The backend hit an internal error on this request. Try again, and report it to the backend team if it keeps failing.'
        : 'Could not reach the FastAPI backend.',
    )
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const parsed = errorMessage(response.status, body)
    throw new ApiError(response.status, parsed.message, parsed.issues)
  }
  return response
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs?: number,
): Promise<T> {
  const response = await send(path, init, timeoutMs)
  return (await response.json().catch(() => null)) as T
}

/** For endpoints whose 404 means "nothing yet" rather than a failure. */
async function nullOn404<T>(pending: Promise<T>): Promise<T | null> {
  try {
    return await pending
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

function bearer(token: string) {
  return { Authorization: `Bearer ${token}` }
}

function query(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

/** Proof images are served by FastAPI under /uploads, relative to its origin. */
export function backendFileUrl(path: string) {
  return /^https?:\/\//i.test(path) ? path : `${API_BASE_URL}${path}`
}

/* ------------------------------------------------------------------ *
 * Endpoints
 * ------------------------------------------------------------------ */

export function checkHealth(signal?: AbortSignal) {
  return request<{ status: string }>('/health', { signal })
}

export function registerAccount(body: RegisterRequest) {
  return request<RegisterResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function login(body: LoginRequest) {
  return request<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createComplaint(
  body: CreateComplaintRequest,
  accessToken: string,
) {
  return request<ComplaintResponse>('/complaints/', {
    method: 'POST',
    headers: bearer(accessToken),
    body: JSON.stringify(body),
  })
}

export function getComplaint(
  trackingId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  return request<ComplaintResponse>(
    `/complaints/${encodeURIComponent(trackingId)}`,
    { headers: bearer(accessToken), signal },
  )
}

export function getMyComplaints(accessToken: string, signal?: AbortSignal) {
  return request<ComplaintResponse[]>('/complaints/my', {
    headers: bearer(accessToken),
    signal,
  })
}

/**
 * Attach or replace the complaint photo (owner or admin). The response comes
 * back immediately with ai_status "pending"; the AI runs in the background.
 */
export function uploadComplaintImage(
  trackingId: string,
  file: File,
  accessToken: string,
) {
  const form = new FormData()
  form.append('file', file)
  return request<ComplaintResponse>(
    `/complaints/${encodeURIComponent(trackingId)}/image`,
    { method: 'POST', headers: bearer(accessToken), body: form },
    30_000,
  )
}

/**
 * Latest photo analysis, or null when no photo was ever analysed. Readable by
 * the owner, the assigned cleaner and admins.
 */
export async function getAIAnalysis(
  trackingId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  const analysis = await nullOn404(
    request<WasteAIAnalysis>(
      `/complaints/${encodeURIComponent(trackingId)}/ai-analysis`,
      { headers: bearer(accessToken), signal },
    ),
  )
  if (analysis) complaintIds.set(trackingId, analysis.complaint_id)
  return analysis
}

export function getAdminQueue(accessToken: string, signal?: AbortSignal) {
  return request<AdminQueueItem[]>('/admin/queue', {
    headers: bearer(accessToken),
    signal,
  })
}

export function getAdminQueueItem(
  trackingId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  return request<AdminQueueItem>(
    `/admin/queue/${encodeURIComponent(trackingId)}`,
    { headers: bearer(accessToken), signal },
  )
}

/**
 * Correct priority or department, or move the status forward. The reply is
 * the bare complaint row — no photo-AI summary is merged in, so its
 * ai_status is always null.
 */
export function updateAdminComplaint(
  complaintId: number,
  body: AdminComplaintUpdateRequest,
  accessToken: string,
) {
  return request<ComplaintResponse>(`/admin/complaints/${complaintId}`, {
    method: 'PUT',
    headers: bearer(accessToken),
    body: JSON.stringify(body),
  })
}

export function getMiningDataset(accessToken: string, signal?: AbortSignal) {
  return request<MiningDataset>(
    '/admin/mining/dataset',
    { headers: bearer(accessToken), signal },
    20_000,
  )
}

const complaintIds = new Map<string, number>()

/**
 * WORKAROUND — ai-review, decision, assign and the other admin actions take
 * the numeric database `complaint_id`, but no complaint or queue response
 * exposes it; the backend's own tests still read it straight from the
 * database. Responses that do carry it (ai-analysis, task proof review) fill
 * this cache; otherwise the mining dataset — the only route listing it next
 * to `tracking_id` — is fetched once. Delete this once AdminQueueItem carries
 * the id.
 */
export async function resolveComplaintId(
  trackingId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  const cached = complaintIds.get(trackingId)
  if (cached !== undefined) return cached
  const dataset = await getMiningDataset(accessToken, signal)
  for (const row of dataset.rows)
    complaintIds.set(row.tracking_id, row.complaint_id)
  const found = complaintIds.get(trackingId)
  if (found === undefined) {
    throw new ApiError(404, 'The backend has no complaint id for this case.')
  }
  return found
}

export function getAIOutputs(
  complaintId: number,
  accessToken: string,
  signal?: AbortSignal,
) {
  return request<AIOutput[]>(`/admin/complaints/${complaintId}/ai-output`, {
    headers: bearer(accessToken),
    signal,
  })
}

/** The admin view of the latest photo analysis, or null when there is none. */
export function getAIReview(
  complaintId: number,
  accessToken: string,
  signal?: AbortSignal,
) {
  return nullOn404(
    request<AdminAIReview>(`/admin/complaints/${complaintId}/ai-review`, {
      headers: bearer(accessToken),
      signal,
    }),
  )
}

export function recordAdminDecision(
  complaintId: number,
  body: AdminDecisionRequest,
  accessToken: string,
) {
  return request<AdminDecisionResult>(
    `/admin/complaints/${complaintId}/decision`,
    {
      method: 'PUT',
      headers: bearer(accessToken),
      body: JSON.stringify(body),
    },
  )
}

export function getCorrections(
  complaintId: number,
  accessToken: string,
  signal?: AbortSignal,
) {
  return request<AICorrection[]>(
    `/admin/complaints/${complaintId}/corrections`,
    { headers: bearer(accessToken), signal },
  )
}

export function assignCleaner(
  complaintId: number,
  body: AssignCleanerRequest,
  accessToken: string,
) {
  return request<AssignCleanerResponse>(
    `/admin/complaints/${complaintId}/assign`,
    {
      method: 'POST',
      headers: bearer(accessToken),
      body: JSON.stringify(body),
    },
  )
}

export function verifyProof(
  proofId: number,
  body: VerifyProofRequest,
  accessToken: string,
) {
  return request<VerifyProofResult>(`/admin/proofs/${proofId}/verify`, {
    method: 'POST',
    headers: bearer(accessToken),
    body: JSON.stringify(body),
  })
}

/** Admin tokens see every task here; cleaner tokens see only their own. */
export function getCleanerTasks(accessToken: string, signal?: AbortSignal) {
  return request<CleanerTask[]>('/cleaner/tasks', {
    headers: bearer(accessToken),
    signal,
  })
}

export function getCleanerTask(
  taskId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  return request<CleanerTask>(`/cleaner/tasks/${encodeURIComponent(taskId)}`, {
    headers: bearer(accessToken),
    signal,
  })
}

/**
 * There is no task lookup by complaint, and seeded assignment events carry no
 * task id, so the admin view filters the task list by tracking id.
 */
export async function findTaskForComplaint(
  trackingId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  const tasks = await getCleanerTasks(accessToken, signal)
  return tasks.find((task) => task.tracking_id === trackingId) ?? null
}

/**
 * The admin task view: who holds it (null until a cleaner is picked) and every
 * proof with its before photo and advisory AI comparison, oldest first.
 */
export async function getTaskProofReview(
  taskId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  const review = await request<AdminProofReview>(
    `/admin/tasks/${encodeURIComponent(taskId)}/proof`,
    { headers: bearer(accessToken), signal },
  )
  complaintIds.set(review.tracking_id, review.complaint_id)
  return review
}

export function startCleanerTask(taskId: string, accessToken: string) {
  return request<CleanerTask>(
    `/cleaner/tasks/${encodeURIComponent(taskId)}/start`,
    { method: 'POST', headers: bearer(accessToken) },
  )
}

export function uploadProof(taskId: string, file: File, accessToken: string) {
  const form = new FormData()
  form.append('file', file)
  return request<CleanupProof>(
    `/cleaner/tasks/${encodeURIComponent(taskId)}/proof`,
    { method: 'POST', headers: bearer(accessToken), body: form },
    30_000,
  )
}

export function getEvents(
  filters: EventFilters,
  accessToken: string,
  signal?: AbortSignal,
) {
  return request<EventLogEntry[]>(`/admin/events${query({ ...filters })}`, {
    headers: bearer(accessToken),
    signal,
  })
}

/**
 * Cleaners the admin can assign. There is no user directory endpoint, so this
 * is the set of cleaners seen in past assignment events — ids always, names
 * only where the event meta recorded one (seeded events do not).
 */
export async function getKnownCleaners(
  accessToken: string,
  signal?: AbortSignal,
) {
  const [assigned, reassigned] = await Promise.all([
    getEvents(
      { activity: 'cleaner_assigned', limit: 5000 },
      accessToken,
      signal,
    ),
    getEvents(
      { activity: 'cleaner_reassigned', limit: 5000 },
      accessToken,
      signal,
    ),
  ])
  const cleaners = new Map<number, string | null>()
  for (const event of [...assigned, ...reassigned]) {
    const id = Number(event.new_value)
    if (!Number.isInteger(id)) continue
    const name = event.meta?.cleaner_name
    if (typeof name === 'string' && name) cleaners.set(id, name)
    else if (!cleaners.has(id)) cleaners.set(id, null)
  }
  return [...cleaners]
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.id - b.id)
}

/**
 * CSV exports need the JWT, which a plain <a href> cannot send, so the file is
 * fetched with the Authorization header and handed to the browser as a blob.
 */
export async function downloadExport(
  path: '/admin/events/export' | '/admin/mining/dataset/export',
  filename: string,
  accessToken: string,
) {
  const response = await send(path, { headers: bearer(accessToken) }, 30_000)
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
