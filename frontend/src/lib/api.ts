import type {
  Complaint,
  Classification,
  ExtractedEntity,
  CaseStatus,
  Priority,
} from './types'

export const API_BASE_URL = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/$/, '')

export interface BackendComplaint {
  id: number
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
  status: string
  created_at: string
  updated_at: string
}

export interface CreateComplaintPayload {
  user_id: number
  complaint_text: string
  latitude?: number | null
  longitude?: number | null
  location_type?: 'gps' | 'manual' | null
  manual_address?: string | null
}

export interface ApprovalPayload {
  admin_id: number
  final_response: string
}

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
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(120_000),
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
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

    case 'resolved':
      return 'Resolved'

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
  }
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

export async function processComplaint(
  complaintId: string,
): Promise<Complaint> {
  const result = await request<BackendComplaint>(
    `/complaints/${complaintId}/process`,
    {
      method: 'POST',
    },
  )

  return mapComplaint(result)
}

export async function getComplaint(complaintId: string): Promise<Complaint> {
  const result = await request<BackendComplaint>(`/complaints/${complaintId}`)

  return mapComplaint(result)
}

/* ---------- Admin API ---------- */

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

export async function getAdminQueue(): Promise<AdminQueueItem[]> {
  return request<AdminQueueItem[]>('/admin/queue')
}

export async function approveComplaint(
  complaintId: string,
  payload: ApprovalPayload,
): Promise<{ complaint_id: number; status: string }> {
  return request(`/admin/responses/${complaintId}/approve`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
