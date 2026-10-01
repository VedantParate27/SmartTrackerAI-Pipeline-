import { useSyncExternalStore } from 'react'
import { analyse } from './pipeline'
import { createComplaint, processComplaint } from './api'
import { POLICY_DOCUMENTS, SEED_CASES } from './seed'
import { SESSIONS, canTransition } from './taxonomy'
import type {
  Attachment,
  AuditEvent,
  CaseStatus,
  Complaint,
  ComplaintLocation,
  IngestionReport,
  PolicyDocument,
  Priority,
  Session,
} from './types'

/**
 * Client-side store standing in for the FastAPI backend. State is kept in a
 * single object so the server render and the first client render match; the
 * browser copy is rehydrated from localStorage after mount.
 */

const STORAGE_KEY = 'smarttracker.state.v2'

/** Fixed reference time used for the server render and the seeded data. */
const SEED_NOW = '2026-02-10T06:00:00.000Z'

export interface AppState {
  cases: Complaint[]
  policies: PolicyDocument[]
  session: Session
  /** Current time, injected so rendering stays deterministic during SSR. */
  now: string
  hydrated: boolean
}

let requestCounter = 0

function nextRequestId() {
  requestCounter += 1
  return `req-${String(requestCounter).padStart(5, '0')}`
}

function auditEvent(
  at: string,
  actor: string,
  action: string,
  detail: string | null,
  index: number,
): AuditEvent {
  return {
    id: `AE-${index}`,
    at,
    actor,
    action,
    detail,
    requestId: nextRequestId(),
  }
}

function buildSeedState(): AppState {
  const policies = POLICY_DOCUMENTS

  const cases = SEED_CASES.map((seed) => {
    const analysis = analyse({
      caseId: seed.id,
      requesterName: seed.requesterName,
      text: seed.text,
      policies,
      now: seed.submittedAt,
    })

    const audit: AuditEvent[] = [
      auditEvent(
        seed.submittedAt,
        seed.requesterName,
        'Complaint submitted',
        `Channel: ${seed.channel}`,
        1,
      ),
      auditEvent(
        seed.submittedAt,
        'System',
        'AI analysis completed',
        `Intent: ${analysis.classification.intent}; department: ${analysis.classification.department}; confidence: ${analysis.classification.confidence}`,
        2,
      ),
      auditEvent(
        seed.submittedAt,
        'System',
        `Status set to ${analysis.status}`,
        analysis.triageReasons.join(' ') || null,
        3,
      ),
    ]

    const record: Complaint = {
      id: seed.id,
      requesterName: seed.requesterName,
      contact: seed.contact,
      channel: seed.channel,
      language: 'English',
      text: seed.text,
      attachments: [],
      priority: seed.priority,
      status: analysis.status,
      submittedAt: seed.submittedAt,
      updatedAt: seed.submittedAt,
      assignedDepartment: null,
      location: null,
      classification: analysis.classification,
      entities: analysis.entities,
      evidence: analysis.evidence,
      aiDraft: analysis.draft,
      editedDraft: null,
      resolution: null,
      closureReason: null,
      duplicateOf: null,
      comments: [],
      audit,
    }

    const advance = seed.advance
    if (!advance) return record

    const at = advance.approvedResponse?.sentAt ?? seed.submittedAt

    if (advance.assignTo) {
      record.assignedDepartment = advance.assignTo
      record.audit.push(
        auditEvent(
          at,
          'A. Patil',
          'Assigned to department',
          advance.assignTo,
          record.audit.length + 1,
        ),
      )
    }

    if (advance.approvedResponse && record.aiDraft) {
      record.resolution = {
        text: record.aiDraft.text,
        approver: advance.approvedResponse.approver,
        sentAt: advance.approvedResponse.sentAt,
      }
      record.audit.push(
        auditEvent(
          advance.approvedResponse.sentAt,
          advance.approvedResponse.approver,
          'Response approved and sent',
          'Draft approved without edits',
          record.audit.length + 1,
        ),
      )
    }

    if (advance.status) {
      record.status = advance.status
      record.audit.push(
        auditEvent(
          at,
          'A. Patil',
          `Status set to ${advance.status}`,
          null,
          record.audit.length + 1,
        ),
      )
    }

    if (advance.comment) {
      record.comments.push({
        id: `CMT-${record.id}-1`,
        at: advance.comment.at,
        author: advance.comment.author,
        text: advance.comment.text,
      })
    }

    record.updatedAt = at
    return record
  })

  return {
    cases,
    policies,
    session: SESSIONS[0],
    now: SEED_NOW,
    hydrated: false,
  }
}

