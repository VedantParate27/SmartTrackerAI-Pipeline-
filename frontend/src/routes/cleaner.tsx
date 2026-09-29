import { Outlet, createFileRoute } from '@tanstack/react-router'
import AuthPanel from '#/components/AuthPanel'
import { Callout } from '#/components/ui'
import { signOut, useAuth } from '#/lib/auth'

export const Route = createFileRoute('/cleaner')({ component: CleanerLayout })

/** Mirrors get_current_cleaner_user, which also admits admins. */
const ALLOWED = ['cleaner', 'admin']

function CleanerLayout() {
  const { session, hydrated } = useAuth()
  const allowed = session !== null && ALLOWED.includes(session.role)

  if (!hydrated || !allowed) {
    return (
      <main id="main" className="wrap page max-w-2xl">
        <p className="kicker">Field work</p>
        <h1 className="mt-1 text-2xl font-extrabold sm:text-3xl">
          Cleanup tasks
        </h1>
        <div className="mt-5">
          <AuthPanel requireRole="cleaner" />
        </div>
        {session && !allowed ? (
          <div className="mt-4">
            <Callout tone="danger" title="Not a cleaner account">
              Cleanup tasks are only served to accounts with the cleaner role.
            </Callout>
          </div>
        ) : (
          <p className="mt-4 text-sm muted">
            Cleaner accounts cannot be self-registered — sign-up always creates
            a citizen account. An administrator has to set up your login.
          </p>
        )}
      </main>
    )
  }

  return (
    <main id="main" className="wrap page max-w-3xl">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="kicker">Field work</p>
          <h1 className="mt-1 text-2xl font-extrabold sm:text-3xl">
            Cleanup tasks
          </h1>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="muted">
            Backend role: <strong>{session.role}</strong>
          </span>
          <button type="button" className="btn btn-sm" onClick={signOut}>
            Sign out
          </button>
        </div>
      </div>
      <div className="mt-5">
        <Outlet />
      </div>
    </main>
  )
}
