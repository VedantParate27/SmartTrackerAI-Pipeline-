import { useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import AuthPanel from '#/components/AuthPanel'
import {
  BackendPriorityPill,
  BackendStatusPill,
  ErrorState,
  Field,
  Spinner,
} from '#/components/ui'
import { createComplaint, fieldErrors } from '#/lib/api'
import type { ComplaintResponse } from '#/lib/api'
import { isExpiredSession, signOut, useAuth } from '#/lib/auth'
import { formatDateTime } from '#/lib/format'

export const Route = createFileRoute('/submit')({ component: SubmitPage })

interface FormValues {
  complaint_text: string
  phone: string
  consent: boolean
}

const EMPTY: FormValues = { complaint_text: '', phone: '', consent: false }
const MIN_TEXT = 10
const MAX_TEXT = 5000

function validate(values: FormValues) {
  const errors: Partial<Record<keyof FormValues, string>> = {}
  const length = values.complaint_text.trim().length
  if (length < MIN_TEXT || length > MAX_TEXT) {
    errors.complaint_text = `Complaint text must contain ${MIN_TEXT}–${MAX_TEXT} characters.`
  }
  if (values.phone.length > 20) {
    errors.phone = 'Phone must contain at most 20 characters.'
  }
  if (!values.consent) {
    errors.consent = 'Please confirm that the complaint may be processed.'
  }
  return errors
}

function SubmitPage() {
  const { session, hydrated } = useAuth()
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [errors, setErrors] = useState<
    Partial<Record<keyof FormValues, string>>
  >({})
  const [submitting, setSubmitting] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [created, setCreated] = useState<ComplaintResponse | null>(null)

  function update<TKey extends keyof FormValues>(
    key: TKey,
    value: FormValues[TKey],
  ) {
    setValues((current) => ({ ...current, [key]: value }))
    setErrors((current) => ({ ...current, [key]: undefined }))
  }

  if (!hydrated || !session) {
    return (
      <main id="main" className="wrap page max-w-2xl">
        <p className="kicker">Secure complaint intake</p>
        <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
          Submit a grievance
        </h1>
        <p className="mt-2 text-sm muted">
          The backend uses your signed-in profile for name and email, so those
          values cannot be forged in the complaint request.
        </p>
        <div className="mt-5">
          <AuthPanel />
        </div>
      </main>
    )
  }

  if (created) {
    return (
      <main id="main" className="wrap page max-w-2xl">
        <p className="kicker">Acknowledgement</p>
        <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
          Your grievance has been registered
        </h1>

        <section className="card card-pad mt-5">
          <span className="kicker">Backend tracking reference</span>
          <p className="mono mt-1 text-xl font-extrabold tracking-wide sm:text-2xl">
            {created.tracking_id}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <BackendStatusPill status={created.status} />
            <BackendPriorityPill priority={created.priority} />
          </div>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="kicker">Department</dt>
              <dd className="m-0">
                {created.department ?? 'Not yet assigned'}
              </dd>
            </div>
            <div>
              <dt className="kicker">Created</dt>
              <dd className="m-0">{formatDateTime(created.created_at)}</dd>
            </div>
          </dl>
        </section>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row">
          <Link
            to="/track"
            search={{ id: created.tracking_id }}
            className="btn btn-primary btn-block sm:w-auto"
          >
            Track this case
          </Link>
          <button
            type="button"
            className="btn btn-block sm:w-auto"
            onClick={() => {
              setCreated(null)
              setValues(EMPTY)
            }}
          >
            Submit another grievance
          </button>
        </div>
      </main>
    )
  }

  return (
    <main id="main" className="wrap page max-w-2xl">
      <p className="kicker">Authenticated complaint intake</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
        Submit a grievance
      </h1>
      <p className="mt-2 text-sm leading-relaxed muted">
        Only <span className="mono">complaint_text</span> and optional{' '}
        <span className="mono">phone</span> are sent. Status, priority,
        department, and tracking ID are assigned by FastAPI.
      </p>

      <div className="mt-4">
        <AuthPanel />
      </div>

      {requestError ? (
        <div className="mt-4">
          <ErrorState
            title="Complaint was not submitted"
            message={requestError}
            onReauth={expired ? signOut : undefined}
          />
        </div>
      ) : null}

      <form
        className="mt-5 grid gap-4"
        noValidate
        onSubmit={async (event) => {
          event.preventDefault()
          const found = validate(values)
          setErrors(found)
          if (Object.keys(found).length > 0) return

          setSubmitting(true)
          setRequestError(null)
          try {
            const response = await createComplaint(
              {
                complaint_text: values.complaint_text.trim(),
                phone: values.phone.trim() || null,
              },
              session.accessToken,
            )
            setCreated(response)
          } catch (error) {
            setExpired(isExpiredSession(error))
            // A 422 names the offending field; show it there, not only above.
            const perField = fieldErrors(error)
            if (Object.keys(perField).length > 0) setErrors(perField)
            setRequestError(
              error instanceof Error
                ? error.message
                : 'The complaint could not be submitted.',
            )
          } finally {
            setSubmitting(false)
          }
        }}
      >
        <Field
          label="What went wrong?"
          htmlFor="complaint_text"
          required
          hint={`${values.complaint_text.trim().length} of ${MAX_TEXT} characters; minimum ${MIN_TEXT}.`}
          error={errors.complaint_text}
        >
          <textarea
            id="complaint_text"
            name="complaint_text"
            className="textarea"
            minLength={MIN_TEXT}
            maxLength={MAX_TEXT}
            required
            value={values.complaint_text}
            aria-invalid={Boolean(errors.complaint_text)}
            placeholder="Describe the issue, including dates, amounts, locations, or reference numbers when relevant."
            onChange={(event) => update('complaint_text', event.target.value)}
          />
        </Field>

        <Field
          label="Phone number"
          htmlFor="phone"
          hint="Optional; the backend accepts up to 20 characters."
          error={errors.phone}
        >
          <input
            id="phone"
            name="phone"
            className="input"
            type="tel"
            autoComplete="tel"
            maxLength={20}
            value={values.phone}
            aria-invalid={Boolean(errors.phone)}
            onChange={(event) => update('phone', event.target.value)}
          />
        </Field>

        <div>
          <label className="check-row" htmlFor="consent">
            <input
              id="consent"
              name="consent"
              type="checkbox"
              checked={values.consent}
              aria-invalid={Boolean(errors.consent)}
              onChange={(event) => update('consent', event.target.checked)}
            />
            <span>
              I confirm that this complaint may be stored and processed.
            </span>
          </label>
          {errors.consent ? (
            <p className="field-error">{errors.consent}</p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="submit"
            className="btn btn-primary btn-block sm:w-auto"
            disabled={submitting}
          >
            {submitting ? <Spinner /> : null}
            {submitting ? 'Submitting…' : 'Submit grievance'}
          </button>
          <Link to="/" className="btn btn-quiet btn-block sm:w-auto">
            Cancel
          </Link>
        </div>
      </form>
    </main>
  )
}
