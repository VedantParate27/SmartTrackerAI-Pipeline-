import { useEffect } from 'react'
import { HeadContent, Scripts, createRootRoute } from '@tanstack/react-router'
import Footer from '#/components/Footer'
import Header from '#/components/Header'
import { hydrateStore } from '#/lib/store'

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
          'Submit a grievance in plain language, track its status, and let administrators review AI classification, policy evidence and grounded draft responses.',
      },
    ],
    links: [{ rel: 'stylesheet', href: appCss }],
  }),
  shellComponent: RootDocument,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  // The store is seeded deterministically for SSR, then rehydrated in the
  // browser from localStorage so a refresh keeps submitted cases.
  useEffect(() => {
    void hydrateStore()
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
