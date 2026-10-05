import { useEffect, useRef, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { Callout, Field, StatusPill } from '#/components/ui'
import { formatBytes } from '#/lib/format'
import { submitWasteComplaint } from '#/lib/api'
import { PRIORITIES } from '#/lib/taxonomy'
import type { Complaint, ComplaintLocation, Priority } from '#/lib/types'

export const Route = createFileRoute('/submit')({ component: SubmitPage })

interface FormValues {
  requesterName: string
  contact: string
  priority: Priority
  text: string
  consent: boolean
}

const EMPTY: FormValues = {
  requesterName: '',
  contact: '',
  priority: 'Medium',
  text: '',
  consent: false,
}

const MIN_TEXT = 30
const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_IMAGE_BYTES = 10 * 1024 * 1024 // 10 MB

type GpsStatus = 'idle' | 'requesting' | 'granted' | 'denied' | 'unavailable'

function validate(values: FormValues, imageFile: File | null) {
  const errors: Partial<Record<keyof FormValues | 'image', string>> = {}

  if (values.requesterName.trim().length < 2) {
    errors.requesterName = 'Enter your name (at least 2 characters).'
  }

  const contact = values.contact.trim()
  const isEmail = /^[\w.+-]+@[\w-]+\.[\w.]{2,}$/.test(contact)
  const isPhone = /^(?:\+91[\s-]?)?[6-9]\d{9}$/.test(contact.replace(/\s/g, ''))
  if (!contact) {
    errors.contact = 'Enter an email address or a 10-digit mobile number.'
  } else if (!isEmail && !isPhone) {
    errors.contact =
      'That does not look like a valid email address or mobile number.'
  }

  if (values.text.trim().length < MIN_TEXT) {
    errors.text = `Describe the problem in at least ${MIN_TEXT} characters.`
  }

  if (!imageFile) {
    errors.image = 'An image of the waste issue is required.'
  } else if (!ALLOWED_IMAGE_TYPES.includes(imageFile.type)) {
    errors.image =
      'Unsupported image type. Only JPEG, PNG, and WEBP are accepted.'
  } else if (imageFile.size > MAX_IMAGE_BYTES) {
    errors.image = `Image is too large. Maximum allowed size is ${formatBytes(MAX_IMAGE_BYTES)}.`
  }

  if (!values.consent) {
    errors.consent =
      'Please confirm you agree to the processing of this complaint.'
  }

  return errors
}

function SubmitPage() {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<
    Partial<Record<keyof FormValues | 'image', string>>
  >({})
  const [serverError, setServerError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submittedComplaint, setSubmittedComplaint] =
    useState<Complaint | null>(null)
  const [failedAttempts, setFailedAttempts] = useState(0)
  const errorSummary = useRef<HTMLDivElement>(null)

  const [gpsStatus, setGpsStatus] = useState<GpsStatus>('idle')
  const [gpsCoords, setGpsCoords] = useState<{
    latitude: number
    longitude: number
  } | null>(null)
  const [manualAddress, setManualAddress] = useState('')

  function requestGpsLocation() {
    if (!('geolocation' in navigator)) {
      setGpsStatus('unavailable')
      return
    }

    setGpsStatus('requesting')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setGpsCoords({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        })
        setGpsStatus('granted')
      },
      (error) => {
        setGpsCoords(null)
        setGpsStatus(
          error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable',
        )
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    )
  }

  function clearGpsLocation() {
    setGpsCoords(null)
    setGpsStatus('idle')
  }

  function currentLocation(): ComplaintLocation | null {
    if (gpsStatus === 'granted' && gpsCoords) {
      return {
        type: 'gps',
        latitude: gpsCoords.latitude,
        longitude: gpsCoords.longitude,
        manualAddress: null,
      }
    }
    if (manualAddress.trim()) {
      return {
        type: 'manual',
        latitude: null,
        longitude: null,
        manualAddress: manualAddress.trim(),
      }
    }
    return null
  }

  useEffect(() => {
    if (failedAttempts > 0) errorSummary.current?.focus()
  }, [failedAttempts])

  function update<TKey extends keyof FormValues>(
    key: TKey,
    value: FormValues[TKey],
  ) {
    setValues((current) => ({ ...current, [key]: value }))
    setErrors((current) => ({ ...current, [key]: undefined }))
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    setServerError(null)

    const found = validate(values, imageFile)
    setErrors(found)

    if (Object.keys(found).length > 0) {
      setFailedAttempts((count) => count + 1)
      return
    }

    setSubmitting(true)

    try {
      const formData = new FormData()
      formData.append('complaint_text', values.text.trim())

      if (imageFile) {
        formData.append('image', imageFile)
      }

      const loc = currentLocation()
      if (loc) {
        if (
          loc.type === 'gps' &&
          loc.latitude != null &&
          loc.longitude != null
        ) {
          formData.append('location_type', 'gps')
          formData.append('latitude', String(loc.latitude))
          formData.append('longitude', String(loc.longitude))
        } else if (loc.type === 'manual' && loc.manualAddress) {
          formData.append('location_type', 'manual')
          formData.append('manual_address', loc.manualAddress)
        }
      }

      const complaint = await submitWasteComplaint(formData)
      setSubmittedComplaint(complaint)
    } catch (error) {
      console.error('Failed to submit complaint:', error)
      setServerError(
        error instanceof Error
          ? error.message
          : 'Unable to submit the complaint. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (submittedComplaint) {
    return (
      <main id="main" className="wrap page max-w-2xl">
        <p className="kicker">Acknowledgement</p>
        <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
          Your grievance has been registered
        </h1>

        <div className="card card-pad mt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <span className="kicker">Tracking reference</span>
              <p className="mono mt-1 text-xl font-extrabold tracking-wide sm:text-2xl">
                {submittedComplaint.id}
              </p>
            </div>
            <div>
              <StatusPill status={submittedComplaint.status} />
            </div>
          </div>
          <p className="hint mt-2">
            Keep this reference. You will need it to check the status of your
            grievance.
          </p>
        </div>

        <div className="mt-4">
          <Callout tone="info" title="What happens next">
            <ol className="m-0 mt-1 list-decimal space-y-1 pl-4">
              <li>
                Automated AI vision analysis evaluates the complaint image and
                determines waste severity.
              </li>
              <li>
                If verification or human review is required, the report is
                routed for admin review.
              </li>
              <li>
                An administrator assigns a cleaner team or verifies the task
                upon completion.
              </li>
              <li>
                You can track updates in real-time using your tracking
                reference.
              </li>
            </ol>
          </Callout>
        </div>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row">
          <Link
            to="/track"
            search={{ id: submittedComplaint.id }}
            className="btn btn-primary btn-block sm:w-auto"
          >
            Track this case
          </Link>
          <button
            type="button"
            className="btn btn-block sm:w-auto"
            onClick={() => {
              setValues(EMPTY)
              setImageFile(null)
              setSubmittedComplaint(null)
              setServerError(null)
              setFailedAttempts(0)
              clearGpsLocation()
              setManualAddress('')
            }}
          >
            Submit another grievance
          </button>
        </div>
      </main>
    )
  }

  const errorList = Object.values(errors).filter(Boolean)

  return (
    <main id="main" className="wrap page max-w-2xl">
      <p className="kicker">Step 1 of 1</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
        Submit a grievance
      </h1>
      <p className="mt-2 text-sm leading-relaxed muted">
        Describe the issue and upload a clear photo. AI vision will automatically
        detect waste type and severity.
      </p>

      <div className="mt-5">
        <Callout tone="info" title="Privacy notice">
          Your complaint text and image are stored so the case can be routed,
          analyzed, and resolved by cleanup teams.
        </Callout>
      </div>

      {serverError ? (
        <div className="mt-4">
          <Callout tone="danger" title="Submission failed">
            {serverError}
          </Callout>
        </div>
      ) : null}

      {errorList.length > 0 ? (
        <div
          className="mt-4"
          ref={errorSummary}
          tabIndex={-1}
          aria-live="assertive"
        >
          <Callout
            tone="danger"
            title={`${errorList.length} ${errorList.length === 1 ? 'field needs' : 'fields need'} attention`}
          >
            <ul className="m-0 mt-1 list-disc space-y-0.5 pl-4">
              {errorList.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </Callout>
        </div>
      ) : null}

      <form className="mt-5 grid gap-4" onSubmit={onSubmit} noValidate>
        <Field
          label="Your name"
          htmlFor="requesterName"
          required
          error={errors.requesterName}
        >
          <input
            id="requesterName"
            name="requesterName"
            className="input"
            autoComplete="name"
            value={values.requesterName}
            disabled={submitting}
            aria-invalid={Boolean(errors.requesterName)}
            aria-describedby={
              errors.requesterName ? 'requesterName-error' : undefined
            }
            onChange={(event) => update('requesterName', event.target.value)}
          />
        </Field>

        <Field
          label="Email or mobile number"
          htmlFor="contact"
          required
          hint="Used only to acknowledge the case and send the approved response."
          error={errors.contact}
        >
          <input
            id="contact"
            name="contact"
            className="input"
            inputMode="email"
            autoComplete="email"
            value={values.contact}
            disabled={submitting}
            aria-invalid={Boolean(errors.contact)}
            aria-describedby={errors.contact ? 'contact-error' : 'contact-hint'}
            onChange={(event) => update('contact', event.target.value)}
          />
        </Field>

        <Field
          label="What went wrong?"
          htmlFor="text"
          required
          hint={`${values.text.trim().length} of ${MIN_TEXT} characters minimum. Describe the problem or location context.`}
          error={errors.text}
        >
          <textarea
            id="text"
            name="text"
            className="textarea"
            value={values.text}
            disabled={submitting}
            aria-invalid={Boolean(errors.text)}
            aria-describedby={errors.text ? 'text-error' : 'text-hint'}
            placeholder="Example: Uncollected garbage pile blocking pedestrian path near main street market."
            onChange={(event) => update('text', event.target.value)}
          />
        </Field>

        <Field
          label="Waste Image"
          htmlFor="image"
          required
          hint={`Upload a photo of the waste (JPEG, PNG, or WEBP, max ${formatBytes(MAX_IMAGE_BYTES)}).`}
          error={errors.image}
        >
          <input
            id="image"
            name="image"
            type="file"
            className="file-input"
            accept="image/jpeg,image/png,image/webp"
            disabled={submitting}
            aria-invalid={Boolean(errors.image)}
            aria-describedby={errors.image ? 'image-error' : 'image-hint'}
            onChange={(event) => {
              const file = event.target.files?.[0] ?? null
              setImageFile(file)
              setErrors((curr) => ({ ...curr, image: undefined }))
            }}
          />
        </Field>

        <Field
          label="Location"
          htmlFor="manualAddress"
          hint="Optional, but helps route the cleanup crew. Share your current location or type an address."
        >
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn"
                onClick={requestGpsLocation}
                disabled={gpsStatus === 'requesting' || submitting}
              >
                {gpsStatus === 'requesting'
                  ? 'Getting your location…'
                  : gpsStatus === 'granted'
                    ? 'Location shared'
                    : 'Share my current location'}
              </button>
              {gpsStatus === 'granted' ? (
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={clearGpsLocation}
                  disabled={submitting}
                >
                  Clear
                </button>
              ) : null}
            </div>

            {gpsStatus === 'granted' && gpsCoords ? (
              <p className="hint">
                Using your current location ({gpsCoords.latitude.toFixed(5)},{' '}
                {gpsCoords.longitude.toFixed(5)}).
              </p>
            ) : null}

            {gpsStatus === 'denied' ? (
              <Callout tone="warn" title="Location permission denied">
                You can still type an address below instead.
              </Callout>
            ) : null}

            {gpsStatus === 'unavailable' ? (
              <Callout tone="warn" title="Location unavailable">
                Your browser or device could not provide a location. Type an
                address below instead.
              </Callout>
            ) : null}

            {gpsStatus !== 'granted' ? (
              <input
                id="manualAddress"
                name="manualAddress"
                className="input"
                placeholder="e.g. Near 5th Cross Road, Indiranagar"
                value={manualAddress}
                disabled={submitting}
                onChange={(event) => setManualAddress(event.target.value)}
              />
            ) : null}
          </div>
        </Field>

        <Field label="How urgent is it?" htmlFor="priority">
          <select
            id="priority"
            name="priority"
            className="select"
            value={values.priority}
            disabled={submitting}
            onChange={(event) =>
              update('priority', event.target.value as Priority)
            }
          >
            {PRIORITIES.map((priority) => (
              <option key={priority} value={priority}>
                {priority}
              </option>
            ))}
          </select>
        </Field>

        <div>
          <label className="check-row" htmlFor="consent">
            <input
              id="consent"
              name="consent"
              type="checkbox"
              checked={values.consent}
              disabled={submitting}
              aria-invalid={Boolean(errors.consent)}
              onChange={(event) => update('consent', event.target.checked)}
            />
            <span>
              I confirm the details above are correct and I agree to this
              complaint being stored and processed to resolve it.
              <span className="req" aria-hidden="true">
                *
              </span>
            </span>
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
            {submitting ? 'Submitting grievance...' : 'Submit grievance'}
          </button>
          <Link to="/" className="btn btn-quiet btn-block sm:w-auto">
            Cancel
          </Link>
        </div>
      </form>
    </main>
  )
}
