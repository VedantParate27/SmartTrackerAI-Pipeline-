export const API_BASE_URL = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/$/, '')

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

/** Exact request body accepted by POST /complaints/. */
export interface CreateComplaintRequest {
  complaint_text: string
  phone?: string | null
}

/** Exact ComplaintResponse model returned by the /complaints endpoints. */
export interface ComplaintResponse {
  tracking_id: string
  complaint_text: string
  status: string
  priority: string
  department: string | null
  created_at: string
}

/**
 * The AdminQueueItem body GET /admin/queue actually returns, verified against
 * the running app and its own /openapi.json.
 *
 * The schema docstring advertises renamed fields (id, requester_name, contact,
 * text, submitted_at, assigned_department), but Pydantic v2 treats `alias=` as
 * the serialization alias too, and FastAPI serialises `by_alias=True`, so the
 * database column names are what reach the wire. These names track the real
 * response. If the backend later switches to `serialization_alias`, this
 * interface is the single place to update.
 *
 * The AI fields are declared Any / [] by the backend schema, so they stay
 * unknown here: the UI must read them defensively instead of assuming a
 * successful classification, retrieval, or generation run.
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

/** Exact request body accepted by POST /admin/responses/{id}/approve. */
export interface ApproveResponseRequest {
  text: string
  next_status: 'in_progress' | 'resolved'
}

/** Exact ApproveResponseResult model returned by the approval endpoint. */
export interface ApproveResponseResult {
  tracking_id: string
  response_text: string
  approved_by: string
  approved_at: string
  status: string
}

/**
 * Mirrors VALID_TRANSITIONS in backend/routers/admin.py, narrowed to the two
 * statuses the approval endpoint accepts. It only decides which options to
 * offer; the backend stays the authority and still answers 400 when this list
 * gets a transition wrong.
 */
export function allowedApprovalStatuses(
  currentStatus: string,
): Array<ApproveResponseRequest['next_status']> {
  const allowed: Record<
    string,
    Array<ApproveResponseRequest['next_status']>
  > = {
    pending: ['in_progress', 'resolved'],
    in_progress: ['in_progress', 'resolved'],
    resolved: ['resolved'],
    closed: [],
  }
  return allowed[currentStatus.toLowerCase()] ?? []
}

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
          return [field, issue.msg].filter(Boolean).join(': ')
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
    404: 'The requested complaint was not found.',
    422: 'Some submitted fields do not match the API contract.',
    500: 'The backend could not complete the request. Try again later.',
  }
  return {
    message: fallback[status] ?? `Backend request failed with HTTP ${status}.`,
    issues: [],
  }
}

function requestSignal(signal?: AbortSignal) {
  const timeout = AbortSignal.timeout(8_000)
  return signal ? AbortSignal.any([signal, timeout]) : timeout
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: requestSignal(init.signal ?? undefined),
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
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

  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const parsed = errorMessage(response.status, body)
    throw new ApiError(response.status, parsed.message, parsed.issues)
  }
  return body as T
}

function bearer(token: string) {
  return { Authorization: `Bearer ${token}` }
}

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

/**
 * There is no GET /admin/queue/{tracking_id}, so the detail screen reads the
 * queue and selects the matching item. Keeping that workaround here means the
 * route components stay on a single helper once the endpoint is added.
 */
export async function getAdminQueueItem(
  trackingId: string,
  accessToken: string,
  signal?: AbortSignal,
) {
  const queue = await getAdminQueue(accessToken, signal)
  const found = queue.find((item) => item.tracking_id === trackingId)
  if (!found) {
    throw new ApiError(404, 'This complaint is not in the admin queue.')
  }
  return found
}

export function approveResponse(
  trackingId: string,
  body: ApproveResponseRequest,
  accessToken: string,
) {
  return request<ApproveResponseResult>(
    `/admin/responses/${encodeURIComponent(trackingId)}/approve`,
    {
      method: 'POST',
      headers: bearer(accessToken),
      body: JSON.stringify(body),
    },
  )
}
