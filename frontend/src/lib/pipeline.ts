import { POLICY_CHUNKS } from './seed'
import {
  CLASSIFIER_VERSION,
  CONFIG,
  GENERATION_MODEL,
  TAXONOMY_VERSION,
} from './taxonomy'
import type {
  CaseStatus,
  Classification,
  DraftResponse,
  EntityType,
  Evidence,
  ExtractedEntity,
  PolicyDocument,
} from './types'

/**
 * Local simulation of the FastAPI pipeline described in SRS sections 4.2, 4.3
 * and 8. It is deterministic and runs entirely in the browser: no model or
 * vector store is contacted. The UI labels every result as simulated.
 */

export const UNRESOLVED_DEPARTMENT = 'Not determined'

const INTENT_RULES: Array<{
  intent: string
  department: string
  keywords: string[]
}> = [
  {
    intent: 'Salary Deduction Dispute',
    department: 'Finance & Payroll',
    keywords: [
      'salary',
      'deduct',
      'payroll',
      'payslip',
      'pay slip',
      'wage',
      'arrear',
      'increment',
      'reimbursement',
    ],
  },
  {
    intent: 'Refund Not Received',
    department: 'Billing & Refunds',
    keywords: [
      'refund',
      'money back',
      'cancelled order',
      'credited',
      'not credited',
      'chargeback',
    ],
  },
  {
    intent: 'Billing Error',
    department: 'Billing & Refunds',
    keywords: [
      'invoice',
      'overcharg',
      'charged twice',
      'double charge',
      'duplicate charge',
      'billing',
      'tariff',
      'wrong bill',
    ],
  },
  {
    intent: 'Portal / Access Failure',
    department: 'IT Support',
    keywords: [
      'portal',
      'login',
      'log in',
      'password',
      'outage',
      'server',
      'crash',
      'error code',
      'timesheet',
      'not working',
      'website',
    ],
  },
  {
    intent: 'Workplace Grievance',
    department: 'Human Resources',
    keywords: [
      'manager',
      'harass',
      'discriminat',
      'leave',
      'attendance',
      'shift',
      'colleague',
      'supervisor',
      'appraisal',
    ],
  },
  {
    intent: 'Facility Maintenance',
    department: 'Facilities & Maintenance',
    keywords: [
      'leak',
      'water',
      'washroom',
      'electric',
      'light',
      'air condition',
      'lift',
      'elevator',
      'housekeeping',
      'garbage',
      'slippery',
    ],
  },
  {
    intent: 'Record / Certificate Request',
    department: 'Public Records',
    keywords: [
      'certificate',
      'certified copy',
      'birth record',
      'passport',
      'licence',
      'license',
      'affidavit',
      'registrar',
    ],
  },
]

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Prefix match on a word boundary so "deduct" also matches "deducted". */
function hasKeyword(text: string, keyword: string) {
  return new RegExp(`\\b${escapeRegExp(keyword)}`, 'i').test(text)
}

function round(value: number, places = 2) {
  const factor = 10 ** places
  return Math.round(value * factor) / factor
}

/* ------------------------------------------------------------------ *
 * FR-08 - entity extraction
 * ------------------------------------------------------------------ */

const ENTITY_PATTERNS: Array<{
  type: EntityType
  pattern: RegExp
  normalize?: (match: RegExpExecArray) => string
}> = [
  {
    type: 'Amount',
    pattern: /(?:₹|rs\.?|inr)\s?([\d,]+(?:\.\d{1,2})?)/gi,
    normalize: (m) => `INR ${m[1].replace(/,/g, '')}`,
  },
  {
    type: 'Employee ID',
    pattern: /\bemp(?:loyee)?[\s-]?(?:id[\s:-]*)?([a-z]*\d{3,})\b/gi,
    normalize: (m) => `EMP-${m[1].toUpperCase()}`,
  },
  {
    type: 'Order ID',
    pattern: /\bord(?:er)?[\s-]?(?:id[\s:-]*)?([a-z0-9]{5,})\b/gi,
    normalize: (m) => `ORD-${m[1].toUpperCase()}`,
  },
  {
    type: 'Error Code',
    pattern: /\berr[\s-]?(\d{3,})\b/gi,
    normalize: (m) => `ERR-${m[1]}`,
  },
  {
    type: 'Email',
    pattern: /\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b/g,
  },
  {
    type: 'Phone',
    pattern: /\b(?:\+91[\s-]?)?[6-9]\d{9}\b/g,
  },
  {
    type: 'Date',
    pattern: /\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b/g,
  },
  {
    type: 'Date',
    pattern:
      /\b(?:last|this|next|since)\s+(?:month|week|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)\b/gi,
  },
  {
    type: 'Date',
    pattern:
      /\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:,\s?\d{4})?\b/gi,
  },
  {
    type: 'Location',
    pattern: /\b(?:block|floor|wing|gate|ward|sector)\s+[a-z0-9]{1,3}\b/gi,
  },
]

