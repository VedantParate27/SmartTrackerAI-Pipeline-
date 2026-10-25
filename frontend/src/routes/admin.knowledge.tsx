import { useCallback, useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Callout, ErrorState, Field, LoadingState, SectionCard } from '#/components/ui'
import { formatDate } from '#/lib/format'
import {
  activatePolicyDoc,
  getAuthToken,
  getAuthUser,
  ingestPolicyDoc,
  listPolicies,
  retirePolicyDoc,
} from '#/lib/api'
import { useAuth } from '#/lib/auth'
import { DEPARTMENTS } from '#/lib/taxonomy'
import type { PolicyDocument } from '#/lib/types'

export const Route = createFileRoute('/admin/knowledge')({
  component: KnowledgePage,
})

const POLICY_TYPES: PolicyDocument['policyType'][] = [
  'Policy',
  'SOP',
  'Circular',
]
const ACCEPTED_TYPES = ['application/pdf', 'text/plain']

const STATUS_TONE: Record<PolicyDocument['status'], string> = {
  Active: 'ok',
  'Pending Approval': 'warn',
  Retired: 'neutral',
}

interface UploadForm {
  title: string
  owner: string
  department: string
  policyType: PolicyDocument['policyType']
  jurisdiction: string
  version: string
  effectiveDate: string
  pages: string
  supersedes: string
}

const EMPTY: UploadForm = {
  title: '',
  owner: '',
  department: DEPARTMENTS[0],
  policyType: 'Policy',
  jurisdiction: 'Organisation-wide',
  version: '',
  effectiveDate: '',
  pages: '1',
  supersedes: '',
}

