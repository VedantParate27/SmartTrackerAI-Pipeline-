import { useEffect, useRef, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { Callout, Field, SectionCard } from '#/components/ui'
import { formatBytes } from '#/lib/format'
import { submitComplaint } from '#/lib/store'
import { CONFIG, PRIORITIES } from '#/lib/taxonomy'
import type { Attachment, Priority } from '#/lib/types'

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

/** FR-02: mandatory fields, contact format, attachment type and size. */
function validate(values: FormValues) {
  const errors: Partial<Record<keyof FormValues, string>> = {}

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
    errors.text = `Describe the problem in at least ${MIN_TEXT} characters so it can be classified.`
  }

  if (!values.consent) {
    errors.consent =
      'Please confirm you agree to the processing of this complaint.'
  }

  return errors
}

function validateFiles(files: File[]) {
  const problems: string[] = []
  const accepted: Attachment[] = []

  if (files.length > CONFIG.maxAttachments) {
    problems.push(`At most ${CONFIG.maxAttachments} attachments are accepted.`)
  }

  for (const file of files.slice(0, CONFIG.maxAttachments)) {
    if (!CONFIG.allowedAttachmentTypes.includes(file.type)) {
      problems.push(
        `"${file.name}" was rejected: only PDF, TXT, PNG and JPG are accepted.`,
      )
      continue
    }
    if (file.size > CONFIG.maxAttachmentBytes) {
      problems.push(
        `"${file.name}" was rejected: ${formatBytes(file.size)} exceeds the ${formatBytes(CONFIG.maxAttachmentBytes)} limit.`,
      )
      continue
    }
    accepted.push({ name: file.name, size: file.size, type: file.type })
  }

  return { problems, accepted }
}

function SubmitPage() {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [errors, setErrors] = useState<
    Partial<Record<keyof FormValues, string>>
  >({})
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [fileProblems, setFileProblems] = useState<string[]>([])
  const [submittedId, setSubmittedId] = useState<string | null>(null)
  const [failedAttempts, setFailedAttempts] = useState(0)
  const errorSummary = useRef<HTMLDivElement>(null)

  // Focus the summary after a rejected submit, once it has rendered (NFR-10).
  // Keyed on the attempt count so typing a fix never steals focus back.
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

  function onFiles(fileList: FileList | null) {
    const files = fileList ? Array.from(fileList) : []
    const { problems, accepted } = validateFiles(files)
    setFileProblems(problems)
    setAttachments(accepted)
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const found = validate(values)
    setErrors(found)

    if (Object.keys(found).length > 0) {
      setFailedAttempts((count) => count + 1)
      return
    }

    setSubmittedId(
      submitComplaint({
        requesterName: values.requesterName.trim(),
        contact: values.contact.trim(),
        text: values.text.trim(),
        priority: values.priority,
        attachments,
      }),
    )
  }

  if (submittedId) {
    return (
      <main id="main" className="wrap page max-w-2xl">
        <p className="kicker">Acknowledgement</p>
        <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
          Your grievance has been registered
        </h1>

        <div className="card card-pad mt-5">
          <span className="kicker">Tracking reference</span>
          <p className="mono mt-1 text-xl font-extrabold tracking-wide sm:text-2xl">
            {submittedId}
          </p>
          <p className="hint">
            Keep this reference. You will need it to check the status of the
            case.
          </p>
        </div>

        <div className="mt-4">
          <Callout tone="info" title="What happens next">
            <ol className="m-0 mt-1 list-decimal space-y-1 pl-4">
              <li>
                Automated analysis classifies the complaint and finds the
                responsible department.
              </li>
              <li>
                Relevant active policy sections are retrieved and a draft reply
                is prepared with citations.
              </li>
              <li>
                A support administrator reviews everything and approves, edits
                or reassigns the case.
              </li>
              <li>
                You receive the approved response on the contact detail you
                provided.
              </li>
            </ol>
          </Callout>
        </div>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row">
          <Link
            to="/track"
            search={{ id: submittedId }}
            className="btn btn-primary btn-block sm:w-auto"
          >
            Track this case
          </Link>
          <button
            type="button"
            className="btn btn-block sm:w-auto"
            onClick={() => {
              setValues(EMPTY)
              setAttachments([])
              setFileProblems([])
              setSubmittedId(null)
              setFailedAttempts(0)
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
        Write in your own words. You do not need to know which department
        handles the issue — that is worked out for you.
      </p>

      <div className="mt-5">
        <Callout tone="info" title="Privacy notice">
          Your name, contact detail and complaint text are stored so the case
          can be routed, answered and audited. Contact details are masked before
          any text is sent to a language model. Only authorised staff of the
          assigned department can open your case.
        </Callout>
      </div>

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
            aria-invalid={Boolean(errors.contact)}
            aria-describedby={errors.contact ? 'contact-error' : 'contact-hint'}
            onChange={(event) => update('contact', event.target.value)}
          />
        </Field>

        <Field
          label="What went wrong?"
          htmlFor="text"
          required
          hint={`${values.text.trim().length} of ${MIN_TEXT} characters minimum. Include dates, amounts or reference numbers if you have them.`}
          error={errors.text}
        >
          <textarea
            id="text"
            name="text"
            className="textarea"
            value={values.text}
            aria-invalid={Boolean(errors.text)}
            aria-describedby={errors.text ? 'text-error' : 'text-hint'}
            placeholder="Example: My salary was deducted last month without notice. Rs. 4,250 is missing from my payslip and my employee ID is EMP-20418."
            onChange={(event) => update('text', event.target.value)}
          />
        </Field>

        <Field label="How urgent is it?" htmlFor="priority">
          <select
            id="priority"
            name="priority"
            className="select"
            value={values.priority}
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

        <Field
          label="Attachments"
          htmlFor="attachments"
          hint={`Optional. Up to ${CONFIG.maxAttachments} files, ${formatBytes(CONFIG.maxAttachmentBytes)} each. PDF, TXT, PNG or JPG.`}
        >
          <input
            id="attachments"
            name="attachments"
            type="file"
            multiple
            className="file-input"
            accept={CONFIG.allowedAttachmentTypes.join(',')}
            aria-describedby="attachments-hint"
            onChange={(event) => onFiles(event.target.files)}
          />
        </Field>

        {fileProblems.length > 0 ? (
          <Callout tone="warn" title="Some files were not accepted">
            <ul className="m-0 mt-1 list-disc space-y-0.5 pl-4">
              {fileProblems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </Callout>
        ) : null}

        {attachments.length > 0 ? (
          <SectionCard title="Attached files" bodyClassName="card-pad pt-2">
            <ul className="m-0 list-none space-y-1 p-0 text-xs muted">
              {attachments.map((file) => (
                <li key={file.name} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate">{file.name}</span>
                  <span className="subtle shrink-0">
                    {formatBytes(file.size)}
                  </span>
                </li>
              ))}
            </ul>
          </SectionCard>
        ) : null}

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
          <button type="submit" className="btn btn-primary btn-block sm:w-auto">
            Submit grievance
          </button>
          <Link to="/" className="btn btn-quiet btn-block sm:w-auto">
            Cancel
          </Link>
        </div>
      </form>
    </main>
  )
}