let state: AppState = buildSeedState()
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

function set(updater: (current: AppState) => AppState) {
  state = updater(state)
  emit()
  persist()
}

function persist() {
  if (typeof window === 'undefined' || !state.hydrated) return
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ cases: state.cases, policies: state.policies }),
    )
  } catch {
    // Storage can be unavailable (private mode, quota). The app still works.
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot() {
  return state
}

export function useAppState() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

/** Called once from the root component, after the first client render. */
export function hydrateStore() {
  if (state.hydrated || typeof window === 'undefined') return

  let restored: Pick<AppState, 'cases' | 'policies'> | null = null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw) restored = JSON.parse(raw)
  } catch {
    restored = null
  }

  state = {
    ...state,
    cases: restored?.cases ?? state.cases,
    policies: restored?.policies ?? state.policies,
    now: new Date().toISOString(),
    hydrated: true,
  }
  emit()
}

export function resetStore() {
  const seeded = buildSeedState()
  state = { ...seeded, now: new Date().toISOString(), hydrated: true }
  emit()
  persist()
}

/* ------------------------------------------------------------------ *
 * Selectors
 * ------------------------------------------------------------------ */

export function findCase(id: string) {
  const wanted = id.trim().toUpperCase()
  return state.cases.find((item) => item.id.toUpperCase() === wanted) ?? null
}

/** UR-05: a department officer may only read their own department's cases. */
export function isVisible(item: Complaint, session: Session) {
  if (session.departments === null) return true
  const department = item.assignedDepartment ?? item.classification?.department
  return department === undefined
    ? false
    : session.departments.includes(department)
}

export function activeDraft(item: Complaint) {
  return item.editedDraft ?? item.aiDraft?.text ?? ''
}

/* ------------------------------------------------------------------ *
 * Actions
 * ------------------------------------------------------------------ */

function touch(
  item: Complaint,
  at: string,
  actor: string,
  action: string,
  detail: string | null,
): Complaint {
  return {
    ...item,
    updatedAt: at,
    audit: [
      ...item.audit,
      auditEvent(at, actor, action, detail, item.audit.length + 1),
    ],
  }
}

function updateCase(id: string, updater: (item: Complaint) => Complaint) {
  set((current) => ({
    ...current,
    cases: current.cases.map((item) => (item.id === id ? updater(item) : item)),
  }))
}

export interface SubmitInput {
  requesterName: string
  contact: string
  text: string
  priority: Priority
  attachments: Attachment[]
  location: ComplaintLocation | null
}

/** UC-01 / FR-01 to FR-05. Returns the tracking id immediately. */
export async function submitComplaint(input: SubmitInput): Promise<Complaint> {
  const complaint = await createComplaint({
    user_id: 1,
    complaint_text: input.text,
    latitude: input.location?.latitude ?? null,
    longitude: input.location?.longitude ?? null,
    location_type: input.location?.type ?? null,
    manual_address: input.location?.manualAddress ?? null,
  })

  // Process the complaint through the real FastAPI + AI pipeline.
  const processedComplaint = await processComplaint(complaint.id)

  return {
    ...processedComplaint,
    requesterName: input.requesterName,
    contact: input.contact,
    priority: input.priority,
    attachments: input.attachments,
  }
}

