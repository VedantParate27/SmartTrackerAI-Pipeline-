import type {
  Complaint,
  Classification,
  ExtractedEntity,
  CaseStatus,
  Priority,
} from './types'

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ??
  import.meta.env.VITE_API_URL ??
  'http://127.0.0.1:8000'
).replace(/\/$/, '')

const AUTH_TOKEN_KEY = 'smarttracker_auth_token'

/* ---------- Auth token helpers ---------- */

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAuthToken(token: string | null): void {
  if (typeof window === 'undefined') return
  try {
    if (token) {
      window.localStorage.setItem(AUTH_TOKEN_KEY, token)
    } else {
      window.localStorage.removeItem(AUTH_TOKEN_KEY)
    }
  } catch {
    // LocalStorage quota or private mode error
  }
  try {
    window.dispatchEvent(new Event('smarttracker:auth-change'))
  } catch {
    // Event dispatch fallback
  }
}

export function clearAuthToken(): void {
  setAuthToken(null)
}

export interface AuthUser {
  id: number
  role: string
}

export function getAuthUser(): AuthUser | null {
  const token = getAuthToken()
  if (!token) return null
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = JSON.parse(atob(parts[1]))
    if (payload.exp && Date.now() >= payload.exp * 1000) {
      clearAuthToken()
      return null
    }
    return { id: Number(payload.sub), role: String(payload.role) }
  } catch {
    return null
  }
}

/* ---------- Image URL helper ---------- */

export function getBackendImageUrl(
  relativePath: string | null | undefined,
): string | null {
  if (!relativePath) return null
  if (
    relativePath.startsWith('http://') ||
    relativePath.startsWith('https://')
  ) {
    return relativePath
  }

  let cleanPath = relativePath.replace(/\\/g, '/').replace(/^\/+/, '')

  if (cleanPath.startsWith('backend/')) {
    cleanPath = cleanPath.slice('backend/'.length)
  }

  return `${API_BASE_URL}/${cleanPath}`
}

/* ---------- Data Contracts ---------- */

export interface LoginPayload {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface RegisterPayload {
  name: string
  email: string
  password: string
}

export interface RegisterResponse {
  id: number
  name: string
  email: string
  role: string
}

export interface BackendComplaint {
  id: number
  tracking_id?: string
  user_id: number
  complaint_text: string
  category: string | null
  department: string | null
  confidence_score: number | null
  ai_draft_response: string | null
  extracted_entities: string | null
  latitude: number | null
  longitude: number | null
  location_type: 'gps' | 'manual' | null
  manual_address: string | null
  image_path?: string | null
  image_mime_type?: string | null
  waste_type?: string | null
  waste_type_confidence?: number | null
  severity?: string | null
  severity_confidence?: number | null
  ai_reasoning?: string | null
  follow_up_question?: string | null
  recurring_flag?: boolean
  prior_reports_at_location?: number
  escalate_to_authority?: boolean
  needs_human_review?: boolean
  review_reasons?: string | null
  disposal_guidance?: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface CreateComplaintPayload {
  user_id?: number
  complaint_text: string
  latitude?: number | null
  longitude?: number | null
  location_type?: 'gps' | 'manual' | null
  manual_address?: string | null
}

export interface ApprovalPayload {
  admin_id?: number
  final_response: string
}

export interface CleanerUser {
  id: number
  name: string
  email: string
  role: string
  department: string | null
  created_at: string
}

export interface WasteReviewPayload {
  decision: 'approve_cleanup' | 'reject'
  cleaner_id?: number | null
  notes?: string | null
}

export interface WasteReviewResponse {
  complaint_id: number
  status: string
  cleanup_task: Record<string, unknown> | null
}

export interface CleanerTask {
  id: number
  complaint_id: number
  cleaner_id: number
  assigned_by: number
  status: string
  notes: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  tracking_id: string
  complaint_text: string
  waste_type: string | null
  severity: string | null
  image_path: string | null
  location_type: 'gps' | 'manual' | null
  latitude: number | null
  longitude: number | null
  manual_address: string | null
  complaint_status: string
}

export interface ProofUploadResponse {
  task_id: number
  complaint_id: number
  task_status: string
  complaint_status: string
  ai_verification: {
    after_image_usable: boolean
    cleanup_appears_complete: boolean
    confidence: number
    admin_review_recommended: boolean
  }
  proof: Record<string, unknown>
}

export interface AdminCleanupTask {
  id: number
  complaint_id: number
  cleaner_id: number
  assigned_by: number
  status: string
  notes: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  tracking_id: string
  complaint_text: string
  waste_type: string | null
  severity: string | null
  image_path: string | null
  complaint_status: string
  cleaner_name: string
  cleaner_email: string
  proof_id: number | null
  proof_image_path: string | null
  proof_image_mime_type: string | null
  verification_status: string | null
  verification_confidence: number | null
  verification_reason: string | null
  uploaded_at: string | null
  reviewed_at: string | null
  reviewed_by: number | null
}

export interface CleanupVerificationPayload {
  decision: 'approve' | 'reject'
  notes?: string | null
}

export interface CleanupVerificationResponse {
  task: Record<string, unknown>
  proof: Record<string, unknown>
  complaint: Record<string, unknown>
  admin_decision: string
}

export interface AdminQueueItem {
  id: number
  user_id: number
  complaint_text: string
  category: string | null
  department: string | null
  confidence_score: number | null
  extracted_entities: string | null
  latitude: number | null
  longitude: number | null
  location_type: 'gps' | 'manual' | null
  manual_address: string | null
  status: string
  created_at: string
  updated_at: string
  ai_draft_response: string
}

/* ---------- HTTP Request Wrapper ---------- */

function errorMessage(status: number, body: unknown): string {
  if (
    body &&
    typeof body === 'object' &&
    'detail' in body &&
    typeof body.detail === 'string'
  ) {
    return body.detail
  }

  return `API request failed (${status})`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const isFormData =
    typeof FormData !== 'undefined' && init?.body instanceof FormData

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(isFormData
      ? {}
      : init?.body
        ? { 'Content-Type': 'application/json' }
        : {}),
    ...(init?.headers as Record<string, string>),
  }

  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(120_000),
    headers,
  })

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(errorMessage(response.status, body))
  }

  return body as T
}

