import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'
import ThemeToggle from './ThemeToggle'
import { checkHealth } from '#/lib/api'

const LINKS = [
  { to: '/', label: 'Home' },
  { to: '/submit', label: 'Submit grievance' },
  { to: '/track', label: 'Track status' },
  { to: '/admin', label: 'Admin' },
] as const

/** Shield + check: a grievance carried through to a verified resolution. */
function BrandMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2.4 4.4 5.4v6.2c0 4.6 3.1 8.6 7.6 10 4.5-1.4 7.6-5.4 7.6-10V5.4L12 2.4Z"
        fill="currentColor"
        opacity=".22"
      />
      <path
        d="M12 2.4 4.4 5.4v6.2c0 4.6 3.1 8.6 7.6 10 4.5-1.4 7.6-5.4 7.6-10V5.4L12 2.4Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="m8.5 12.1 2.4 2.4 4.6-4.8"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/**
 * Backend reachability, polled once on mount. It is the fastest answer to
 * "why is every screen empty?" — an unreachable API is visible before the user
 * opens a form and waits for a request to time out.
 */
function ConnectionDot() {
  const [state, setState] = useState<'checking' | 'online' | 'offline'>(
    'checking',
  )

  useEffect(() => {
    const controller = new AbortController()
    checkHealth(controller.signal)
      .then(() => !controller.signal.aborted && setState('online'))
      .catch(() => !controller.signal.aborted && setState('offline'))
    return () => controller.abort()
  }, [])

  const label =
    state === 'online' ? 'API' : state === 'offline' ? 'API down' : 'API…'

  return (
    <span
      className="conn-dot"
      data-state={state}
      aria-live="polite"
      title={
        state === 'online'
          ? 'FastAPI is reachable'
          : state === 'offline'
            ? 'FastAPI is unreachable — start the backend on port 8000'
            : 'Checking the backend…'
      }
    >
      <span className="hidden sm:inline">{label}</span>
      <span className="sr-only sm:hidden">
        {state === 'online'
          ? 'Backend reachable'
          : state === 'offline'
            ? 'Backend unreachable'
            : 'Checking backend'}
      </span>
    </span>
  )
}

export default function Header() {
  const [open, setOpen] = useState(false)

  return (
    <header className="site-header">
      <div className="wrap flex items-center gap-3 py-2.5">
        <Link to="/" className="brand" onClick={() => setOpen(false)}>
          <span className="brand-mark">
            <BrandMark />
          </span>
          <span>
            SmartTracker<span className="text-(--accent)"> AI</span>
          </span>
        </Link>

        <nav
          aria-label="Main"
          className="ml-auto hidden items-center gap-0.5 md:flex"
        >
          {LINKS.map((link) => (
            <Link
              key={link.to}
              to={link.to}
              className="nav-link"
              activeProps={{ className: 'nav-link is-active' }}
              activeOptions={{ exact: link.to === '/' }}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1.5 md:ml-3">
          <ConnectionDot />
          <ThemeToggle />
          <button
            type="button"
            className="btn btn-sm btn-icon md:hidden"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((value) => !value)}
          >
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              {open ? (
                <path d="M6 6l12 12M18 6L6 18" />
              ) : (
                <path d="M4 7h16M4 12h16M4 17h16" />
              )}
            </svg>
            <span className="sr-only">
              {open ? 'Close navigation menu' : 'Open navigation menu'}
            </span>
          </button>
        </div>
      </div>

      <nav
        id="mobile-nav"
        aria-label="Main"
        hidden={!open}
        className="wrap border-t border-(--glass-line) pt-2 pb-3 md:hidden"
      >
        <ul className="m-0 grid list-none gap-0.5 p-0">
          {LINKS.map((link) => (
            <li key={link.to}>
              <Link
                to={link.to}
                className="nav-link"
                activeProps={{ className: 'nav-link is-active' }}
                activeOptions={{ exact: link.to === '/' }}
                onClick={() => setOpen(false)}
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}