/** UC-02. Runs the simulated pipeline and parks the case for a human. */
export function runAnalysis(id: string) {
  const target = findCase(id)
  if (!target) return

  updateCase(id, (item) =>
    touch(
      item,
      new Date().toISOString(),
      'System',
      'Status set to AI Analysis',
      null,
    ),
  )
  updateCase(id, (item) => ({ ...item, status: 'AI Analysis' }))

  window.setTimeout(() => {
    const current = findCase(id)
    if (!current) return

    const at = new Date().toISOString()
    const analysis = analyse({
      caseId: current.id,
      requesterName: current.requesterName,
      text: current.text,
      policies: state.policies,
      now: at,
    })

    updateCase(id, (item) => {
      const analysed = touch(
        item,
        at,
        'System',
        'AI analysis completed',
        `Intent: ${analysis.classification.intent}; department: ${analysis.classification.department}; confidence: ${analysis.classification.confidence}; evidence: ${analysis.evidence.length}`,
      )

      return touch(
        {
          ...analysed,
          classification: analysis.classification,
          entities: analysis.entities,
          evidence: analysis.evidence,
          aiDraft: analysis.draft,
          status: analysis.status,
        },
        at,
        'System',
        `Status set to ${analysis.status}`,
        analysis.triageReasons.join(' ') || null,
      )
    })
  }, 1400)
}

/** FR-11: authorised override of the AI classification. */
export function overrideClassification(
  id: string,
  next: { intent: string; department: string; reason: string },
) {
  const at = new Date().toISOString()
  const actor = state.session.name

  updateCase(id, (item) => {
    if (!item.classification) return item
    const before = `${item.classification.intent} / ${item.classification.department}`

    return touch(
      {
        ...item,
        classification: {
          ...item.classification,
          intent: next.intent,
          department: next.department,
          overriddenBy: actor,
        },
      },
      at,
      actor,
      'Classification overridden',
      `${before} -> ${next.intent} / ${next.department}. Reason: ${next.reason}`,
    )
  })
}

/** FR-19: the edited draft is stored separately from the AI original. */
export function saveDraftEdit(id: string, text: string) {
  const at = new Date().toISOString()
  updateCase(id, (item) =>
    touch(
      { ...item, editedDraft: text },
      at,
      state.session.name,
      'Draft edited',
      'Original AI draft retained',
    ),
  )
}

/** FR-20 / BR-01: explicit approve-and-send, recorded against the approver. */
export function approveAndSend(
  id: string,
  options: {
    text: string
    nextStatus: Extract<CaseStatus, 'Assigned to Department' | 'Resolved'>
  },
) {
  const at = new Date().toISOString()
  const approver = state.session.name

  updateCase(id, (item) => {
    const department =
      item.classification?.department ?? item.assignedDepartment
    const withResolution: Complaint = {
      ...item,
      resolution: { text: options.text, approver, sentAt: at },
      assignedDepartment: item.assignedDepartment ?? department ?? null,
      status: options.nextStatus,
    }

    return touch(
      touch(
        withResolution,
        at,
        approver,
        'Response approved and sent',
        item.editedDraft
          ? 'Approved with administrator edits'
          : 'Approved without edits',
      ),
      at,
      approver,
      `Status set to ${options.nextStatus}`,
      null,
    )
  })
}

/** FR-21: reassign with a mandatory reason (BR-02). */
export function reassign(id: string, department: string, reason: string) {
  const at = new Date().toISOString()
  const actor = state.session.name

  updateCase(id, (item) =>
    touch(
      {
        ...item,
        assignedDepartment: department,
        status:
          item.status === 'Manual Triage' || item.status === 'Pending Review'
            ? 'Assigned to Department'
            : item.status,
      },
      at,
      actor,
      'Case reassigned',
      `To ${department}. Reason: ${reason}`,
    ),
  )
}

export function escalate(id: string, reason: string) {
  const at = new Date().toISOString()
  updateCase(id, (item) =>
    touch(
      { ...item, status: 'Escalated' },
      at,
      state.session.name,
      'Case escalated',
      reason,
    ),
  )
}

export function reject(id: string, reason: string) {
  const at = new Date().toISOString()
  updateCase(id, (item) =>
    touch(
      { ...item, status: 'Rejected', closureReason: reason },
      at,
      state.session.name,
      'Case rejected as invalid',
      reason,
    ),
  )
}