export function extractEntities(text: string): ExtractedEntity[] {
  const found: ExtractedEntity[] = []

  for (const { type, pattern, normalize } of ENTITY_PATTERNS) {
    const regex = new RegExp(pattern.source, pattern.flags)
    let match = regex.exec(text)

    while (match !== null) {
      const value = match[0].trim()
      const start = match.index
      const overlaps = found.some(
        (e) => start < e.span[1] && start + value.length > e.span[0],
      )

      if (!overlaps && value.length > 1) {
        found.push({
          type,
          value,
          normalized: normalize ? normalize(match) : value,
          // Longer, more specific matches are treated as more reliable.
          confidence: round(Math.min(0.97, 0.72 + value.length / 60)),
          span: [start, start + value.length],
        })
      }

      if (match.index === regex.lastIndex) regex.lastIndex += 1
      match = regex.exec(text)
    }
  }

  return found.sort((a, b) => a.span[0] - b.span[0])
}

/* ------------------------------------------------------------------ *
 * FR-06, FR-07, FR-09 - classification and routing
 * ------------------------------------------------------------------ */

export function classify(text: string): Classification {
  const scored = INTENT_RULES.map((rule) => ({
    rule,
    hits: rule.keywords.filter((keyword) => hasKeyword(text, keyword)).length,
  })).sort((a, b) => b.hits - a.hits)

  const totalHits = scored.reduce((sum, item) => sum + item.hits, 0)

  if (totalHits === 0) {
    return {
      intent: 'Unclassified',
      department: UNRESOLVED_DEPARTMENT,
      confidence: 0.16,
      alternatives: [],
      modelVersion: CLASSIFIER_VERSION,
      taxonomyVersion: TAXONOMY_VERSION,
      ruleApplied: null,
      overriddenBy: null,
    }
  }

  const scoreOf = (hits: number) => {
    const share = hits / totalHits
    const coverage = Math.min(1, hits / 4)
    // Capped below 1: a classifier never reports absolute certainty.
    return round(Math.min(0.96, 0.35 * coverage + 0.65 * share))
  }

  const top = scored[0]
  let department = top.rule.department
  let ruleApplied: string | null = null

  // FR-09: explicit routing rules layered on top of the classifier output.
  if (hasKeyword(text, 'err') && /\berr[\s-]?\d{3,}\b/i.test(text)) {
    department = 'IT Support'
    ruleApplied = 'RR-01 - an explicit error code routes to IT Support'
  } else if (
    hasKeyword(text, 'harass') ||
    hasKeyword(text, 'discriminat') ||
    hasKeyword(text, 'safety')
  ) {
    department = 'Human Resources'
    ruleApplied = 'RR-02 - harassment, discrimination or safety routes to HR'
  }

  return {
    intent: top.rule.intent,
    department,
    confidence: scoreOf(top.hits),
    alternatives: scored
      .slice(1)
      .filter((item) => item.hits > 0)
      .slice(0, 2)
      .map((item) => ({
        intent: item.rule.intent,
        department: item.rule.department,
        confidence: scoreOf(item.hits),
      })),
    modelVersion: CLASSIFIER_VERSION,
    taxonomyVersion: TAXONOMY_VERSION,
    ruleApplied,
    overriddenBy: null,
  }
}

/* ------------------------------------------------------------------ *
 * FR-12 to FR-14 - hybrid retrieval
 * ------------------------------------------------------------------ */

const STOP_WORDS = new Set([
  'a',
  'about',
  'after',
  'all',
  'also',
  'am',
  'an',
  'and',
  'any',
  'are',
  'as',
  'at',
  'be',
  'been',
  'but',
  'by',
  'can',
  'do',
  'for',
  'from',
  'has',
  'have',
  'i',
  'if',
  'in',
  'is',
  'it',
  'its',
  'me',
  'my',
  'no',
  'not',
  'of',
  'on',
  'only',
  'or',
  'shall',
  'she',
  'so',
  'still',
  'that',
  'the',
  'their',
  'then',
  'there',
  'they',
  'this',
  'to',
  'up',
  'was',
  'we',
  'were',
  'what',
  'when',
  'which',
  'who',
  'will',
  'with',
  'you',
  'your',
])

