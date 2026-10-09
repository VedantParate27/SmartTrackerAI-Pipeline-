import { useEffect, useState } from 'react'
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { clearAuthToken, getAuthUser, type AuthUser } from '#/lib/api'
import { resetStore } from '#/lib/store'
import ThemeToggle from './ThemeToggle'

interface NavLinkItem {
  to:
    | '/'
    | '/submit'
    | '/track'
    | '/guide'
    | '/admin'
    | '/admin/verification'
    | '/admin/knowledge'
    | '/cleaner'
    | '/login'
  label: string
  exact?: boolean
}

const CITIZEN_LINKS: readonly NavLinkItem[] = [
  { to: '/', label: 'Home', exact: true },
  { to: '/track', label: 'My Complaints / Track' },
  { to: '/submit', label: 'Submit Complaint' },
]

const ADMIN_LINKS: readonly NavLinkItem[] = [
  { to: '/admin', label: 'Admin Dashboard', exact: true },
  { to: '/admin', label: 'Complaint Queue', exact: true },
  { to: '/admin', label: 'Cleaner Management', exact: true },
  { to: '/admin/verification', label: 'Cleanup Verification' },
  { to: '/admin/knowledge', label: 'Knowledge/Analytics' },
]

const CLEANER_LINKS: readonly NavLinkItem[] = [
  { to: '/cleaner', label: 'Cleaner Dashboard', exact: true },
  { to: '/cleaner', label: 'My Tasks', exact: true },
]

const GUEST_LINKS: readonly NavLinkItem[] = [
  { to: '/', label: 'Home', exact: true },
  { to: '/track', label: 'Track status' },
  { to: '/guide', label: 'Document guide' },
  { to: '/login', label: 'Sign in' },
]

function getNavLinks(user: AuthUser | null): readonly NavLinkItem[] {
  if (!user) return GUEST_LINKS
  if (user.role === 'admin') return ADMIN_LINKS
  if (user.role === 'cleaner') return CLEANER_LINKS
  return CITIZEN_LINKS
}

export default function Header() {
  const [open, setOpen] = useState(false)
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const navigate = useNavigate()
  const routerState = useRouterState()

  useEffect(() => {
    setAuthUser(getAuthUser())
    const handleAuthChange = () => {
      setAuthUser(getAuthUser())
    }
    window.addEventListener('smarttracker:auth-change', handleAuthChange)
    window.addEventListener('storage', handleAuthChange)
    return () => {
      window.removeEventListener('smarttracker:auth-change', handleAuthChange)
      window.removeEventListener('storage', handleAuthChange)
    }
  }, [routerState.location.pathname])

  const handleLogout = () => {
    clearAuthToken()
    setAuthUser(null)
    resetStore()
    setOpen(false)
    navigate({ to: '/login' })
  }

  const links = getNavLinks(authUser)

  return (
    <header className="site-header">
      <div className="wrap flex items-center gap-3 py-2.5">
        <Link to="/" className="brand" onClick={() => setOpen(false)}>
          <span className="brand-mark" aria-hidden="true">
            ST
          </span>
          <span>
            SmartTracker<span className="text-(--accent)"> AI</span>
          </span>
        </Link>

        {/* Desktop navigation */}
        <nav
          aria-label="Main"
          className="ml-auto hidden items-center gap-0.5 md:flex"
        >
          {links.map((link, idx) => (
            <Link
              key={`${link.to}-${link.label}-${idx}`}
              to={link.to}
              className="nav-link"
              activeProps={{ className: 'nav-link is-active' }}
              activeOptions={{ exact: link.exact ?? link.to === '/' }}
            >
              {link.label}
            </Link>
          ))}
          {authUser ? (
            <button
              type="button"
              onClick={handleLogout}
              className="nav-link cursor-pointer text-red-500 hover:text-red-600 transition-colors"
            >
              Logout
            </button>
          ) : null}
        </nav>

        <div className="ml-auto flex items-center gap-1.5 md:ml-1">
          <ThemeToggle />
          <button
            type="button"
            className="btn btn-sm md:hidden"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((value) => !value)}
          >
            <span aria-hidden="true">{open ? '✕' : '☰'}</span>
            <span className="sr-only">
              {open ? 'Close navigation menu' : 'Open navigation menu'}
            </span>
          </button>
        </div>
      </div>

      {/* Mobile navigation */}
      {open ? (
        <nav
          id="mobile-nav"
          aria-label="Main"
          className="wrap border-t border-(--line) pb-3 pt-2 md:hidden"
        >
          <ul className="m-0 grid list-none gap-0.5 p-0">
            {links.map((link, idx) => (
              <li key={`${link.to}-${link.label}-${idx}`}>
                <Link
                  to={link.to}
                  className="nav-link"
                  activeProps={{ className: 'nav-link is-active' }}
                  activeOptions={{ exact: link.exact ?? link.to === '/' }}
                  onClick={() => setOpen(false)}
                >
                  {link.label}
                </Link>
              </li>
            ))}
            {authUser ? (
              <li>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="nav-link w-full text-left cursor-pointer text-red-500 hover:text-red-600 transition-colors"
                >
                  Logout
                </button>
              </li>
            ) : null}
          </ul>
        </nav>
      ) : null}
    </header>
  )
}