export function markDuplicate(id: string, originalId: string, reason: string) {
  const at = new Date().toISOString()
  updateCase(id, (item) =>
    touch(
      {
        ...item,
        status: 'Duplicate',
        duplicateOf: originalId.toUpperCase(),
        closureReason: reason,
      },
      at,
      state.session.name,
      'Marked as duplicate',
      `Linked to ${originalId.toUpperCase()}. Reason: ${reason}`,
    ),
  )
}

/** FR-22 / BR-06: only workflow-permitted transitions are applied. */
export function setStatus(id: string, next: CaseStatus, note: string) {
  const target = findCase(id)
  if (!target || !canTransition(target.status, next)) return false

  const at = new Date().toISOString()
  updateCase(id, (item) =>
    touch(
      { ...item, status: next },
      at,
      state.session.name,
      `Status set to ${next}`,
      note || null,
    ),
  )
  return true
}

export function addComment(id: string, text: string) {
  const at = new Date().toISOString()
  const author = state.session.name

  updateCase(id, (item) => ({
    ...item,
    comments: [
      ...item.comments,
      { id: `CMT-${item.id}-${item.comments.length + 1}`, at, author, text },
    ],
    updatedAt: at,
  }))
}

export function setSession(session: Session) {
  set((current) => ({ ...current, session }))
}

/* ------------------------------------------------------------------ *
 * UC-04 - policy knowledge base
 * ------------------------------------------------------------------ */

export interface PolicyUploadInput {
  title: string
  owner: string
  department: string
  policyType: PolicyDocument['policyType']
  jurisdiction: string
  version: string
  effectiveDate: string
  pages: number
  fileName: string
  supersedes: string | null
}

/** FR-25, FR-26: ingest, then report what the extraction step produced. */
export function ingestPolicy(input: PolicyUploadInput) {
  const at = new Date().toISOString()
  const id = `DOC-${String(state.policies.length + 1).padStart(3, '0')}`

  const duplicate = state.policies.some(
    (policy) =>
      policy.title.toLowerCase() === input.title.toLowerCase() &&
      policy.version === input.version,
  )

  const ingestion: IngestionReport = {
    // Chunking is simulated: roughly three overlapping chunks per page.
    chunks: Math.max(1, input.pages * 3),
    unreadablePages: [],
    warnings: [
      ...(duplicate
        ? [
            `A document with the title "${input.title}" and version ${input.version} already exists.`,
          ]
        : []),
      'Chunk text is not searchable in this demo build: no vector store or BM25 index is connected.',
    ],
  }

  const record: PolicyDocument = {
    id,
    title: input.title,
    owner: input.owner,
    department: input.department,
    policyType: input.policyType,
    jurisdiction: input.jurisdiction,
    version: input.version,
    effectiveDate: input.effectiveDate,
    // FR-27: an upload is never immediately authoritative.
    status: 'Pending Approval',
    pages: input.pages,
    lastUpdated: at.slice(0, 10),
    supersedes: input.supersedes,
    ingestion,
  }

  set((current) => ({ ...current, policies: [record, ...current.policies] }))
  return record
}

export function activatePolicy(id: string) {
  const today = new Date().toISOString().slice(0, 10)

  set((current) => {
    const target = current.policies.find((policy) => policy.id === id)
    if (!target) return current

    return {
      ...current,
      policies: current.policies.map((policy) => {
        if (policy.id === id) {
          return { ...policy, status: 'Active', lastUpdated: today }
        }
        // FR-28: activating a version retires the version it supersedes.
        if (target.supersedes && policy.id === target.supersedes) {
          return { ...policy, status: 'Retired', lastUpdated: today }
        }
        return policy
      }),
    }
  })
}

export function retirePolicy(id: string) {
  set((current) => ({
    ...current,
    policies: current.policies.map((policy) =>
      policy.id === id
        ? {
            ...policy,
            status: 'Retired',
            lastUpdated: new Date().toISOString().slice(0, 10),
          }
        : policy,
    ),
  }))
}