/* ---------- Backend → Frontend mapping ---------- */

function mapStatus(status: string): CaseStatus {
  switch (status) {
    case 'submitted':
      return 'Submitted'

    case 'processing':
      return 'AI Analysis'

    case 'awaiting_review':
      return 'Pending Review'

    case 'assigned':
      return 'Assigned to Department'

    case 'in_progress':
      return 'In Progress'

    case 'verification':
      return 'Verification'

    case 'completed':
    case 'resolved':
      return 'Resolved'

    case 'rejected':
      return 'Rejected'

    default:
      return 'Submitted'
  }
}

function mapEntities(raw: string | null): ExtractedEntity[] {
  if (!raw) {
    return []
  }

  try {
    const parsed = JSON.parse(raw)

    const entities: ExtractedEntity[] = []

    if (Array.isArray(parsed)) {
      return parsed
    }

    if (Array.isArray(parsed.order_ids)) {
      for (const orderId of parsed.order_ids) {
        entities.push({
          type: 'Order ID',
          value: String(orderId),
          normalized: String(orderId),
          confidence: 1,
          span: [0, 0],
        })
      }
    }

    if (parsed.account_id) {
      entities.push({
        type: 'Employee ID',
        value: String(parsed.account_id),
        normalized: String(parsed.account_id),
        confidence: 1,
        span: [0, 0],
      })
    }

    if (parsed.error_code) {
      entities.push({
        type: 'Error Code',
        value: String(parsed.error_code),
        normalized: String(parsed.error_code),
        confidence: 1,
        span: [0, 0],
      })
    }

    return entities
  } catch {
    return []
  }
}

function mapPriority(status: string): Priority {
  return status === 'high' ? 'High' : status === 'low' ? 'Low' : 'Medium'
}

