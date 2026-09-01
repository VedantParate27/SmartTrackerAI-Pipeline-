import { Link, createFileRoute } from '@tanstack/react-router'
import { BackendStatus } from '#/components/ui'

export const Route = createFileRoute('/')({ component: Home })

const PIPELINE = [
  {
    step: '01',
    title: 'Intake',
    body: 'FastAPI stores the complaint and returns the tracking reference used everywhere else.',
  },
  {
    step: '02',
    title: 'Classify & route',
    body: 'Category, entities, department and confidence appear only when backend processing returns them.',
  },
  {
    step: '03',
    title: 'Retrieve policy',
    body: 'Missing policy or retrieval results stay visibly unavailable instead of being filled in.',
  },
  {
    step: '04',
    title: 'Draft with citations',
    body: 'The UI accepts a backend draft or AI failure state and never assumes generation succeeded.',
  },
  {
    step: '05',
    title: 'Human approval',
    body: 'An admin approves the reply through the backend, which stores it and returns the new status.',
  },
]

const ENTRIES = [
  {
    to: '/submit',
    label: 'Submit a grievance',
    body: 'One form. No department to choose.',
  },
  {
    to: '/track',
    label: 'Track a case',
    body: 'Check status with your reference number.',
  },
  {
    to: '/admin',
    label: 'Review workspace',
    body: 'Admin queue, drafts and approvals.',
  },
] as const

function Home() {
  return (
    <main id="main" className="wrap page">
      <section className="max-w-3xl">
        <p className="kicker">Grievance routing &amp; resolution pipeline</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">
          Describe the problem. We find the right desk and the right policy.
        </h1>
        <p className="mt-3 text-base leading-relaxed muted sm:text-lg">
          SmartTracker AI sends your complaint through the FastAPI request model
          and displays the backend response without inventing fields.
          Classification, evidence, and approved replies appear when the API
          provides them.
        </p>
      </section>

      <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:items-center">
        <Link to="/submit" className="btn btn-primary btn-block sm:w-auto">
          Submit a grievance
        </Link>
        <Link to="/track" className="btn btn-block sm:w-auto">
          Track an existing case
        </Link>
      </div>

      <div className="mt-8">
        <BackendStatus />
      </div>

      <section className="mt-10" aria-labelledby="entries-heading">
        <h2 id="entries-heading" className="sr-only">
          Where to start
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {ENTRIES.map((entry) => (
            <Link
              key={entry.to}
              to={entry.to}
              className="card card-pad no-underline transition-colors hover:border-(--accent)"
            >
              <span className="block text-sm font-extrabold text-(--fg)">
                {entry.label}
              </span>
              <span className="mt-1 block text-xs muted">{entry.body}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className="mt-10" aria-labelledby="pipeline-heading">
        <h2 id="pipeline-heading" className="text-lg font-extrabold">
          How a case moves
        </h2>
        <ol className="mt-4 grid list-none gap-3 p-0 md:grid-cols-5">
          {PIPELINE.map((item) => (
            <li key={item.step} className="card card-pad">
              <span className="kicker">{item.step}</span>
              <h3 className="mt-1 text-sm font-extrabold">{item.title}</h3>
              <p className="mt-1 text-xs leading-relaxed muted">{item.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-10" aria-labelledby="safeguards-heading">
        <h2 id="safeguards-heading" className="text-lg font-extrabold">
          What the system will not do
        </h2>
        <ul className="mt-3 grid list-none gap-2 p-0 text-sm muted sm:grid-cols-2">
          {[
            'Send an AI-written response without a named human approver.',
            'Show mock policy evidence when retrieval results are missing.',
            'Hide a missing or low-confidence AI result behind a fake success state.',
            'Give legal, medical or emergency advice, or make a final disciplinary decision.',
          ].map((item) => (
            <li key={item} className="card card-pad flex gap-2">
              <span
                aria-hidden="true"
                className="font-extrabold text-(--danger)"
              >
                ✕
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}
