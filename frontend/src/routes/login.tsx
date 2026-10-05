import { useState } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Callout, Field } from '#/components/ui'
import { getAuthUser, login } from '#/lib/api'

export const Route = createFileRoute('/login')({
  component: LoginPage,
})

function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const currentUser = getAuthUser()

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) {
      setError('Please enter both email and password.')
      return
    }

    setLoading(true)
    setError(null)

    try {
      await login({ email, password })
      const user = getAuthUser()
      if (user?.role === 'admin') {
        navigate({ to: '/admin' })
      } else if (user?.role === 'cleaner') {
        navigate({ to: '/cleaner' as any })
      } else {
        navigate({ to: '/submit' })
      }
    } catch (err: any) {
      setError(err?.message || 'Login failed. Please check credentials.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main id="main" className="wrap page max-w-md">
      <p className="kicker">Authentication</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">Sign in</h1>
      <p className="mt-2 text-sm muted">
        Sign in to access your role workspace using real backend JWT authentication.
      </p>

      {currentUser ? (
        <div className="mt-4">
          <Callout tone="info" title="Already Signed In">
            Currently authenticated as User ID <strong>#{currentUser.id}</strong> (Role: <strong>{currentUser.role}</strong>).
          </Callout>
        </div>
      ) : null}

      <form className="mt-6 grid gap-4 card card-pad" onSubmit={handleLogin}>
        {error ? (
          <Callout tone="danger" title="Authentication Error">
            {error}
          </Callout>
        ) : null}

        <Field label="Email Address" htmlFor="login-email">
          <input
            id="login-email"
            type="email"
            className="input"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="user@example.com"
          />
        </Field>

        <Field label="Password" htmlFor="login-password">
          <input
            id="login-password"
            type="password"
            className="input"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
        </Field>

        <button
          type="submit"
          className="btn btn-primary mt-2 w-full"
          disabled={loading}
        >
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>

      <div className="mt-6 card card-pad text-xs muted space-y-1">
        <p className="font-bold text-sm text-(--fg)">Demo Accounts</p>
        <p><strong>Admin:</strong> admin@smarttracker.in / admin12345</p>
        <p><strong>Cleaner:</strong> phase3cleaner@example.com / cleaner123</p>
        <p><strong>Citizen:</strong> phase3test@example.com / testpass123</p>
      </div>
    </main>
  )
}
