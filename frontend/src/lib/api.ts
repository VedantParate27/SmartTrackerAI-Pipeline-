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

/** Exact ComplaintResponse returned by POST /complaints/, /complaints/my and /complaints/{id}. */
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
  created_at: string
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
 * AI triage + human-in-the-loop decision
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

export type Decision = 'dispatch' | 'guidance'

export interface AICorrectionItem {
  field_name: 'waste_type' | 'quantity_severity' | 'intervention_required'
  ai_value?: string | null
  admin_value?: string | null
}

/** Exact request body accepted by POST /admin/complaints/{id}/ai-decision. */
export interface AIDecisionRequest {
  waste_type: WasteType
  quantity_severity: Severity
  intervention_required: boolean
  decision: Decision
  guidance_text?: string | null
  notes?: string | null
  corrections?: AICorrectionItem[]
}

export interface AIDecisionResponse {
  tracking_id: string
  triage_mode: TriageMode
  review_completed: boolean
  decision: string
  waste_type: string | null
  quantity_severity: string | null
  intervention_required: boolean
  priority: string
  status: string
  task_id: string | null
  corrections_recorded: number
  acceptance_rate_fields: number
  resolved_at: string | null
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
 * Decisions the panel offers for a complaint status. The backend moves
 * dispatch -> in_progress and guidance -> resolved through VALID_TRANSITIONS
 * in backend/routers/admin.py; a resolved or closed case is treated as
 * decided. The backend stays the authority and its 400 is shown verbatim.
 */
export function allowedDecisions(status: string): Decision[] {
  const value = status.toLowerCase()
  return value === 'pending' || value === 'in_progress'
    ? ['dispatch', 'guidance']
    : []
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

function errorMessage(status: number, body: unknown) {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = body.detail
    if (typeof detail === 'string') return { message: detail, issues: [] }
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
    throw new ApiError(
      0,
      timedOut
        ? 'The backend request timed out. Check the connection and try again.'
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

export function getMiningDataset(accessToken: string, signal?: AbortSignal) {
  return request<MiningDataset>(
    '/admin/mining/dataset',
    { headers: bearer(accessToken), signal },
    20_000,
  )
}

const complaintIds = new Map<string, number>()

/**
 * WORKAROUND — every triage/dispatch endpoint takes the numeric database
 * `complaint_id`, but no complaint or queue response exposes it; the backend's
 * own tests read it straight from the database. The mining dataset is the only
 * HTTP route that returns it next to `tracking_id`, so it is resolved from
 * there and cached (the mapping never changes). Delete this once
 * AdminQueueItem carries the id.
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

export function recordAIDecision(
  complaintId: number,
  body: AIDecisionRequest,
  accessToken: string,
) {
  return request<AIDecisionResponse>(
    `/admin/complaints/${complaintId}/ai-decision`,
    {
      method: 'POST',
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
