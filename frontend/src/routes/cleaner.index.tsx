import { useMemo } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  Callout,
  EmptyState,
  ErrorState,
  LoadingState,
  SectionCard,
  Spinner,
  TaskStatusPill,
  WastePill,
} from '#/components/ui'
import { getCleanerTasks } from '#/lib/api'
import type { CleanerTask } from '#/lib/api'
import { signOut, useAuth } from '#/lib/auth'
import { formatCoordinates, severityLabel } from '#/lib/complaint-format'
import { formatAge } from '#/lib/format'
import { useApi } from '#/lib/use-api'

export const Route = createFileRoute('/cleaner/')({ component: TaskListPage })

const GROUPS: Array<{ title: string; statuses: string[]; empty: string }> = [
  {
    title: 'To do',
    statuses: ['assigned', 'in_progress', 'rejected'],
    empty: 'Nothing waiting for you.',
  },
  {
    title: 'Waiting for a check',
    statuses: ['proof_submitted'],
    empty: 'No photos awaiting review.',
  },
  { title: 'Done', statuses: ['verified'], empty: 'No finished tasks yet.' },
]

function TaskListPage() {
  const { session } = useAuth()
  const token = session?.accessToken
  const tasks = useApi(
    token ? (signal) => getCleanerTasks(token, signal) : null,
    [token],
  )

  const grouped = useMemo(
    () =>
      GROUPS.map((group) => ({
        ...group,
        tasks: (tasks.data ?? []).filter((task) =>
          group.statuses.includes(task.status),
        ),
      })),
    [tasks.data],
  )

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {session?.role === 'admin' ? (
          <p className="m-0 text-sm muted">
            Signed in as an admin, so every cleaner's tasks are listed.
          </p>
        ) : (
          <p className="m-0 text-sm muted">Tasks assigned to you.</p>
        )}
        <button
          type="button"
          className="btn btn-sm"
          disabled={tasks.loading}
          onClick={tasks.reload}
        >
          {tasks.loading ? <Spinner /> : null}
          {tasks.loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {tasks.error ? (
        <ErrorState
          title="Tasks could not be loaded"
          message={tasks.error}
          onRetry={tasks.reload}
          onReauth={tasks.expired ? signOut : undefined}
        />
      ) : tasks.loading && !tasks.data ? (
        <LoadingState label="Loading your tasks…" />
      ) : tasks.data && tasks.data.length === 0 ? (
        <Callout tone="info" title="No tasks yet">
          When an admin dispatches a complaint to you it appears here.
        </Callout>
      ) : (
        grouped.map((group) => (
          <SectionCard
            key={group.title}
            title={group.title}
            meta={`${group.tasks.length}`}
            bodyClassName="divide-rows"
          >
            {group.tasks.length === 0 ? (
              <EmptyState>{group.empty}</EmptyState>
            ) : (
              group.tasks.map((task) => (
                <TaskRow key={task.task_id} task={task} />
              ))
            )}
          </SectionCard>
        ))
      )}
    </div>
  )
}

function TaskRow({ task }: { task: CleanerTask }) {
  const lastProof = task.proofs.at(-1)
  return (
    <Link
      to="/cleaner/tasks/$taskId"
      params={{ taskId: task.task_id }}
      className="block px-4 py-3 text-inherit no-underline hover:bg-(--surface-2)"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="mono font-bold">{task.task_id}</span>
        <TaskStatusPill status={task.status} />
      </div>
      <p className="mt-1 mb-0 truncate text-sm">{task.complaint_text}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs muted">
        <WastePill wasteType={task.waste_type} />
        {task.quantity_severity ? (
          <span>{severityLabel(task.quantity_severity)}</span>
        ) : null}
        <span>
          ·{' '}
          {task.address_text ??
            formatCoordinates(task.latitude, task.longitude) ??
            'No location given'}
        </span>
        <span>
          · assigned {formatAge(task.assigned_at, new Date().toISOString())} ago
        </span>
      </div>
      {task.status === 'rejected' && lastProof?.rejection_reason ? (
        <p className="mt-1.5 mb-0 text-xs text-(--danger)">
          Photo rejected: {lastProof.rejection_reason}
        </p>
      ) : null}
    </Link>
  )
}
