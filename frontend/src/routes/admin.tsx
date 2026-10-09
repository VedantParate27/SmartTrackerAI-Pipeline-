import { Link, Outlet, createFileRoute } from '@tanstack/react-router'
import { resetStore } from '#/lib/store'
import { getAuthUser } from '#/lib/api'

export const Route = createFileRoute('/admin')({ component: AdminLayout })

function AdminLayout() {
  const authUser = getAuthUser()

  return (
    <main id="main" className="wrap page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="kicker">Administration</p>
          <h1 className="mt-1 text-2xl font-extrabold sm:text-3xl">
            Review workspace
          </h1>
        </div>

        <div className="flex w-full items-center gap-2 sm:w-auto">
          {authUser ? (
            <span className="text-xs muted mono">
              Admin #{authUser.id}
            </span>
          ) : null}
          <button
            type="button"
            className="btn btn-sm shrink-0"
            onClick={() => {
              if (
                window.confirm(
                  'Reset the demo back to the seeded cases and policies? Cases you submitted in this browser will be removed.',
                )
              ) {
                resetStore()
              }
            }}
          >
            Reset demo data
          </button>
        </div>
      </div>

      <nav
        aria-label="Administration sections"
        className="mt-4 flex gap-1 overflow-x-auto pb-1"
      >
        <Link
          to="/admin"
          activeOptions={{ exact: true }}
          className="nav-link shrink-0"
          activeProps={{ className: 'nav-link is-active shrink-0' }}
        >
          Case queue
        </Link>
        <Link
          to="/admin/verification"
          className="nav-link shrink-0"
          activeProps={{ className: 'nav-link is-active shrink-0' }}
        >
          Cleanup verification queue
        </Link>
        <Link
          to="/admin/knowledge"
          className="nav-link shrink-0"
          activeProps={{ className: 'nav-link is-active shrink-0' }}
        >
          Policy knowledge base
        </Link>
      </nav>

      <div className="mt-4">
        <Outlet />
      </div>
    </main>
  )
}