function KnowledgePage() {
  const { session } = useAuth()
  const token =
    (session?.role === 'admin' ? session.accessToken : null) ??
    (getAuthUser()?.role === 'admin' ? (getAuthToken() ?? undefined) : undefined)

  const [policies, setPolicies] = useState<PolicyDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [search, setSearch] = useState('')
  const [department, setDepartment] = useState('All')
  const [status, setStatus] = useState('All')

  const [form, setForm] = useState<UploadForm>(EMPTY)
  const [fileName, setFileName] = useState('')
  const [formErrors, setFormErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [actionInProgress, setActionInProgress] = useState<string | null>(null)
  const [report, setReport] = useState<PolicyDocument | null>(null)

  const loadPolicies = useCallback(
    async (signal?: AbortSignal) => {
      if (!token) return
      setLoading(true)
      setError(null)
      try {
        const data = await listPolicies(
          { search, department, status },
          token,
          signal,
        )
        setPolicies(data)
      } catch (err: unknown) {
        if (err instanceof Error && err.name === 'AbortError') return
        setError(
          err instanceof Error ? err.message : 'Failed to load policy documents',
        )
      } finally {
        setLoading(false)
      }
    },
    [token, search, department, status],
  )

  useEffect(() => {
    const controller = new AbortController()
    loadPolicies(controller.signal)
    return () => controller.abort()
  }, [loadPolicies])

  if (!token) {
    return (
      <Callout tone="danger" title="Admin session required">
        Sign in with a backend admin account to access the policy knowledge base.
      </Callout>
    )
  }

  function update<TKey extends keyof UploadForm>(
    key: TKey,
    value: UploadForm[TKey],
  ) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const found: string[] = []

    if (form.title.trim().length < 4) found.push('Enter the document title.')
    if (form.owner.trim().length < 2) found.push('Enter the document owner.')
    if (!/^\d+(\.\d+)?$/.test(form.version.trim())) {
      found.push('Enter a version number such as 1.0 or 2.4.')
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(form.effectiveDate)) {
      found.push('Choose the effective date.')
    }
    const pages = Number(form.pages)
    if (!Number.isInteger(pages) || pages < 1 || pages > 500) {
      found.push('Page count must be a whole number between 1 and 500.')
    }
    if (!fileName) found.push('Attach the policy file (PDF or TXT).')

    setFormErrors(found)
    if (found.length > 0) return

    setSubmitting(true)
    try {
      const doc = await ingestPolicyDoc(
        {
          title: form.title.trim(),
          owner: form.owner.trim(),
          department: form.department,
          policyType: form.policyType,
          jurisdiction: form.jurisdiction.trim() || 'Organisation-wide',
          version: form.version.trim(),
          effectiveDate: form.effectiveDate,
          pages,
          fileName,
          supersedes: form.supersedes || null,
        },
        token,
      )
      setReport(doc)
      setForm(EMPTY)
      setFileName('')
      setFormErrors([])
      await loadPolicies()
    } catch (err: unknown) {
      setFormErrors([
        err instanceof Error ? err.message : 'Ingestion failed on backend',
      ])
    } finally {
      setSubmitting(false)
    }
  }

  async function handleActivate(id: string) {
    setActionInProgress(id)
    try {
      await activatePolicyDoc(id, token)
      if (report && report.id === id) {
        setReport(null)
      }
      await loadPolicies()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Activation failed')
    } finally {
      setActionInProgress(null)
    }
  }

  async function handleRetire(id: string) {
    setActionInProgress(id)
    try {
      await retirePolicyDoc(id, token)
      await loadPolicies()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Retirement failed')
    } finally {
      setActionInProgress(null)
    }
  }

  const activeCount = policies.filter(
    (policy) => policy.status === 'Active',
  ).length

  return (
    <div className="grid gap-4">
      <Callout tone="info" title="Only active versions are authoritative">
        {activeCount} of {policies.length} documents are active. Retired
        versions stay readable for audit but are never retrieved for a new draft
        (FR-27, FR-28, BR-04).
      </Callout>

      {report ? (
        <SectionCard
          title="Ingestion report"
          meta={`${report.id} · ${report.title} v${report.version}`}
        >
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="kicker">Chunks generated</dt>
              <dd className="m-0 font-bold">{report.ingestion.chunks}</dd>
            </div>
            <div>
              <dt className="kicker">Pages</dt>
              <dd className="m-0 font-bold">{report.pages}</dd>
            </div>
            <div>
              <dt className="kicker">Unreadable pages</dt>
              <dd className="m-0 font-bold">
                {report.ingestion.unreadablePages.length === 0
                  ? 'None'
                  : report.ingestion.unreadablePages.join(', ')}
              </dd>
            </div>
            <div>
              <dt className="kicker">Status</dt>
              <dd className="m-0 font-bold">{report.status}</dd>
            </div>
          </dl>

          {report.ingestion.warnings.length > 0 ? (
            <div className="mt-4">
              <Callout tone="warn" title="Warnings">
                <ul className="m-0 mt-1 list-disc space-y-0.5 pl-4">
                  {report.ingestion.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </Callout>
            </div>
          ) : null}

          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={actionInProgress === report.id}
              onClick={() => handleActivate(report.id)}
            >
              {actionInProgress === report.id
                ? 'Activating…'
                : 'Approve and activate this version'}
            </button>
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              onClick={() => setReport(null)}
            >
              Leave pending
            </button>
          </div>
        </SectionCard>
      ) : null}

      <SectionCard title="Upload a policy document" meta="FR-24, FR-25">
        {formErrors.length > 0 ? (
          <div className="mb-4">
            <Callout tone="danger" title="Fix these fields">
              <ul className="m-0 mt-1 list-disc space-y-0.5 pl-4">
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Callout>
          </div>
        ) : null}

        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={onSubmit}
          noValidate
        >
          <div className="sm:col-span-2">
            <Field label="Title" htmlFor="p-title" required>
              <input
                id="p-title"
                className="input"
                value={form.title}
                onChange={(event) => update('title', event.target.value)}
              />
            </Field>
          </div>

          <Field label="Owner" htmlFor="p-owner" required>
            <input
              id="p-owner"
              className="input"
              value={form.owner}
              onChange={(event) => update('owner', event.target.value)}
            />
          </Field>

          <Field label="Department" htmlFor="p-dept" required>
            <select
              id="p-dept"
              className="select"
              value={form.department}
              onChange={(event) => update('department', event.target.value)}
            >
              {DEPARTMENTS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Document type" htmlFor="p-type" required>
            <select
              id="p-type"
              className="select"
              value={form.policyType}
              onChange={(event) =>
                update(
                  'policyType',
                  event.target.value as PolicyDocument['policyType'],
                )
              }
            >
              {POLICY_TYPES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Jurisdiction" htmlFor="p-jurisdiction">
            <input
              id="p-jurisdiction"
              className="input"
              value={form.jurisdiction}
              onChange={(event) => update('jurisdiction', event.target.value)}
            />
          </Field>

          <Field
            label="Version"
            htmlFor="p-version"
            required
            hint="For example 1.0"
          >
            <input
              id="p-version"
              className="input"
              inputMode="decimal"
              value={form.version}
              onChange={(event) => update('version', event.target.value)}
            />
          </Field>

          <Field label="Effective date" htmlFor="p-date" required>
            <input
              id="p-date"
              type="date"
              className="input"
              value={form.effectiveDate}
              onChange={(event) => update('effectiveDate', event.target.value)}
            />
          </Field>

          <Field label="Pages" htmlFor="p-pages" required>
            <input
              id="p-pages"
              type="number"
              min={1}
              max={500}
              className="input"
              value={form.pages}
              onChange={(event) => update('pages', event.target.value)}
            />
          </Field>

          <Field
            label="Supersedes"
            htmlFor="p-supersedes"
            hint="Activating this version will retire the one it replaces."
          >
            <select
              id="p-supersedes"
              className="select"
              value={form.supersedes}
              onChange={(event) => update('supersedes', event.target.value)}
            >
              <option value="">Nothing — this is a new document</option>
              {policies
                .filter((policy) => policy.status === 'Active')
                .map((policy) => (
                  <option key={policy.id} value={policy.id}>
                    {policy.title} v{policy.version}
                  </option>
                ))}
            </select>
          </Field>

          <div className="sm:col-span-2">
            <Field
              label="Policy file"
              htmlFor="p-file"
              required
              hint="PDF or TXT. The file is registered and indexed for knowledge retrieval."
            >
              <input
                id="p-file"
                type="file"
                className="file-input"
                accept={ACCEPTED_TYPES.join(',')}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (!file) {
                    setFileName('')
                    return
                  }
                  if (!ACCEPTED_TYPES.includes(file.type)) {
                    setFormErrors([
                      'Only PDF or TXT policy documents can be ingested.',
                    ])
                    setFileName('')
                    return
                  }
                  setFormErrors([])
                  setFileName(file.name)
                }}
              />
            </Field>
          </div>

          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={submitting}
              className="btn btn-primary btn-block sm:w-auto"
            >
              {submitting ? 'Ingesting…' : 'Extract and ingest'}
            </button>
          </div>
        </form>
      </SectionCard>

      <SectionCard
        title="Policy versions"
        meta={`${policies.length} documents`}
        bodyClassName=""
      >
        <div className="card-pad pb-0">
          <div className="filter-row flex flex-wrap items-center justify-between gap-3 mb-4">
            <div className="flex flex-1 min-w-[200px] items-center gap-2">
              <input
                type="search"
                placeholder="Search policies by title, ID, or owner…"
                className="input w-full"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="select text-xs"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
              >
                <option value="All">All departments</option>
                {DEPARTMENTS.map((dept) => (
                  <option key={dept} value={dept}>
                    {dept}
                  </option>
                ))}
              </select>
              <select
                className="select text-xs"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="All">All statuses</option>
                <option value="Active">Active</option>
                <option value="Pending Approval">Pending Approval</option>
                <option value="Retired">Retired</option>
              </select>
            </div>
          </div>
        </div>

        {error ? (
          <div className="card-pad">
            <ErrorState
              title="Policy documents could not be loaded"
              message={error}
              onRetry={() => loadPolicies()}
            />
          </div>
        ) : loading && policies.length === 0 ? (
          <div className="card-pad">
            <LoadingState label="Loading policy documents…" />
          </div>
        ) : policies.length === 0 ? (
          <div className="card-pad text-center text-sm muted py-8">
            No policy documents found matching your filter criteria.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Document</th>
                  <th scope="col">Department</th>
                  <th scope="col">Version</th>
                  <th scope="col">Effective</th>
                  <th scope="col">Status</th>
                  <th scope="col">Retrievable</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {policies.map((policy) => (
                  <tr key={policy.id}>
                    <td>
                      <span className="font-bold">{policy.title}</span>
                      <span className="mono block subtle">{policy.id}</span>
                      <span className="block text-xs subtle">
                        {policy.policyType} · owner {policy.owner} ·{' '}
                        {policy.ingestion.chunks} chunks
                      </span>
                    </td>
                    <td className="text-xs">{policy.department}</td>
                    <td className="whitespace-nowrap">v{policy.version}</td>
                    <td className="whitespace-nowrap text-xs">
                      {formatDate(policy.effectiveDate)}
                    </td>
                    <td>
                      <span
                        className="pill"
                        data-tone={STATUS_TONE[policy.status]}
                      >
                        {policy.status}
                      </span>
                    </td>
                    <td className="text-xs">
                      {policy.status === 'Active' ? 'Yes' : 'No — audit only'}
                    </td>
                    <td>
                      {policy.status === 'Pending Approval' ? (
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={actionInProgress === policy.id}
                          onClick={() => handleActivate(policy.id)}
                        >
                          {actionInProgress === policy.id
                            ? 'Activating…'
                            : 'Activate'}
                        </button>
                      ) : policy.status === 'Active' ? (
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={actionInProgress === policy.id}
                          onClick={() => handleRetire(policy.id)}
                        >
                          {actionInProgress === policy.id
                            ? 'Retiring…'
                            : 'Retire'}
                        </button>
                      ) : (
                        <span className="text-xs subtle">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  )
}
