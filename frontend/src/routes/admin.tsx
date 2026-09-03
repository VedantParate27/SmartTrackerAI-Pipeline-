import { Outlet, createFileRoute } from '@tanstack/react-router'
import AuthPanel from '#/components/AuthPanel'
import { Callout } from '#/components/ui'
import { signOut, useAuth } from '#/lib/auth'

export const Route = createFileRoute('/admin')({ component: AdminLayout })

function AdminLayout() {
  const { session, hydrated } = useAuth()

  if (!hydrated || !session || session.role !== 'admin') {
    return (
      <main id="main" className="wrap page max-w-2xl">
        <p className="kicker">Administration</p>
        <h1 className="mt-1 text-2xl font-extrabold sm:text-3xl">
          Review workspace
        </h1>
        <div className="mt-5">
          <AuthPanel adminOnly />
        </div>
        {session && session.role !== 'admin' ? (
          <div className="mt-4">
            <Callout tone="danger" title="Backend access denied">
              Frontend role switching has been removed. Sign in with a real
              backend admin account to access{' '}
              <span className="mono">/admin</span> endpoints.
            </Callout>
          </div>
        ) : null}
      </main>
    )
  }

  return (
    <main id="main" className="wrap page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="kicker">Administration</p>
          <h1 className="mt-1 text-2xl font-extrabold sm:text-3xl">
            Review workspace
          </h1>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="muted">
            Backend role: <strong>admin</strong>
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
