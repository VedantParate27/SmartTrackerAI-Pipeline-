import { useEffect, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  Callout,
  ErrorState,
  LoadingState,
  ProofImage,
  ProofStatusPill,
  SectionCard,
  Spinner,
  TaskStatusPill,
  WastePill,
} from '#/components/ui'
import {
  backendFileUrl,
  getCleanerTask,
  startCleanerTask,
  uploadProof,
} from '#/lib/api'
import type { CleanerTask } from '#/lib/api'
import { isExpiredSession, signOut, useAuth } from '#/lib/auth'
import {
  formatCoordinates,
  mapsUrl,
  severityLabel,
} from '#/lib/complaint-format'
import { formatDateTime } from '#/lib/format'
import { useApi } from '#/lib/use-api'

export const Route = createFileRoute('/cleaner/tasks/$taskId')({
  component: TaskPage,
})

/** The backend sets no size limit; this keeps an upload inside its 30 s window. */
const MAX_BYTES = 15 * 1024 * 1024

function TaskPage() {
  const { taskId } = Route.useParams()
  const { session } = useAuth()
  const token = session?.accessToken
  const task = useApi(
    token ? (signal) => getCleanerTask(taskId, token, signal) : null,
    [taskId, token],
  )

  if (!token) return null

  if (task.loading && !task.data) {
    return <LoadingState label="Loading the task…" />
  }

  if (task.error || !task.data) {
    return (
      <div className="grid gap-4">
        <ErrorState
          title="Task could not be loaded"
          message={task.error ?? 'Task not found.'}
          onRetry={task.reload}
          onReauth={task.expired ? signOut : undefined}
        />
        <Link to="/cleaner" className="text-sm no-underline">
          ← All tasks
        </Link>
      </div>
    )
  }

  return (
    <TaskDetail
      task={task.data}
      token={token}
      onChange={(next) => (next ? task.setData(next) : task.reload())}
      busy={task.loading}
      onRefresh={task.reload}
    />
  )
}