function tokenize(text: string) {
  return (text.toLowerCase().match(/[a-z][a-z0-9-]{1,}/g) ?? []).filter(
    (token) => !STOP_WORDS.has(token),
  )
}

const CORPUS = POLICY_CHUNKS.map((chunk) => ({
  chunk,
  tokens: tokenize(chunk.text + ' ' + chunk.section),
}))

const AVG_LENGTH =
  CORPUS.reduce((sum, item) => sum + item.tokens.length, 0) / CORPUS.length

const DOC_FREQUENCY = (() => {
  const frequency = new Map<string, number>()
  for (const item of CORPUS) {
    for (const token of new Set(item.tokens)) {
      frequency.set(token, (frequency.get(token) ?? 0) + 1)
    }
  }
  return frequency
})()

function idf(token: string) {
  const df = DOC_FREQUENCY.get(token) ?? 0
  return Math.log(1 + (CORPUS.length - df + 0.5) / (df + 0.5))
}

/** Stand-in for embedding similarity: cosine over binary term vectors. */
function denseScore(queryTokens: string[], docTokens: string[]) {
  const query = new Set(queryTokens)
  const doc = new Set(docTokens)
  if (query.size === 0 || doc.size === 0) return 0
  let shared = 0
  for (const token of query) if (doc.has(token)) shared += 1
  // Scaled into the range embedding similarities usually land in.
  return round(
    Math.min(1, (2.6 * shared) / Math.sqrt(query.size * doc.size)),
    3,
  )
}

/** BM25 over the same corpus, normalised into a 0-1 range for display. */
function bm25Score(queryTokens: string[], docTokens: string[]) {
  const k1 = 1.5
  const b = 0.75
  let score = 0

  for (const token of new Set(queryTokens)) {
    const tf = docTokens.filter((t) => t === token).length
    if (tf === 0) continue
    score +=
      idf(token) *
      ((tf * (k1 + 1)) /
        (tf + k1 * (1 - b + (b * docTokens.length) / AVG_LENGTH)))
  }

  return round(Math.min(1, score / 9), 3)
}

export function retrieve(
  text: string,
  department: string,
  policies: PolicyDocument[],
): Evidence[] {
  const queryTokens = tokenize(text)
  const byId = new Map(policies.map((policy) => [policy.id, policy]))

  const candidates = CORPUS.filter(({ chunk }) => {
    const document = byId.get(chunk.documentId)
    // FR-27 / BR-04: only active versions reach the retrieval pipeline.
    if (!document || document.status !== 'Active') return false
    // FR-13: metadata filter on the routed department.
    if (department !== UNRESOLVED_DEPARTMENT) {
      return document.department === department
    }
    return true
  })

  const ranked = candidates.map(({ chunk, tokens }) => {
    const document = byId.get(chunk.documentId)!
    const dense = denseScore(queryTokens, tokens)
    const keyword = bm25Score(queryTokens, tokens)

    return {
      chunkId: chunk.id,
      documentId: chunk.documentId,
      documentTitle: document.title,
      version: document.version,
      effectiveDate: document.effectiveDate,
      department: document.department,
      section: chunk.section,
      page: chunk.page,
      snippet: chunk.text,
      denseScore: dense,
      keywordScore: keyword,
      // FR-14: merged hybrid rank.
      hybridScore: round(
        CONFIG.denseWeight * dense + CONFIG.keywordWeight * keyword,
        3,
      ),
    }
  })

  return ranked
    .filter((item) => item.hybridScore >= CONFIG.evidenceThreshold)
    .sort((a, b) => b.hybridScore - a.hybridScore)
    .slice(0, CONFIG.topK)
}

/* ------------------------------------------------------------------ *
 * FR-15, FR-16, AI-04, AI-05 - grounded draft generation
 * ------------------------------------------------------------------ */

const NEXT_STEPS: Record<string, string> = {
  'Finance & Payroll':
    'Payroll will verify the wage register for the disputed month and confirm the correction in writing.',
  'Billing & Refunds':
    'Billing will trace the transaction with the payment gateway and share the reference for your bank.',
  'IT Support':
    'The service desk will log this as an incident and share the workaround or fix timeline.',
  'Human Resources':
    'Human Resources will complete the first review and contact you for any additional detail.',
  'Facilities & Maintenance':
    'A technician will be assigned to inspect the reported location and confirm completion with you.',
  'Public Records':
    'The records desk will check the application for completeness and list anything that is missing.',
}

