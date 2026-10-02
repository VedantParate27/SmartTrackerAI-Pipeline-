import { Link, createFileRoute } from '@tanstack/react-router'
import { BackendStatus } from '#/components/ui'

export const Route = createFileRoute('/')({ component: Home })

const PIPELINE = [
  {
    step: '01',
    title: 'Report',
    body: 'A citizen describes the waste, adds a photo and, optionally, where it is. The backend returns a tracking reference.',
  },
  {
    step: '02',
    title: 'Photo check',
    body: 'An AI looks at the photo — waste type, how much, whether it needs the authorities — with a confidence score for each.',
  },
  {
    step: '03',
    title: 'Human decision',
    body: 'An admin weighs that advice and decides: send a cleaner, resolve, escalate, ask for more information or dismiss.',
  },
  {
    step: '04',
    title: 'Cleanup + proof',
    body: 'The cleaner uploads an after photo, and an AI compares it with the citizen’s before photo.',
  },
  {
    step: '05',
    title: 'Verified & measured',
    body: 'An admin approves or rejects the proof. Every step lands in the event log for process mining.',
  },
]

const ENTRIES = [
  {
    to: '/submit',
    label: 'Report waste',
    body: 'One form. Location and type are optional.',
  },
  {
    to: '/track',
    label: 'Track a complaint',
    body: 'See status, and all your past reports.',
  },
  {
    to: '/cleaner',
    label: 'Cleaner tasks',
    body: 'Assigned jobs and photo proof.',
  },
  {
    to: '/admin',
    label: 'Admin workspace',
    body: 'AI review, dispatch and verification.',
  },
] as const

function Home() {
  return (
    <main id="main" className="wrap page">
      <section className="max-w-3xl">
        <p className="kicker">Waste complaint triage &amp; resolution</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">
          Report the mess. AI sorts it, a person decides, a cleaner proves it's
          done.
        </h1>
        <p className="mt-3 text-base leading-relaxed muted sm:text-lg">
          SmartTracker AI routes every waste complaint through a
          confidence-gated AI assistant and a human reviewer, then tracks the
          cleanup to a verified photo.
        </p>
      </section>

      <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:items-center">
        <Link to="/submit" className="btn btn-primary btn-block sm:w-auto">
          Report waste
        </Link>
        <Link to="/track" className="btn btn-block sm:w-auto">
          Track a complaint
        </Link>
      </div>

      <div className="mt-8">
        <BackendStatus />
      </div>

      <section className="mt-10" aria-labelledby="entries-heading">
        <h2 id="entries-heading" className="sr-only">
          Where to start
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
          How a complaint moves
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
            'Let the AI resolve or dispatch anything on its own.',
            'Route hazardous or medical waste without a human check.',
            'Approve a cleanup on the AI’s word — a person checks every proof photo.',
            'Invent a prediction when the AI service has not sent one.',
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
