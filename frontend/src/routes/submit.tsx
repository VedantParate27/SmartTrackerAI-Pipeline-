import { useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import AuthPanel from '#/components/AuthPanel'
import {
  BackendPriorityPill,
  BackendStatusPill,
  ErrorState,
  Field,
  Spinner,
  WastePill,
} from '#/components/ui'
import {
  SEVERITIES,
  WASTE_TYPES,
  createComplaint,
  fieldErrors,
} from '#/lib/api'
import type { ComplaintResponse, Severity, WasteType } from '#/lib/api'
import { isExpiredSession, signOut, useAuth } from '#/lib/auth'
import {
  formatCoordinates,
  severityLabel,
  wasteLabel,
} from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'

export const Route = createFileRoute('/submit')({ component: SubmitPage })

interface FormValues {
  complaint_text: string
  address_text: string
  waste_type: WasteType | ''
  quantity_severity: Severity | ''
  intervention_required: boolean
  waste_context: string
  phone: string
  consent: boolean
}

// `latitude`/`longitude` have no input of their own but a 422 can still name them.
type FormErrors = Partial<
  Record<keyof FormValues | 'location' | 'latitude' | 'longitude', string>
>

const EMPTY: FormValues = {
  complaint_text: '',
  address_text: '',
  waste_type: '',
  quantity_severity: '',
  intervention_required: false,
  waste_context: '',
  phone: '',
  consent: false,
}
const MIN_TEXT = 10
const MAX_TEXT = 5000

/** Client checks mirror CreateComplaintRequest so most mistakes never cost a round-trip. */
function validate(values: FormValues) {
  const errors: FormErrors = {}
  const length = values.complaint_text.trim().length
  if (length < MIN_TEXT || length > MAX_TEXT) {
    errors.complaint_text = `Describe the problem in ${MIN_TEXT}–${MAX_TEXT} characters.`
  }
  if (values.address_text.length > 255) {
    errors.address_text = 'Keep the address under 255 characters.'
  }
  if (values.waste_context.length > 2000) {
    errors.waste_context = 'Keep this under 2000 characters.'
  }
  if (values.phone.length > 20) {
    errors.phone = 'Phone must contain at most 20 characters.'
  }
  if (!values.consent) {
    errors.consent = 'Please confirm that the complaint may be processed.'
  }
  return errors
}

const GEO_ERRORS: Record<number, string> = {
  1: 'Location permission was denied. You can type the address instead.',
  2: 'Your location could not be determined. Type the address instead.',
  3: 'Finding your location took too long. Try again or type the address.',
}

function SubmitPage() {
  const { session, hydrated } = useAuth()
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(
    null,
  )
  const [locating, setLocating] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})
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

  function locate() {
    if (!('geolocation' in navigator)) {
      setErrors((current) => ({
        ...current,
        location: 'This browser cannot share a location. Type the address.',
      }))
      return
    }
    setLocating(true)
    setErrors((current) => ({ ...current, location: undefined }))
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        })
        setLocating(false)
      },
      (failure) => {
        setErrors((current) => ({
          ...current,
          location:
            GEO_ERRORS[failure.code] ?? 'Your location could not be read.',
        }))
        setLocating(false)
      },
      { enableHighAccuracy: true, timeout: 10_000 },
    )
  }

  if (!hydrated || !session) {
    return (
      <main id="main" className="wrap page max-w-2xl">
        <p className="kicker">Report waste</p>
        <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
          Report a waste problem
        </h1>
        <p className="mt-2 text-sm muted">
          Sign in so you can track what happens next. Your name and email come
          from your account, so nobody can file under your name.
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
        <p className="kicker">Received</p>
        <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
          Your complaint is registered
        </h1>

        <section className="card card-pad mt-5">
          <span className="kicker">Tracking reference</span>
          <p className="mono mt-1 text-xl font-extrabold tracking-wide sm:text-2xl">
            {created.tracking_id}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <BackendStatusPill status={created.status} />
            <BackendPriorityPill priority={created.priority} />
            {created.waste_type ? (
              <WastePill wasteType={created.waste_type} />
            ) : null}
          </div>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="kicker">Submitted</dt>
              <dd className="m-0">{formatDateTime(created.created_at)}</dd>
            </div>
            <div>
              <dt className="kicker">Location</dt>
              <dd className="m-0">
                {created.address_text ??
                  formatCoordinates(created.latitude, created.longitude) ??
                  'Not given'}
              </dd>
            </div>
          </dl>
        </section>

        <section className="card card-pad mt-4">
          <h2 className="card-title">What happens next</h2>
          <ol className="mt-2 grid gap-1.5 pl-5 text-sm muted">
            <li>
              An AI assistant suggests the waste type and how serious it is.
            </li>
            <li>
              A staff member checks that suggestion — the AI never decides
              alone.
            </li>
            <li>
              You either get disposal guidance, or a cleaner is sent and must
              upload a photo before the case is closed.
            </li>
          </ol>
        </section>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row">
          <Link
            to="/track"
            search={{ id: created.tracking_id }}
            className="btn btn-primary btn-block sm:w-auto"
          >
            Track this complaint
          </Link>
          <button
            type="button"
            className="btn btn-block sm:w-auto"
            onClick={() => {
              setCreated(null)
              setValues(EMPTY)
              setCoords(null)
            }}
          >
            Report another problem
          </button>
        </div>
      </main>
    )
  }

  return (
    <main id="main" className="wrap page max-w-2xl">
      <p className="kicker">Report waste</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
        Report a waste problem
      </h1>
      <p className="mt-2 text-sm leading-relaxed muted">
        Only the description is required. Priority is worked out by the backend
        from the details, so you never have to pick one.
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
        className="mt-5 grid gap-5"
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
                address_text: values.address_text.trim() || null,
                latitude: coords?.lat ?? null,
                longitude: coords?.lng ?? null,
                waste_type: values.waste_type || null,
                quantity_severity: values.quantity_severity || null,
                intervention_required: values.intervention_required,
                waste_context: values.waste_context.trim() || null,
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
          label="What is the problem?"
          htmlFor="complaint_text"
          required
          hint={`${values.complaint_text.trim().length} of ${MAX_TEXT} characters; minimum ${MIN_TEXT}.`}
          error={errors.complaint_text}
        >
          <textarea
            id="complaint_text"
            className="textarea"
            maxLength={MAX_TEXT}
            required
            value={values.complaint_text}
            aria-invalid={Boolean(errors.complaint_text)}
            placeholder="e.g. Broken TVs and batteries dumped behind the market for a week."
            onChange={(event) => update('complaint_text', event.target.value)}
          />
        </Field>

        <fieldset className="card card-pad grid gap-4">
          <legend className="kicker px-1">Where is it?</legend>
          <Field
            label="Address or landmark"
            htmlFor="address_text"
            hint="Include the ward if you know it, e.g. “Ward 3, Market Road”."
            error={errors.address_text}
          >
            <input
              id="address_text"
              className="input"
              maxLength={255}
              autoComplete="street-address"
              value={values.address_text}
              aria-invalid={Boolean(errors.address_text)}
              onChange={(event) => update('address_text', event.target.value)}
            />
          </Field>

          <div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-sm"
                disabled={locating}
                onClick={locate}
              >
                {locating ? <Spinner /> : null}
                {locating
                  ? 'Finding you…'
                  : coords
                    ? 'Update my location'
                    : 'Use my current location'}
              </button>
              {coords ? (
                <>
                  <span className="mono text-xs muted">
                    {formatCoordinates(coords.lat, coords.lng)}
                  </span>
                  <button
                    type="button"
                    className="btn btn-quiet btn-sm"
                    onClick={() => setCoords(null)}
                  >
                    Remove
                  </button>
                </>
              ) : null}
            </div>
            {errors.location || errors.latitude || errors.longitude ? (
              <p className="field-error">
                <span aria-hidden="true">!</span>
                <span>
                  {errors.location ?? errors.latitude ?? errors.longitude}
                </span>
              </p>
            ) : (
              <p className="hint">Optional. Shared only with this complaint.</p>
            )}
          </div>
        </fieldset>

        <fieldset className="card card-pad grid gap-4">
          <legend className="kicker px-1">If you know (optional)</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Type of waste"
              htmlFor="waste_type"
              error={errors.waste_type}
            >
              <select
                id="waste_type"
                className="select"
                value={values.waste_type}
                aria-invalid={Boolean(errors.waste_type)}
                onChange={(event) =>
                  update('waste_type', event.target.value as WasteType | '')
                }
              >
                <option value="">Not sure</option>
                {WASTE_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {wasteLabel(type)}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="How much is there?"
              htmlFor="quantity_severity"
              error={errors.quantity_severity}
            >
              <select
                id="quantity_severity"
                className="select"
                value={values.quantity_severity}
                aria-invalid={Boolean(errors.quantity_severity)}
                onChange={(event) =>
                  update(
                    'quantity_severity',
                    event.target.value as Severity | '',
                  )
                }
              >
                <option value="">Not sure</option>
                {SEVERITIES.map((severity) => (
                  <option key={severity} value={severity}>
                    {severityLabel(severity)}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <label className="check-row" htmlFor="intervention_required">
            <input
              id="intervention_required"
              type="checkbox"
              checked={values.intervention_required}
              onChange={(event) =>
                update('intervention_required', event.target.checked)
              }
            />
            <span>
              It is too much or too risky to handle myself — send a cleaner.
            </span>
          </label>

          <Field
            label="Anything else about the spot?"
            htmlFor="waste_context"
            hint="e.g. inside a building, blocking a drain, near a school."
            error={errors.waste_context}
          >
            <input
              id="waste_context"
              className="input"
              maxLength={2000}
              value={values.waste_context}
              aria-invalid={Boolean(errors.waste_context)}
              onChange={(event) => update('waste_context', event.target.value)}
            />
          </Field>

          <Field
            label="Phone number"
            htmlFor="phone"
            hint="Optional; up to 20 characters."
            error={errors.phone}
          >
            <input
              id="phone"
              className="input"
              type="tel"
              autoComplete="tel"
              maxLength={20}
              value={values.phone}
              aria-invalid={Boolean(errors.phone)}
              onChange={(event) => update('phone', event.target.value)}
            />
          </Field>
        </fieldset>

        <div>
          <label className="check-row" htmlFor="consent">
            <input
              id="consent"
              type="checkbox"
              checked={values.consent}
              aria-invalid={Boolean(errors.consent)}
              onChange={(event) => update('consent', event.target.checked)}
            />
            <span>I confirm this complaint may be stored and processed.</span>
          </label>
          {errors.consent ? (
            <p className="field-error">
              <span aria-hidden="true">!</span>
              <span>{errors.consent}</span>
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="submit"
            className="btn btn-primary btn-block sm:w-auto"
            disabled={submitting}
          >
            {submitting ? <Spinner /> : null}
            {submitting ? 'Submitting…' : 'Submit complaint'}
          </button>
          <Link to="/" className="btn btn-quiet btn-block sm:w-auto">
            Cancel
          </Link>
        </div>
      </form>
    </main>
  )
}