/** AI-07: reduce personal data before it is placed in a prompt or a draft. */
export function maskPII(text: string) {
  return text
    .replace(/\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b/g, '[email masked]')
    .replace(/\b(?:\+91[\s-]?)?[6-9]\d{9}\b/g, '[phone masked]')
}

function firstName(fullName: string) {
  return fullName.trim().split(/\s+/)[0] || 'Requester'
}

export function generateDraft(input: {
  caseId: string
  requesterName: string
  department: string
  intent: string
  evidence: Evidence[]
  now: string
}): DraftResponse {
  const { caseId, requesterName, department, evidence, now } = input

  // FR-16: abstain instead of writing an ungrounded response.
  if (evidence.length === 0) {
    return {
      text: [
        `A grounded draft could not be produced for ${caseId}.`,
        '',
        'No active policy section scored above the configured evidence threshold for this complaint, so any procedural commitment would be unsupported. This case requires manual handling by an administrator.',
        '',
        'Suggested administrator actions: confirm the correct department, ask the requester for the missing detail, or ingest the policy that covers this topic.',
      ].join('\n'),
      evidenceIds: [],
      generationModel: GENERATION_MODEL,
      grounding: 'Insufficient Evidence',
      groundingNotes: [
        'No retrieved evidence cleared the evidence threshold, so generation abstained (FR-16).',
        'The draft contains no policy claim and cannot be approved for sending.',
      ],
      createdAt: now,
    }
  }

  const cited = evidence.slice(0, 3)
  const body = cited.map(
    (item, index) =>
      `As per ${item.documentTitle} (version ${item.version}, ${item.section}): "${item.snippet}" [${index + 1}]`,
  )

  const sources = cited.map(
    (item, index) =>
      `[${index + 1}] ${item.documentTitle} - ${item.section}, page ${item.page} (version ${item.version}, effective ${item.effectiveDate})`,
  )

  const text = [
    `Dear ${firstName(requesterName)},`,
    '',
    `Thank you for contacting us. Your grievance has been registered as ${caseId} and routed to ${department} for review.`,
    '',
    ...body.flatMap((line) => [line, '']),
    NEXT_STEPS[department] ??
      'The assigned department will review this case and respond on this reference.',
    '',
    `You can track the case with the reference ${caseId}.`,
    '',
    'Regards,',
    `${department} Support Desk`,
    '',
    'Sources',
    ...sources,
  ].join('\n')

  return {
    text,
    evidenceIds: cited.map((item) => item.chunkId),
    generationModel: GENERATION_MODEL,
    grounding: 'Passed',
    groundingNotes: [
      `${cited.length} of ${cited.length} policy statements carry a citation (AI-05).`,
      'Every cited chunk belongs to an active policy version (FR-27).',
      `All evidence is owned by ${department}, which matches the routed department (FR-13).`,
      'Requester contact details were masked before generation (AI-07).',
    ],
    createdAt: now,
  }
}

/* ------------------------------------------------------------------ *
 * UC-02 - the full analysis pass
 * ------------------------------------------------------------------ */

export interface AnalysisResult {
  classification: Classification
  entities: ExtractedEntity[]
  evidence: Evidence[]
  draft: DraftResponse
  status: Extract<CaseStatus, 'Pending Review' | 'Manual Triage'>
  triageReasons: string[]
}

export function analyse(input: {
  caseId: string
  requesterName: string
  text: string
  policies: PolicyDocument[]
  now: string
}): AnalysisResult {
  const { caseId, requesterName, text, policies, now } = input

  const classification = classify(maskPII(text))
  const entities = extractEntities(text)
  const evidence = retrieve(text, classification.department, policies)
  const draft = generateDraft({
    caseId,
    requesterName,
    department: classification.department,
    intent: classification.intent,
    evidence,
    now,
  })

  const triageReasons: string[] = []
  if (classification.confidence < CONFIG.confidenceThreshold) {
    triageReasons.push(
      `Classifier confidence ${Math.round(classification.confidence * 100)}% is below the configured threshold of ${Math.round(CONFIG.confidenceThreshold * 100)}% (FR-10).`,
    )
  }
  if (classification.department === UNRESOLVED_DEPARTMENT) {
    triageReasons.push(
      'No department could be derived from the complaint text (FR-10).',
    )
  }
  if (draft.grounding === 'Insufficient Evidence') {
    triageReasons.push(
      'No active policy evidence supports a grounded draft (FR-16, BR-03).',
    )
  }

  return {
    classification,
    entities,
    evidence,
    draft,
    status: triageReasons.length > 0 ? 'Manual Triage' : 'Pending Review',
    triageReasons,
  }
}
