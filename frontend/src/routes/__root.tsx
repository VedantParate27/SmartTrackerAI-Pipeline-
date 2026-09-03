import { useEffect } from 'react'
import {
  HeadContent,
  Link,
  Scripts,
  createRootRoute,
} from '@tanstack/react-router'
import Footer from '#/components/Footer'
import Header from '#/components/Header'
import { hydrateAuth } from '#/lib/auth'

import appCss from '#/styles.css?url'

const THEME_INIT_SCRIPT = `(function(){try{var stored=window.localStorage.getItem('theme');var mode=(stored==='light'||stored==='dark'||stored==='auto')?stored:'auto';var prefersDark=window.matchMedia('(prefers-color-scheme: dark)').matches;var resolved=mode==='auto'?(prefersDark?'dark':'light'):mode;var root=document.documentElement;root.classList.remove('light','dark');root.classList.add(resolved);if(mode==='auto'){root.removeAttribute('data-theme')}else{root.setAttribute('data-theme',mode)}root.style.colorScheme=resolved;}catch(e){}})();`

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: 'SmartTracker AI — Grievance Routing & Resolution' },
      {
        name: 'description',
        content:
          'Submit and track grievances through the SmartTracker FastAPI contract, with optional AI details shown only when the backend returns them.',
      },
    ],
    links: [{ rel: 'stylesheet', href: appCss }],
  }),
  shellComponent: RootDocument,
  notFoundComponent: NotFound,
})

function NotFound() {
  return (
    <main id="main" className="wrap page max-w-2xl">
      <p className="kicker">404</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
        That page does not exist
      </h1>
      <p className="mt-2 text-sm muted">
        The link may be out of date. Everything the app can do starts from one
        of these.
      </p>
      <div className="mt-5 flex flex-col gap-2 sm:flex-row">
        <Link to="/" className="btn btn-primary btn-block sm:w-auto">
          Home
        </Link>
        <Link to="/submit" className="btn btn-block sm:w-auto">
          Submit a grievance
        </Link>
        <Link to="/track" className="btn btn-block sm:w-auto">
          Track a case
        </Link>
      </div>
    </main>
  )
}

function RootDocument({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    hydrateAuth()
  }, [])

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <HeadContent />
      </head>
      <body className="flex min-h-screen flex-col font-sans antialiased">
        <a className="skip-link" href="#main">
          Skip to main content
        </a>
        <Header />
        {children}
        <Footer />
        <Scripts />
      </body>
    </html>
  )
}
