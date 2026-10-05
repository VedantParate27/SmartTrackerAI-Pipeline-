import type { CaseStatus, Priority, Role, Session } from './types'

/** TBD-01 placeholder taxonomy. Configurable, not hard-coded in components. */
export const TAXONOMY_VERSION = 'tax-2026.02'
export const CLASSIFIER_VERSION = 'intent-clf-0.4.1'
export const GENERATION_MODEL = 'grounded-draft-0.3.0'
export const EMBEDDING_MODEL = 'embed-mini-384'

export const DEPARTMENTS = [
  'Finance & Payroll',
  'Human Resources',
  'IT Support',
  'Facilities & Maintenance',
  'Billing & Refunds',
  'Public Records',
] as const

export const PRIORITIES: Priority[] = ['Low', 'Medium', 'High']

export const STATUSES: CaseStatus[] = [
  'Submitted',
  'AI Analysis',
  'Pending Review',
  'Manual Triage',
  'Assigned to Department',
  'In Progress',
  'Escalated',
  'Resolved',
  'Closed',
  'Rejected',
  'Duplicate',
]

/** AI-02: thresholds are configurable and must be validated on a test set. */
export const CONFIG = {
  /** FR-10: below this the case goes to Manual Triage. */
  confidenceThreshold: 0.62,
  /** FR-16: below this there is no usable evidence, so the draft abstains. */
  evidenceThreshold: 0.18,
  /** Top-k for both retrievers before the merge step. */
  topK: 5,
  /** Weights for the hybrid merge (dense vs BM25). */
  denseWeight: 0.6,
  keywordWeight: 0.4,
  maxAttachments: 3,
  maxAttachmentBytes: 5 * 1024 * 1024,
  allowedAttachmentTypes: [
    'application/pdf',
    'text/plain',
    'image/png',
    'image/jpeg',
  ],
}

export const STATUS_MEANING: Record<CaseStatus, string> = {
  Submitted: 'Case is stored and waiting for processing.',
  'AI Analysis':
    'Classification, extraction, retrieval and draft generation are running.',
  'Pending Review': 'AI results are available for a human administrator.',
  'Manual Triage':
    'Confidence or evidence was insufficient, so a human must triage this case.',
  'Assigned to Department': 'Case has an authorised departmental owner.',
  'In Progress': 'Department is actively handling the grievance.',
  Verification: 'Cleanup proof is submitted and awaiting verification.',
  Escalated:
    'Senior or specialist review is required due to risk, uncertainty or delay.',
  Resolved: 'A resolution has been recorded and communicated.',
  Closed:
    'No further action is expected; the case remains available for audit.',
  Rejected: 'Case is invalid, spam or out of scope.',
  Duplicate: 'Case is linked to an existing case.',
}

export type Tone = 'neutral' | 'info' | 'warn' | 'ok' | 'danger'

export const STATUS_TONE: Record<CaseStatus, Tone> = {
  Submitted: 'neutral',
  'AI Analysis': 'info',
  'Pending Review': 'info',
  'Manual Triage': 'warn',
  'Assigned to Department': 'info',
  'In Progress': 'info',
  Verification: 'info',
  Escalated: 'warn',
  Resolved: 'ok',
  Closed: 'neutral',
  Rejected: 'danger',
  Duplicate: 'neutral',
}

/** BR-06: every status transition must be allowed by the workflow. */
export const ALLOWED_TRANSITIONS: Record<CaseStatus, CaseStatus[]> = {
  Submitted: ['AI Analysis', 'Rejected'],
  'AI Analysis': ['Pending Review', 'Manual Triage'],
  'Pending Review': [
    'Assigned to Department',
    'Escalated',
    'Resolved',
    'Rejected',
    'Duplicate',
  ],
  'Manual Triage': [
    'Assigned to Department',
    'Pending Review',
    'Escalated',
    'Rejected',
    'Duplicate',
  ],
  'Assigned to Department': ['In Progress', 'Escalated', 'Resolved'],
  'In Progress': ['Verification', 'Escalated', 'Resolved'],
  Verification: ['Resolved', 'In Progress', 'Escalated'],
  Escalated: ['In Progress', 'Resolved'],
  Resolved: ['Closed'],
  Closed: [],
  Rejected: ['Closed'],
  Duplicate: ['Closed'],
}

export function canTransition(from: CaseStatus, to: CaseStatus) {
  return ALLOWED_TRANSITIONS[from].includes(to)
}

/** NFR-05 / BR-01: role-based access control. */
const PERMISSIONS: Record<Role, string[]> = {
  Requester: [],
  'Support Administrator': [
    'case.read.all',
    'case.edit_draft',
    'case.approve',
    'case.reassign',
    'case.override',
    'case.comment',
  ],
  'Department Officer': ['case.read.department', 'case.comment', 'case.status'],
  'Knowledge Manager': ['policy.manage'],
  'System Administrator': ['case.read.all', 'policy.manage', 'config.manage'],
}

export function can(session: Session, permission: string) {
  return PERMISSIONS[session.role].includes(permission)
}

export const SESSIONS: Session[] = [
  { role: 'Support Administrator', name: 'A. Patil', departments: null },
  {
    role: 'Department Officer',
    name: 'K. Lanke',
    departments: ['Finance & Payroll'],
  },
  { role: 'Knowledge Manager', name: 'V. Parate', departments: null },
]
