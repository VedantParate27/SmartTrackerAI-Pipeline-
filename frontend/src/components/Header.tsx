import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import ThemeToggle from './ThemeToggle'

const LINKS = [
  { to: '/', label: 'Home' },
  { to: '/submit', label: 'Submit grievance' },
  { to: '/track', label: 'Track status' },
  { to: '/guide', label: 'Document guide' },
  { to: '/admin', label: 'Admin' },
] as const

export default function Header() {
  const [open, setOpen] = useState(false)

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
      ) : null}
    </header>
  )
}
