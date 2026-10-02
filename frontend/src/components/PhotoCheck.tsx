import { useEffect, useRef, useState } from 'react'
import PhotoInput from './PhotoInput'
import {
  AIStatusPill,
  BackendPhoto,
  Callout,
  ErrorState,
  LoadingState,
  Spinner,
} from './ui'
import {
  aiRunLost,
  backendFileUrl,
  getAIAnalysis,
  uploadComplaintImage,
} from '#/lib/api'
import type { WasteAIAnalysis } from '#/lib/api'
import { isExpiredSession, signOut } from '#/lib/auth'
import { aiSeverityLabel, aiWasteLabel } from '#/lib/complaint-format'
import { useApi, usePolling } from '#/lib/use-api'

/**
 * The citizen's view of their photo and its automatic check. The analysis is
 * advisory — staff still review every complaint — so codes and confidence
 * scores stay on the admin side; the citizen sees what matters to them.
 */
export default function PhotoCheck({
  trackingId,
  token,
  canUpload,
  onUploaded,
  onSettled,
}: {
  trackingId: string
  token: string
  /** Owner (or admin) of an open complaint: may add or replace the photo. */
  canUpload: boolean
  onUploaded?: () => void
  /** The background check finished while this was on screen. */
  onSettled?: () => void
}) {
  const analysis = useApi(
    (signal) => getAIAnalysis(trackingId, token, signal),
    [trackingId, token],
  )
  const result = analysis.data
  const status = result?.ai_status ?? null
  const lost = result?.ai_status === 'pending' && aiRunLost(result.created_at)
  const stalled = usePolling(status === 'pending' && !lost, analysis.reload, {
    busy: analysis.loading,
    runKey: result?.id ?? null,
  })

  const previous = useRef(status)
  useEffect(() => {
    if (
      previous.current === 'pending' &&
      status !== null &&
      status !== 'pending'
    ) {
      onSettled?.()
    }
    previous.current = status
  }, [status, onSettled])

  if (analysis.loading && !result && !analysis.error) {
    return <LoadingState label="Loading your photo…" />
  }
  if (analysis.error && !result) {
    return (
      <ErrorState
        title="Photo status could not be loaded"
        message={analysis.error}
        onRetry={analysis.reload}
        onReauth={analysis.expired ? signOut : undefined}
      />
    )
  }

  return (
    <div className="grid gap-4">
      {analysis.error ? (
        <ErrorState
          title="Photo status could not be refreshed"
          message={analysis.error}
          onRetry={analysis.reload}
          onReauth={analysis.expired ? signOut : undefined}
        />
      ) : null}

      {result ? (
        <Result result={result} stalled={stalled} lost={lost} />
      ) : (
        <p className="m-0 text-sm muted">
          No photo yet. A photo lets the automatic check see the waste and helps
          staff decide faster.
        </p>
      )}

      {canUpload ? (
        result ? (
          <details>
            <summary className="cursor-pointer text-sm font-bold">
              Replace the photo
            </summary>
            <div className="mt-3">
              <UploadForm
                trackingId={trackingId}
                token={token}
                cta="Upload new photo"
                onDone={() => {
                  analysis.reload()
                  onUploaded?.()
                }}
              />
            </div>
          </details>
        ) : (
          <UploadForm
            trackingId={trackingId}
            token={token}
            cta="Add photo"
            onDone={() => {
              analysis.reload()
              onUploaded?.()
            }}
          />
        )
      ) : null}
    </div>
  )
}

function Result({
  result,
  stalled,
  lost,
}: {
  result: WasteAIAnalysis
  stalled: boolean
  lost: boolean
}) {
  const unusable =
    result.ai_status === 'completed' && result.image_usable === false

  return (
    <div className="grid gap-4 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)]">
      {result.image_url ? (
        <BackendPhoto
          src={backendFileUrl(result.image_url)}
          alt="Your photo of the waste"
          className="photo-frame"
        />
      ) : null}

      <div className="grid content-start gap-3" aria-live="polite">
        <div>
          <AIStatusPill
            status={result.ai_status}
            usable={result.image_usable}
            lost={lost}
          />
        </div>

        {result.ai_status === 'pending' && lost ? (
          <Callout tone="info" title="The automatic check didn’t finish">
            Your photo is saved, and staff will still look at it when they
            review the complaint.
          </Callout>
        ) : result.ai_status === 'pending' ? (
          <p className="m-0 flex items-center gap-2 text-sm muted">
            <Spinner />
            {stalled
              ? 'Still checking. Refresh this page in a little while.'
              : 'Checking your photo — this usually takes under a minute.'}
          </p>
        ) : null}

        {result.ai_status === 'failed' ? (
          <Callout tone="info" title="The automatic check could not run">
            Your photo is saved. A staff member will look at it when they review
            the complaint.
          </Callout>
        ) : null}

        {unusable ? (
          <Callout tone="warn" title="We could not use this photo">
            {result.unusable_reason
              ? `${result.unusable_reason.trim().replace(/\.?$/, '.')} `
              : ''}
            Try a clearer, closer photo of the waste in daylight.
          </Callout>
        ) : null}

        {result.ai_status === 'completed' && !unusable ? (
          <>
            <dl className="m-0 grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="kicker">The check saw</dt>
                <dd className="m-0">
                  {aiWasteLabel(result.waste_type) ?? 'Not sure'}
                </dd>
              </div>
              <div>
                <dt className="kicker">Amount</dt>
                <dd className="m-0">
                  {aiSeverityLabel(result.severity) ?? 'Not sure'}
                </dd>
              </div>
            </dl>
            {result.disposal_guidance ? (
              <div className="ai-note">
                <span className="kicker">Suggested disposal</span>
                <p className="mt-1 mb-0">{result.disposal_guidance}</p>
                <p className="mt-1 mb-0 text-xs muted">
                  An automatic suggestion — staff review every complaint and may
                  follow up.
                </p>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  )
}

/** Owners and admins may attach or replace the photo; each upload re-runs the check. */
export function UploadForm({
  trackingId,
  token,
  cta,
  onDone,
}: {
  trackingId: string
  token: string
  cta: string
  onDone: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)

  return (
    <form
      className="grid gap-3"
      onSubmit={async (event) => {
        event.preventDefault()
        if (!file) {
          setError('Take or choose a photo first.')
          return
        }
        setBusy(true)
        setError(null)
        try {
          await uploadComplaintImage(trackingId, file, token)
          setFile(null)
          onDone()
        } catch (caught) {
          setExpired(isExpiredSession(caught))
          setError(caught instanceof Error ? caught.message : 'Upload failed.')
        } finally {
          setBusy(false)
        }
      }}
    >
      <PhotoInput
        id={`photo-${trackingId}`}
        file={file}
        onChange={(next) => {
          setFile(next)
          setError(null)
        }}
        disabled={busy}
        hint="Show the waste clearly · JPEG, PNG or WebP up to 8 MB"
        error={expired ? null : error}
      />
      {expired && error ? (
        <ErrorState title="Not uploaded" message={error} onReauth={signOut} />
      ) : null}
      <div>
        <button
          type="submit"
          className="btn btn-primary btn-sm"
          disabled={busy || !file}
        >
          {busy ? <Spinner /> : null}
          {busy ? 'Uploading…' : cta}
        </button>
      </div>
    </form>
  )
}
