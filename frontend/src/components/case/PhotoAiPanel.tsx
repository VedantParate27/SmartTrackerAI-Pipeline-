import { UploadForm } from '#/components/PhotoCheck'
import {
  AIStatusPill,
  BackendPhoto,
  Callout,
  ConfidenceMeter,
  ErrorState,
  LoadingState,
  SectionCard,
  Spinner,
} from '#/components/ui'
import { aiRunLost, backendFileUrl } from '#/lib/api'
import type { AdminAIReview } from '#/lib/api'
import {
  aiErrorInfo,
  aiSeverityLabel,
  aiWasteLabel,
  reviewReasonText,
} from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'

/** One AI failure entry: the plain reason, then the code and details for staff. */
export function AiErrorList({ errors }: { errors: unknown[] }) {
  return (
    <ul className="m-0 grid list-none gap-1.5 p-0">
      {errors.map((entry, index) => {
        const info = aiErrorInfo(entry)
        return (
          <li key={`${info.code}-${index}`} className="text-xs">
            <span className="font-bold">{info.message}</span>{' '}
            <span className="mono subtle">{info.code}</span>
            {info.details ? (
              <span className="block subtle [overflow-wrap:anywhere]">
                {info.details}
              </span>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

/**
 * The latest analysis of the citizen's photo, exactly as the AI returned it.
 * Everything here is advisory: escalate_to_authority and needs_human_review
 * never act on their own — the decision panel below is the authority.
 */
export default function PhotoAiPanel({
  review,
  loading,
  error,
  onRetry,
  stalled,
  needsId,
  trackingId,
  token,
  canUpload,
  onUploaded,
}: {
  /** null when the citizen never attached a photo. */
  review: AdminAIReview | null
  loading: boolean
  error: string | null
  onRetry: () => void
  stalled: boolean
  /** The review is keyed by the numeric id; true while it is unresolvable. */
  needsId: boolean
  trackingId: string
  token: string
  /** Admins may attach or replace the photo while the case is open. */
  canUpload: boolean
  onUploaded: () => void
}) {
  const analysis = review?.analysis ?? null
  const lost =
    analysis?.ai_status === 'pending' && aiRunLost(analysis.created_at)
  // Keep what is on screen when only a refresh failed.
  const failedLoad = Boolean(error) && !review
  const upload =
    canUpload && !needsId && !failedLoad && !(loading && !review) ? (
      <details>
        <summary className="cursor-pointer text-sm font-bold">
          {analysis ? 'Replace the photo' : 'Attach a photo for the citizen'}
        </summary>
        <div className="mt-3">
          <UploadForm
            trackingId={trackingId}
            token={token}
            cta={analysis ? 'Upload new photo' : 'Attach photo'}
            onDone={onUploaded}
          />
        </div>
      </details>
    ) : null

  return (
    <SectionCard
      title="Photo & AI check"
      meta={
        analysis ? (
          <span role="status">
            <AIStatusPill
              status={analysis.ai_status}
              usable={analysis.image_usable}
              lost={lost}
            />
          </span>
        ) : undefined
      }
    >
      <div className="grid gap-4">
        {error && !failedLoad ? (
          <ErrorState
            title="The photo analysis could not be refreshed"
            message={error}
            onRetry={onRetry}
          />
        ) : null}
        {needsId ? (
          <p className="m-0 text-sm muted">
            Needs the internal complaint id, which could not be resolved.
          </p>
        ) : failedLoad && error ? (
          <ErrorState
            title="The photo analysis could not be loaded"
            message={error}
            onRetry={onRetry}
          />
        ) : loading && !review ? (
          <LoadingState label="Loading the photo analysis…" />
        ) : !analysis ? (
          <p className="m-0 text-sm muted">
            No photo yet — the citizen has not attached one. Decide from the
            description.
          </p>
        ) : (
          <div className="grid gap-4 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
            {analysis.image_url ? (
              <BackendPhoto
                src={backendFileUrl(analysis.image_url)}
                alt="Citizen's photo of the waste"
                className="photo-frame"
              />
            ) : null}

            <div className="grid content-start gap-3">
              {analysis.ai_status === 'pending' && lost ? (
                <Callout
                  tone="warn"
                  title="The AI check never finished — decide manually"
                >
                  The run was probably interrupted, for example by a server
                  restart. Uploading the photo again starts a new one.
                </Callout>
              ) : analysis.ai_status === 'pending' ? (
                <p className="m-0 flex items-center gap-2 text-sm muted">
                  <Spinner />
                  {stalled
                    ? 'Still running after the AI timeout window. Refresh later.'
                    : 'The AI is analysing the photo…'}
                </p>
              ) : null}

              {analysis.ai_status === 'failed' ? (
                <Callout
                  tone="warn"
                  title="The AI check failed — decide manually"
                >
                  <AiErrorList errors={review?.errors ?? []} />
                </Callout>
              ) : null}

              {analysis.ai_status === 'completed' ? (
                <>
                  {analysis.image_usable === false ? (
                    <Callout
                      tone="warn"
                      title="The AI could not use this photo"
                    >
                      {analysis.unusable_reason ?? 'No reason was given.'}
                    </Callout>
                  ) : null}

                  <dl className="m-0 grid gap-3 sm:grid-cols-2">
                    <div className="ai-cell">
                      <dt className="kicker">Waste type</dt>
                      <dd className="ai-value m-0">
                        {aiWasteLabel(analysis.waste_type) ?? 'Not predicted'}
                      </dd>
                    </div>
                    <div className="ai-cell">
                      <dt className="kicker">Scale</dt>
                      <dd className="ai-value m-0">
                        {aiSeverityLabel(analysis.severity) ?? 'Not predicted'}
                      </dd>
                    </div>
                  </dl>

                  <div className="grid gap-1.5">
                    <ConfidenceMeter
                      label="Type confidence"
                      value={analysis.waste_type_confidence}
                    />
                    <ConfidenceMeter
                      label="Scale confidence"
                      value={analysis.severity_confidence}
                    />
                  </div>

                  {analysis.escalate_to_authority ||
                  analysis.needs_human_review ||
                  analysis.recurring_flag ? (
                    <ul className="flag-list" aria-label="AI flags">
                      {analysis.escalate_to_authority ? (
                        <li className="pill normal-case" data-tone="danger">
                          Suggests escalating to the authority
                        </li>
                      ) : null}
                      {analysis.needs_human_review ? (
                        <li className="pill normal-case" data-tone="warn">
                          Asks for human review
                        </li>
                      ) : null}
                      {analysis.recurring_flag ? (
                        <li className="pill normal-case" data-tone="warn">
                          Recurring spot
                        </li>
                      ) : null}
                    </ul>
                  ) : null}

                  {review?.review_reasons?.length ? (
                    <ul className="m-0 grid list-none gap-1 p-0 text-xs muted">
                      {review.review_reasons.map((reason, index) => (
                        <li key={index}>· {reviewReasonText(reason)}</li>
                      ))}
                    </ul>
                  ) : null}

                  {analysis.reasoning ? (
                    <div className="ai-note">
                      <span className="kicker">What the AI saw</span>
                      <p className="mt-1 mb-0">{analysis.reasoning}</p>
                    </div>
                  ) : null}

                  {analysis.follow_up_question ? (
                    <div className="ai-note">
                      <span className="kicker">
                        Suggested question for the citizen
                      </span>
                      <p className="mt-1 mb-0">{analysis.follow_up_question}</p>
                      <p className="mt-1 mb-0 text-xs muted">
                        To ask it, record “Request information” below with the
                        question as the note.
                      </p>
                    </div>
                  ) : null}

                  {analysis.disposal_guidance ? (
                    <div className="ai-note">
                      <span className="kicker">
                        Suggested disposal guidance
                      </span>
                      <p className="mt-1 mb-0">{analysis.disposal_guidance}</p>
                    </div>
                  ) : null}

                  {review?.errors?.length ? (
                    <details className="text-xs">
                      <summary className="cursor-pointer muted">
                        {review.errors.length} stage warning
                        {review.errors.length === 1 ? '' : 's'} from the AI run
                      </summary>
                      <div className="mt-2">
                        <AiErrorList errors={review.errors} />
                      </div>
                    </details>
                  ) : null}
                </>
              ) : null}

              <p className="m-0 text-xs subtle">
                {analysis.prior_reports_count !== null
                  ? `${analysis.prior_reports_count} earlier report${analysis.prior_reports_count === 1 ? '' : 's'} within ${analysis.radius_m ?? '?'} m · `
                  : ''}
                Photo uploaded {formatDateTime(analysis.created_at)}
                {analysis.latency_ms ? ` · ${analysis.latency_ms} ms` : ''}
                {analysis.model_name
                  ? ` · ${analysis.model_name} ${analysis.model_version ?? ''}`
                  : ''}
                . Advisory only — your decision below is what counts.
              </p>
            </div>
          </div>
        )}
        {upload}
      </div>
    </SectionCard>
  )
}
