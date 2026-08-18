/** Data model from SRS section 7.2 (Core Data Entities). */

export type Priority = 'Low' | 'Medium' | 'High'

/** Appendix A.2 - Status Definitions. */
export type CaseStatus =
  | 'Submitted'
  | 'AI Analysis'
  | 'Pending Review'
  | 'Manual Triage'
  | 'Assigned to Department'
  | 'In Progress'
  | 'Escalated'
  | 'Resolved'
  | 'Closed'
  | 'Rejected'
  | 'Duplicate'

export type EntityType =
  | 'Person'
  | 'Date'
  | 'Amount'
  | 'Order ID'
  | 'Employee ID'
  | 'Location'
  | 'Error Code'
  | 'Email'
  | 'Phone'

/** Extracted Entity: type, value, normalized value, confidence, source span. */
export interface ExtractedEntity {
  type: EntityType
  value: string
  normalized: string
  confidence: number
  span: [number, number]
}

/** Classification Result: intent, department, scores, alternatives, versions. */
export interface Classification {
  intent: string
  department: string
  confidence: number
  alternatives: Array<{
    intent: string
    department: string
    confidence: number
  }>
  modelVersion: string
  taxonomyVersion: string
  ruleApplied: string | null
  overriddenBy: string | null
}

export interface IngestionReport {
  chunks: number
  unreadablePages: number[]
  warnings: string[]
}

/** Policy Document: title, owner, version, effective date, status, metadata. */
export interface PolicyDocument {
  id: string
  title: string
  owner: string
  department: string
  policyType: 'Policy' | 'SOP' | 'Circular'
  jurisdiction: string
  version: string
  effectiveDate: string
  status: 'Active' | 'Pending Approval' | 'Retired'
  pages: number
  lastUpdated: string
  supersedes: string | null
  ingestion: IngestionReport
}

/** Policy Chunk: parent document version, source page, text. */
export interface PolicyChunk {
  id: string
  documentId: string
  page: number
  section: string
  text: string
}

/** A merged, ranked and deduplicated retrieval result (FR-12 to FR-14). */
export interface Evidence {
  chunkId: string
  documentId: string
  documentTitle: string
  version: string
  effectiveDate: string
  department: string
  section: string
  page: number
  snippet: string
  denseScore: number
  keywordScore: number
  hybridScore: number
}

export type GroundingResult = 'Passed' | 'Insufficient Evidence'

/** Draft Response: generated text, evidence IDs, model, grounding result. */
export interface DraftResponse {
  text: string
  evidenceIds: string[]
  generationModel: string
  grounding: GroundingResult
  groundingNotes: string[]
  createdAt: string
}

/** Resolution: human-edited response, approver, action, sent time. */
export interface Resolution {
  text: string
  approver: string
  sentAt: string
}

/** Audit Event: actor, action, before/after values, timestamp, request id. */
export interface AuditEvent {
  id: string
  at: string
  actor: string
  action: string
  detail: string | null
  requestId: string
}

export interface CaseComment {
  id: string
  at: string
  author: string
  text: string
}

export interface Attachment {
  name: string
  size: number
  type: string
}

/** Complaint: requester contact, original text, attachments, status, times. */
export interface Complaint {
  id: string
  requesterName: string
  contact: string
  channel: string
  language: string
  /** Immutable after creation (SRS 7.3). */
  text: string
  attachments: Attachment[]
  priority: Priority
  status: CaseStatus
  submittedAt: string
  updatedAt: string
  assignedDepartment: string | null
  classification: Classification | null
  entities: ExtractedEntity[]
  evidence: Evidence[]
  /** Immutable after creation (SRS 7.3); edits live in `editedDraft`. */
  aiDraft: DraftResponse | null
  editedDraft: string | null
  resolution: Resolution | null
  closureReason: string | null
  duplicateOf: string | null
  comments: CaseComment[]
  audit: AuditEvent[]
}

/** Document Guide: required proofs, steps, fees, time, source, last updated. */
export interface DocumentGuide {
  id: string
  title: string
  aliases: string[]
  authority: string
  requiredDocuments: string[]
  acceptableProofs: string[]
  steps: string[]
  fees: string
  processingTime: string
  validity: string
  source: string
  lastUpdated: string
}

export type Role =
  | 'Requester'
  | 'Support Administrator'
  | 'Department Officer'
  | 'Knowledge Manager'
  | 'System Administrator'

export interface Session {
  role: Role
  name: string
  /** Departments this session may read (UR-05). `null` means all. */
  departments: string[] | null
}
