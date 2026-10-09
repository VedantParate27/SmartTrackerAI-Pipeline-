import { useEffect, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Callout, StatusPill } from '#/components/ui'
import {
  getBackendImageUrl,
  listCleanupTasks,
  verifyCleanupTask,
  type AdminCleanupTask,
} from '#/lib/api'

export const Route = createFileRoute('/admin/verification')({
  component: AdminVerificationPage,
})

function AdminVerificationPage() {
  const [tasks, setTasks] = useState<AdminCleanupTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [submittingTaskId, setSubmittingTaskId] = useState<number | null>(null)
  const [notesMap, setNotesMap] = useState<Record<number, string>>({})

  const fetchVerificationTasks = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listCleanupTasks()
      const awaitingVerification = data.filter(
        (task) => task.status === 'verification',
      )
      setTasks(awaitingVerification)
    } catch (err: any) {
      setError(
        err?.message ||
          'Failed to load verification tasks. Ensure you are signed in as an admin.',
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchVerificationTasks()
  }, [])

  const handleVerify = async (taskId: number, decision: 'approve' | 'reject') => {
    setSubmittingTaskId(taskId)
    setError(null)
    setActionMessage(null)

    const notes = notesMap[taskId]?.trim() || null

    try {
      await verifyCleanupTask(taskId, { decision, notes })
      setActionMessage(
        `Verification decision '${decision}' recorded for Task #${taskId}. Complaint updated.`
      )
      await fetchVerificationTasks()
    } catch (err: any) {
      setError(err?.message || 'Failed to record verification decision.')
    } finally {
      setSubmittingTaskId(null)
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-bold">Cleanup Verification Queue</h2>
          <p className="text-sm muted m-0">
            Inspect uploaded cleanup proof photos against initial reports and verify work completion.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-sm btn-quiet"
          onClick={fetchVerificationTasks}
        >
          Refresh Queue
        </button>
      </div>

      {actionMessage ? (
        <Callout tone="ok" title="Decision Recorded">
          {actionMessage}
        </Callout>
      ) : null}

      {error ? (
        <Callout tone="danger" title="Error">
          {error}{' '}
          <Link to="/login" className="underline font-semibold">
            Sign in as Admin
          </Link>
        </Callout>
      ) : null}

      {loading ? (
        <div className="card card-pad text-center muted">Loading verification tasks...</div>
      ) : tasks.length === 0 ? (
        <div className="card card-pad text-center muted">
          No cleanup tasks currently awaiting verification.
        </div>
      ) : (
        <div className="grid gap-4">
          {tasks.map((task) => (
            <div key={task.id} className="card card-pad grid gap-4">
              <div className="flex flex-wrap items-start justify-between gap-2 border-b border-(--line) pb-3">
                <div>
                  <span className="kicker">Task #{task.id} · Ref: {task.tracking_id}</span>
                  <h3 className="text-base font-extrabold mt-0.5">
                    Complaint #{task.complaint_id} — Cleaner: {task.cleaner_name} ({task.cleaner_email})
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  <span className="pill">Task: {task.status}</span>
                  <StatusPill status={task.complaint_status as any} />
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2 text-sm">
                <div>
                  <span className="kicker">Complaint Text</span>
                  <p className="m-0 text-(--fg) font-medium">{task.complaint_text}</p>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs bg-(--surface-2) p-2.5 rounded">
                    <div>
                      <span className="kicker">Waste Type</span>
                      <p className="m-0 font-bold capitalize">{task.waste_type ?? 'N/A'}</p>
                    </div>
                    <div>
                      <span className="kicker">Severity</span>
                      <p className="m-0 font-bold capitalize">{task.severity ?? 'Normal'}</p>
                    </div>
                  </div>

                  {task.verification_status ? (
                    <div className="mt-3 text-xs bg-(--surface-2) p-2.5 rounded space-y-1">
                      <span className="kicker">AI Verification Assessment</span>
                      <p className="m-0">
                        Status: <strong>{task.verification_status}</strong> | Confidence:{' '}
                        <strong>{((task.verification_confidence ?? 0) * 100).toFixed(0)}%</strong>
                      </p>
                      {task.verification_reason ? (
                        <p className="m-0 italic subtle">{task.verification_reason}</p>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                {/* Proof Image Comparison */}
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="kicker block text-xs">Before Image</span>
                    {task.image_path ? (
                      <div className="mt-1 rounded overflow-hidden border border-(--line)">
                        <img
                          src={getBackendImageUrl(task.image_path) ?? undefined}
                          alt="Before cleanup"
                          className="w-full h-auto max-h-40 object-cover"
                        />
                      </div>
                    ) : (
                      <p className="text-xs muted italic mt-2">No before image</p>
                    )}
                  </div>

                  <div>
                    <span className="kicker block text-xs">Proof Image (After)</span>
                    {task.proof_image_path ? (
                      <div className="mt-1 rounded overflow-hidden border border-(--line)">
                        <img
                          src={getBackendImageUrl(task.proof_image_path) ?? undefined}
                          alt="Cleanup proof after"
                          className="w-full h-auto max-h-40 object-cover"
                        />
                      </div>
                    ) : (
                      <p className="text-xs muted italic mt-2">No proof uploaded</p>
                    )}
                  </div>
                </div>
              </div>

              {/* Admin Verification Actions */}
              <div className="pt-3 border-t border-(--line) flex flex-wrap items-center justify-between gap-3">
                <div className="flex-1 min-w-[240px]">
                  <input
                    type="text"
                    className="input text-xs"
                    placeholder="Verification notes / feedback (optional)..."
                    value={notesMap[task.id] ?? ''}
                    onChange={(e) =>
                      setNotesMap((prev) => ({ ...prev, [task.id]: e.target.value }))
                    }
                  />
                </div>

                <div className="flex gap-2">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={submittingTaskId === task.id}
                    onClick={() => handleVerify(task.id, 'approve')}
                  >
                    Approve Cleanup
                  </button>
                  <button
                    type="button"
                    className="btn btn-quiet btn-sm text-(--warn)"
                    disabled={submittingTaskId === task.id}
                    onClick={() => handleVerify(task.id, 'reject')}
                  >
                    Reject (Require Rework)
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