function mapComplaint(row: BackendComplaint): Complaint {
  const classification: Classification | null =
    row.category || row.department
      ? {
          intent: row.category ?? 'other',
          department: row.department ?? 'other',
          confidence: row.confidence_score ?? 0,
          alternatives: [],
          modelVersion: 'Gemini',
          taxonomyVersion: 'Phase 2',
          ruleApplied: null,
          overriddenBy: null,
        }
      : null

  return {
    id: String(row.id),

    requesterName: `User ${row.user_id}`,
    contact: '',
    channel: 'Web',
    language: 'English',

    text: row.complaint_text,
    attachments: [],

    priority: mapPriority(row.status),

    status: mapStatus(row.status),

    submittedAt: row.created_at,
    updatedAt: row.updated_at,

    assignedDepartment: row.department,

    location:
      row.location_type != null
        ? {
            type: row.location_type,
            latitude: row.latitude,
            longitude: row.longitude,
            manualAddress: row.manual_address,
          }
        : null,

    classification,

    entities: mapEntities(row.extracted_entities),

    evidence: [],

    aiDraft: row.ai_draft_response
      ? {
          text: row.ai_draft_response,
          evidenceIds: [],
          generationModel: 'Gemini',
          grounding: 'Passed',
          groundingNotes: [],
          createdAt: row.updated_at,
        }
      : null,

    editedDraft: null,

    resolution: null,

    closureReason: null,
    duplicateOf: null,

    comments: [],
    audit: [],

    imagePath: row.image_path ?? null,
    wasteType: row.waste_type ?? null,
    severity: row.severity ?? null,
    aiReasoning: row.ai_reasoning ?? null,
  }
}

/* ---------- Authentication API ---------- */

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const result = await request<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

  if (result.access_token) {
    setAuthToken(result.access_token)
  }

  return result
}

export async function register(
  payload: RegisterPayload,
): Promise<RegisterResponse> {
  return request<RegisterResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function logout(): void {
  clearAuthToken()
}

/* ---------- Complaint API ---------- */

export async function createComplaint(
  payload: CreateComplaintPayload,
): Promise<Complaint> {
  const result = await request<BackendComplaint>('/complaints', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

  return mapComplaint(result)
}

export async function submitWasteComplaint(
  formData: FormData,
): Promise<Complaint> {
  const result = await request<BackendComplaint>('/complaints', {
    method: 'POST',
    body: formData,
  })

  return mapComplaint(result)
}

export async function processComplaint(
  complaintId: string | number,
): Promise<Complaint> {
  const result = await request<BackendComplaint>(
    `/complaints/${complaintId}/process`,
    {
      method: 'POST',
    },
  )

  return mapComplaint(result)
}

export async function getComplaint(
  complaintId: string | number,
): Promise<Complaint> {
  const result = await request<BackendComplaint>(`/complaints/${complaintId}`)

  return mapComplaint(result)
}

/* ---------- Admin API ---------- */

export async function getAdminQueue(): Promise<AdminQueueItem[]> {
  return request<AdminQueueItem[]>('/admin/queue')
}

export async function approveComplaint(
  complaintId: string | number,
  payload: ApprovalPayload,
): Promise<{ complaint_id: number; status: string }> {
  return request(`/admin/responses/${complaintId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ final_response: payload.final_response }),
  })
}

export async function listCleaners(): Promise<CleanerUser[]> {
  return request<CleanerUser[]>('/admin/cleaners')
}

export async function reviewWasteComplaint(
  complaintId: number | string,
  payload: WasteReviewPayload,
): Promise<WasteReviewResponse> {
  return request<WasteReviewResponse>(
    `/admin/complaints/${complaintId}/review`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

/* ---------- Cleaner API ---------- */

export async function listCleanerTasks(): Promise<CleanerTask[]> {
  return request<CleanerTask[]>('/cleaner/tasks')
}

export async function startCleanerTask(
  taskId: number | string,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/cleaner/tasks/${taskId}/start`, {
    method: 'POST',
  })
}

export async function uploadCleanupProof(
  taskId: number | string,
  formData: FormData,
): Promise<ProofUploadResponse> {
  return request<ProofUploadResponse>(`/cleaner/tasks/${taskId}/proof`, {
    method: 'POST',
    body: formData,
  })
}

/* ---------- Admin Cleanup Tasks & Verification API ---------- */

export async function listCleanupTasks(): Promise<AdminCleanupTask[]> {
  return request<AdminCleanupTask[]>('/admin/cleanup-tasks')
}

export async function verifyCleanupTask(
  taskId: number | string,
  payload: CleanupVerificationPayload,
): Promise<CleanupVerificationResponse> {
  return request<CleanupVerificationResponse>(
    `/admin/cleanup-tasks/${taskId}/verify`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}
