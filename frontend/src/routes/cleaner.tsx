import { useEffect, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Callout, Field, StatusPill } from '#/components/ui'
import {
  getBackendImageUrl,
  listCleanerTasks,
  startCleanerTask,
  uploadCleanupProof,
  type CleanerTask,
  type ProofUploadResponse,
} from '#/lib/api'

export const Route = createFileRoute('/cleaner')({
  component: CleanerPortalPage,
})

function CleanerPortalPage() {
  const [tasks, setTasks] = useState<CleanerTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  // Upload proof state
  const [selectedFileMap, setSelectedFileMap] = useState<Record<number, File | null>>({})
  const [uploadingTaskId, setUploadingTaskId] = useState<number | null>(null)
  const [uploadResultMap, setUploadResultMap] = useState<Record<number, ProofUploadResponse | null>>({})

  const fetchTasks = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listCleanerTasks()
      setTasks(data)
    } catch (err: any) {
      setError(err?.message || 'Failed to load cleaner tasks. Make sure you are signed in as a cleaner.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTasks()
  }, [])

  const handleStart = async (taskId: number) => {
    setActionMessage(null)
    try {
      await startCleanerTask(taskId)
      setActionMessage(`Task #${taskId} marked as started (In Progress).`)
      await fetchTasks()
    } catch (err: any) {
      setError(err?.message || 'Failed to start task.')
    }
  }

  const handleFileChange = (taskId: number, file: File | null) => {
    setSelectedFileMap((prev) => ({ ...prev, [taskId]: file }))
  }

  const handleUploadProof = async (taskId: number) => {
    const file = selectedFileMap[taskId]
    if (!file) {
      setError('Please select an image file to upload as proof.')
      return
    }

    setUploadingTaskId(taskId)
    setError(null)
    setActionMessage(null)

    try {
      const formData = new FormData()
      formData.append('image', file)

      const result = await uploadCleanupProof(taskId, formData)
      setUploadResultMap((prev) => ({ ...prev, [taskId]: result }))
      setActionMessage(`Cleanup proof uploaded for Task #${taskId}! AI verification confidence: ${(result.ai_verification.confidence * 100).toFixed(0)}%`)
      await fetchTasks()
    } catch (err: any) {
      setError(err?.message || 'Failed to upload cleanup proof.')
    } finally {
      setUploadingTaskId(null)
    }
  }

  return (
    <main id="main" className="wrap page max-w-4xl">
      <p className="kicker">Field Operations</p>
      <h1 className="mt-1 text-2xl font-extrabold sm:text-3xl">Cleaner Task Portal</h1>
      <p className="mt-2 text-sm muted">
        View assigned cleanup tasks, start work, and upload completion proof images.
      </p>

      {actionMessage ? (
        <div className="mt-4">
          <Callout tone="ok" title="Action Completed">
            {actionMessage}
          </Callout>
        </div>
      ) : null}

      {error ? (
        <div className="mt-4">
          <Callout tone="danger" title="Error">
            {error}{' '}
            <Link to="/login" className="underline font-semibold">
              Sign in as Cleaner
            </Link>
          </Callout>
        </div>
      ) : null}

      <div className="mt-6 flex justify-between items-center">
        <h2 className="text-lg font-bold">Assigned Tasks ({tasks.length})</h2>
        <button type="button" className="btn btn-sm btn-quiet" onClick={fetchTasks}>
          Refresh Tasks
        </button>
      </div>

      {loading ? (
        <div className="mt-4 card card-pad text-center muted">Loading assigned tasks...</div>
      ) : tasks.length === 0 ? (
        <div className="mt-4 card card-pad text-center muted">
          No cleanup tasks currently assigned to your account.
        </div>
      ) : (
        <div className="mt-4 grid gap-4">
          {tasks.map((task) => {
            const proofResult = uploadResultMap[task.id]
            const selectedFile = selectedFileMap[task.id]

            return (
              <div key={task.id} className="card card-pad grid gap-3">
                <div className="flex flex-wrap items-start justify-between gap-2 border-b border-(--line) pb-3">
                  <div>
                    <span className="kicker">Task #{task.id} · Ref: {task.tracking_id}</span>
                    <h3 className="text-base font-extrabold mt-0.5">
                      Complaint #{task.complaint_id}
                    </h3>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="pill">Task: {task.status}</span>
                    <StatusPill status={task.complaint_status as any} />
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2 text-sm">
                  <div>
                    <span className="kicker">Description</span>
                    <p className="m-0 text-(--fg)">{task.complaint_text}</p>

                    <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="kicker">Waste Type</span>
                        <p className="m-0 font-semibold capitalize">{task.waste_type ?? 'N/A'}</p>
                      </div>
                      <div>
                        <span className="kicker">Severity</span>
                        <p className="m-0 font-semibold capitalize">{task.severity ?? 'Normal'}</p>
                      </div>
                    </div>

                    <div className="mt-2 text-xs muted">
                      <span className="kicker">Location</span>
                      <p className="m-0">
                        {task.location_type === 'gps'
                          ? `GPS (${task.latitude?.toFixed(4)}, ${task.longitude?.toFixed(4)})`
                          : task.manual_address ?? 'Not specified'}
                      </p>
                    </div>
                  </div>

                  <div>
                    {task.image_path ? (
                      <div>
                        <span className="kicker">Initial Waste Image</span>
                        <div className="mt-1 rounded overflow-hidden border border-(--line) max-w-xs">
                          <img
                            src={getBackendImageUrl(task.image_path) ?? undefined}
                            alt="Initial waste complaint"
                            className="w-full h-auto max-h-36 object-cover"
                          />
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>

                {/* Workflow Actions */}
                <div className="mt-2 pt-3 border-t border-(--line) flex flex-wrap items-center justify-between gap-3">
                  {task.status === 'assigned' ? (
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => handleStart(task.id)}
                    >
                      Start Task
                    </button>
                  ) : null}

                  {(task.status === 'in_progress' || task.status === 'assigned' || task.status === 'rework_required') ? (
                    <div className="flex-1 max-w-lg bg-(--surface-2) p-3 rounded-lg grid gap-2">
                      <Field label="Upload Completion Proof Image" htmlFor={`proof-${task.id}`}>
                        <input
                          id={`proof-${task.id}`}
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          className="input text-xs"
                          onChange={(e) => handleFileChange(task.id, e.target.files?.[0] ?? null)}
                        />
                      </Field>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={!selectedFile || uploadingTaskId === task.id}
                        onClick={() => handleUploadProof(task.id)}
                      >
                        {uploadingTaskId === task.id ? 'Uploading...' : 'Submit Cleanup Proof'}
                      </button>
                    </div>
                  ) : null}

                  {proofResult ? (
                    <div className="w-full bg-(--ok-surface) p-3 rounded-lg text-xs space-y-1">
                      <p className="font-bold text-(--ok-fg)">AI Cleanup Verification Result</p>
                      <p>Task status: {proofResult.task_status} | Complaint status: {proofResult.complaint_status}</p>
                      <p>
                        Usable: {proofResult.ai_verification.after_image_usable ? 'Yes' : 'No'} |
                        Clean: {proofResult.ai_verification.cleanup_appears_complete ? 'Yes' : 'No'} |
                        Confidence: {(proofResult.ai_verification.confidence * 100).toFixed(0)}%
                      </p>
                    </div>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </main>
  )
}