function TaskDetail({
  task,
  token,
  onChange,
  busy,
  onRefresh,
}: {
  task: CleanerTask
  token: string
  onChange: (next?: CleanerTask) => void
  busy: boolean
  onRefresh: () => void
}) {
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const map = mapsUrl(task.latitude, task.longitude)
  const coordinates = formatCoordinates(task.latitude, task.longitude)
  const lastProof = task.proofs.at(-1)
  const canUpload = ['assigned', 'in_progress', 'rejected'].includes(
    task.status,
  )

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to="/cleaner" className="text-sm no-underline">
          ← All tasks
        </Link>
        <button
          type="button"
          className="btn btn-sm"
          disabled={busy}
          onClick={onRefresh}
        >
          {busy ? <Spinner /> : null}
          {busy ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <header className="card card-pad">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <span className="kicker">Task</span>
            <h2 className="mono mt-0.5 text-lg font-extrabold">
              {task.task_id}
            </h2>
            <p className="m-0 mt-0.5 text-xs muted">
              Complaint <span className="mono">{task.tracking_id}</span> ·
              assigned {formatDateTime(task.assigned_at)}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <TaskStatusPill status={task.status} />
            <WastePill wasteType={task.waste_type} />
            {task.quantity_severity ? (
              <span className="pill">
                {severityLabel(task.quantity_severity)}
              </span>
            ) : null}
          </div>
        </div>

        <div className="mt-4">
          <span className="kicker">Where</span>
          <p className="m-0 mt-1 text-sm">
            {task.address_text ?? (coordinates ? null : 'No location given')}
          </p>
          {coordinates ? (
            <p className="m-0 text-xs muted">
              {coordinates}
              {map ? (
                <>
                  {' · '}
                  <a href={map} target="_blank" rel="noreferrer">
                    Open map
                  </a>
                </>
              ) : null}
            </p>
          ) : null}
        </div>
      </header>

      {task.status === 'rejected' && lastProof?.rejection_reason ? (
        <Callout tone="danger" title="Your last photo was rejected">
          {lastProof.rejection_reason} — fix it and upload a new photo.
        </Callout>
      ) : null}

      <SectionCard title="What to clean">
        <p className="original-text m-0">{task.complaint_text}</p>
        {task.notes ? (
          <div className="mt-3">
            <span className="kicker">Instructions from the admin</span>
            <p className="mt-1 mb-0 text-sm">{task.notes}</p>
          </div>
        ) : null}
        {task.recommended_action ? (
          <div className="mt-3">
            <span className="kicker">Recommended action</span>
            <div className="draft-box mt-1">{task.recommended_action}</div>
          </div>
        ) : null}
      </SectionCard>

      {task.status === 'assigned' ? (
        <SectionCard title="1. Start the cleanup">
          {startError ? (
            <div className="mb-3">
              <ErrorState title="Not started" message={startError} />
            </div>
          ) : null}
          <p className="mt-0 mb-3 text-sm muted">
            Tap this when you arrive, so the case records when work began.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            disabled={starting}
            onClick={async () => {
              setStarting(true)
              setStartError(null)
              try {
                onChange(await startCleanerTask(task.task_id, token))
              } catch (caught) {
                setStartError(
                  caught instanceof Error ? caught.message : 'Start failed.',
                )
              } finally {
                setStarting(false)
              }
            }}
          >
            {starting ? <Spinner /> : null}
            {starting ? 'Starting…' : 'Start cleanup'}
          </button>
        </SectionCard>
      ) : null}

      {canUpload ? (
        <SectionCard
          title={
            task.status === 'assigned' ? '2. Upload proof' : 'Upload proof'
          }
        >
          <ProofUpload taskId={task.task_id} token={token} onDone={onChange} />
        </SectionCard>
      ) : task.status === 'proof_submitted' ? (
        <Callout tone="info" title="Photo sent">
          An admin will check it. If it is rejected you will see why here.
        </Callout>
      ) : task.status === 'verified' ? (
        <Callout tone="ok" title="Task complete">
          Your proof was verified
          {task.completed_at ? ` on ${formatDateTime(task.completed_at)}` : ''}.
        </Callout>
      ) : null}

      <SectionCard title="Your photos" meta={`${task.proofs.length}`}>
        {task.proofs.length === 0 ? (
          <p className="m-0 text-sm muted">No photos uploaded yet.</p>
        ) : (
          <ul className="proof-grid list-none p-0">
            {[...task.proofs].reverse().map((proof) => (
              <li key={proof.id} className="proof-card">
                <ProofImage
                  src={backendFileUrl(proof.image_url)}
                  alt={`Proof uploaded ${formatDateTime(proof.uploaded_at)}`}
                />
                <div className="proof-body grid gap-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <ProofStatusPill status={proof.verification_status} />
                    <span className="text-xs muted">
                      {formatDateTime(proof.uploaded_at)}
                    </span>
                  </div>
                  {proof.rejection_reason ? (
                    <p className="m-0 text-xs">
                      <strong>Reason:</strong> {proof.rejection_reason}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  )
}

function ProofUpload({
  taskId,
  token,
  onDone,
}: {
  taskId: string
  token: string
  onDone: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)

  // Release the object URL whenever the preview changes or the form goes away.
  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview)
    }
  }, [preview])

  function choose(next: File | null) {
    setError(null)
    if (!next) {
      setFile(null)
      setPreview(null)
      return
    }
    if (!next.type.startsWith('image/')) {
      setFileError('Choose a photo (JPEG, PNG or similar).')
      return
    }
    if (next.size > MAX_BYTES) {
      setFileError('That photo is over 15 MB. Take a smaller one.')
      return
    }
    setFileError(null)
    setFile(next)
    setPreview(URL.createObjectURL(next))
  }

  return (
    <form
      className="grid gap-3"
      onSubmit={async (event) => {
        event.preventDefault()
        if (!file) {
          setFileError('Take or choose a photo of the cleaned spot first.')
          return
        }
        setUploading(true)
        setError(null)
        try {
          await uploadProof(taskId, file, token)
          choose(null)
          onDone()
        } catch (caught) {
          setExpired(isExpiredSession(caught))
          setError(caught instanceof Error ? caught.message : 'Upload failed.')
        } finally {
          setUploading(false)
        }
      }}
    >
      {error ? (
        <ErrorState
          title="Photo was not uploaded"
          message={error}
          onReauth={expired ? signOut : undefined}
        />
      ) : null}

      <label className="file-drop relative">
        <input
          type="file"
          accept="image/*"
          capture="environment"
          disabled={uploading}
          onChange={(event) => choose(event.target.files?.[0] ?? null)}
        />
        {preview ? (
          <img className="file-preview" src={preview} alt="Selected proof" />
        ) : (
          <span aria-hidden="true" className="text-2xl">
            ⬆
          </span>
        )}
        <span className="font-bold text-(--fg)">
          {file ? file.name : 'Take or choose a photo'}
        </span>
        <span>Show the spot after cleaning.</span>
      </label>
      {fileError ? (
        <p className="field-error m-0">
          <span aria-hidden="true">!</span>
          <span>{fileError}</span>
        </p>
      ) : null}

      <div>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={uploading || !file}
        >
          {uploading ? <Spinner /> : null}
          {uploading ? 'Uploading…' : 'Send proof'}
        </button>
      </div>
    </form>
  )
}
