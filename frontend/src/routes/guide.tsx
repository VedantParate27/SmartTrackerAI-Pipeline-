import { useMemo, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Callout, Field } from '#/components/ui'
import { formatDate } from '#/lib/format'
import { DOCUMENT_GUIDES } from '#/lib/seed'
import type { DocumentGuide } from '#/lib/types'

export const Route = createFileRoute('/guide')({ component: GuidePage })

/** FR-29: identify a supported document or service from a plain-language query. */
function matchGuides(query: string) {
  const cleaned = query.trim().toLowerCase()
  if (cleaned.length < 2) return []

  return DOCUMENT_GUIDES.map((guide) => {
    const aliasHit = guide.aliases.some(
      (alias) => cleaned.includes(alias) || alias.includes(cleaned),
    )
    const titleHits = guide.title
      .toLowerCase()
      .split(/[^a-z]+/)
      .filter((word) => word.length > 3 && cleaned.includes(word)).length

    return { guide, score: (aliasHit ? 2 : 0) + titleHits }
  })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .map((item) => item.guide)
}

function GuideDetail({ guide }: { guide: DocumentGuide }) {
  return (
    <article className="grid gap-4">
      <header className="card card-pad">
        <span className="kicker">{guide.authority}</span>
        <h2 className="mt-1 text-xl font-extrabold">{guide.title}</h2>
        <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="kicker">Fees</dt>
            <dd className="m-0">{guide.fees}</dd>
          </div>
          <div>
            <dt className="kicker">Processing time</dt>
            <dd className="m-0">{guide.processingTime}</dd>
          </div>
          <div>
            <dt className="kicker">Validity</dt>
            <dd className="m-0">{guide.validity}</dd>
          </div>
        </dl>
      </header>

      <section className="card">
        <div className="card-head">
          <h3 className="card-title">Documents you need</h3>
        </div>
        <ul className="m-0 list-none divide-rows p-0">
          {guide.requiredDocuments.map((item) => (
            <li key={item} className="flex gap-2 px-4 py-2.5 text-sm">
              <span
                aria-hidden="true"
                className="font-extrabold text-(--accent)"
              >
                ✓
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <div className="card-head">
          <h3 className="card-title">Accepted proofs</h3>
        </div>
        <ul className="m-0 list-disc space-y-1.5 py-3 pl-8 pr-4 text-sm muted">
          {guide.acceptableProofs.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section className="card">
        <div className="card-head">
          <h3 className="card-title">Steps to apply</h3>
        </div>
        <ol className="m-0 list-decimal space-y-1.5 py-3 pl-8 pr-4 text-sm">
          {guide.steps.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ol>
      </section>

      {/* FR-31: always show where this came from and when it was last updated. */}
      <Callout tone="info" title="Source">
        {guide.source} · last updated {formatDate(guide.lastUpdated)}. Only the
        fields recorded in this source are shown; anything not listed here has
        not been filled in. Confirm fees and timelines with the issuing
        authority before you apply.
      </Callout>
    </article>
  )
}

function GuidePage() {
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [searched, setSearched] = useState(false)

  const matches = useMemo(() => matchGuides(query), [query])
  const selected = selectedId
    ? (DOCUMENT_GUIDES.find((guide) => guide.id === selectedId) ?? null)
    : matches.length === 1
      ? matches[0]
      : null

  return (
    <main id="main" className="wrap page max-w-3xl">
      <p className="kicker">Document requirements guide</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
        What do I need to apply?
      </h1>
      <p className="mt-2 text-sm muted">
        Ask in plain language — for example “what documents for a new passport”.
        You do not need to create a complaint to use this.
      </p>

      <form
        className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-end"
        onSubmit={(event) => {
          event.preventDefault()
          setSelectedId(null)
          setSearched(true)
        }}
      >
        <div className="flex-1">
          <Field label="Your question" htmlFor="guide-query">
            <input
              id="guide-query"
              className="input"
              value={query}
              placeholder="documents needed for driving licence"
              onChange={(event) => {
                setQuery(event.target.value)
                setSelectedId(null)
                setSearched(false)
              }}
            />
          </Field>
        </div>
        <button type="submit" className="btn btn-primary">
          Find checklist
        </button>
      </form>

      <div className="mt-6" aria-live="polite">
        {/* FR-32: an ambiguous query asks the user to choose. */}
        {!selected && matches.length > 1 ? (
          <div className="grid gap-3">
            <Callout tone="warn" title="More than one service matches">
              Pick the one you meant. Nothing is guessed for you.
            </Callout>
            <div className="grid gap-2 sm:grid-cols-2">
              {matches.map((guide) => (
                <button
                  key={guide.id}
                  type="button"
                  className="card card-pad text-left"
                  onClick={() => setSelectedId(guide.id)}
                >
                  <span className="block text-sm font-extrabold">
                    {guide.title}
                  </span>
                  <span className="mt-0.5 block text-xs muted">
                    {guide.authority}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {/* FR-32: an unsupported query returns suggestions, never invented steps. */}
        {searched && query.trim().length >= 2 && matches.length === 0 ? (
          <div className="grid gap-3">
            <Callout tone="warn" title="Not a supported service yet">
              No checklist is recorded for “{query.trim()}”, so no steps can be
              shown. The services covered in this release are listed below.
            </Callout>
            <SupportedList onPick={setSelectedId} />
          </div>
        ) : null}

        {selected ? <GuideDetail guide={selected} /> : null}

        {!selected && !searched && matches.length === 0 ? (
          <SupportedList onPick={setSelectedId} />
        ) : null}
      </div>
    </main>
  )
}

function SupportedList({ onPick }: { onPick: (id: string) => void }) {
  return (
    <section aria-labelledby="supported-heading">
      <h2 id="supported-heading" className="kicker">
        Supported services
      </h2>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {DOCUMENT_GUIDES.map((guide) => (
          <button
            key={guide.id}
            type="button"
            className="card card-pad text-left transition-colors hover:border-(--accent)"
            onClick={() => onPick(guide.id)}
          >
            <span className="block text-sm font-extrabold">{guide.title}</span>
            <span className="mt-0.5 block text-xs muted">
              {guide.authority}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
