import { useState } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Callout, Field } from '#/components/ui'
import { getAuthUser, login, register } from '#/lib/api'

export const Route = createFileRoute('/login')({
  component: LoginPage,
})

function LoginPage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const currentUser = getAuthUser()

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    const cleanEmail = email.trim().toLowerCase()

    if (!cleanEmail || !password) {
      setError('Please enter both email and password.')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      await login({ email: cleanEmail, password })
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

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    const cleanName = name.trim()
    const cleanEmail = email.trim().toLowerCase()

    if (!cleanName || cleanName.length < 2) {
      setError('Full name must be at least 2 characters.')
      return
    }

    if (!cleanEmail || !cleanEmail.includes('@')) {
      setError('Please enter a valid email address.')
      return
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters long.')
      return
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const res = await register({
        name: cleanName,
        email: cleanEmail,
        password,
      })
      setSuccess(
        `Account registered successfully for ${res.name}! You can now sign in with your password.`,
      )
      setPassword('')
      setConfirmPassword('')
      setName('')
      setMode('login')
    } catch (err: any) {
      setError(
        err?.message ||
          'Registration failed. Please check your details and try again.',
      )
    } finally {
      setLoading(false)
    }
  }

  const switchMode = (newMode: 'login' | 'register') => {
    setMode(newMode)
    setError(null)
    setSuccess(null)
  }

  return (
    <main id="main" className="wrap page max-w-md">
      <p className="kicker">Authentication</p>
      <h1 className="mt-2 text-2xl font-extrabold sm:text-3xl">
        {mode === 'login' ? 'Sign in' : 'Register as Citizen'}
      </h1>
      <p className="mt-2 text-sm muted">
        {mode === 'login'
          ? 'Sign in to access your role workspace using real backend JWT authentication.'
          : 'Create a citizen account to submit and track your civic grievances.'}
      </p>

      {currentUser ? (
        <div className="mt-4">
          <Callout tone="info" title="Already Signed In">
            Currently authenticated as User ID <strong>#{currentUser.id}</strong> (Role: <strong>{currentUser.role}</strong>).
          </Callout>
        </div>
      ) : null}

      <div className="mt-6 flex border-b border-(--line) gap-4">
        <button
          type="button"
          onClick={() => switchMode('login')}
          className={`pb-2 text-sm font-semibold border-b-2 transition-colors cursor-pointer ${
            mode === 'login'
              ? 'border-(--accent) text-(--fg)'
              : 'border-transparent muted hover:text-(--fg)'
          }`}
        >
          Sign in
        </button>
        <button
          type="button"
          onClick={() => switchMode('register')}
          className={`pb-2 text-sm font-semibold border-b-2 transition-colors cursor-pointer ${
            mode === 'register'
              ? 'border-(--accent) text-(--fg)'
              : 'border-transparent muted hover:text-(--fg)'
          }`}
        >
          Register as Citizen
        </button>
      </div>

      <div className="mt-4">
        {error ? (
          <div className="mb-4">
            <Callout
              tone="danger"
              title={mode === 'login' ? 'Authentication Error' : 'Registration Error'}
            >
              {error}
            </Callout>
          </div>
        ) : null}

        {success ? (
          <div className="mb-4">
            <Callout tone="ok" title="Registration Successful">
              {success}
            </Callout>
          </div>
        ) : null}

        {mode === 'login' ? (
          <form className="grid gap-4 card card-pad" onSubmit={handleLogin}>
            <Field label="Email Address" htmlFor="login-email" required>
              <input
                id="login-email"
                type="email"
                className="input"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
                autoComplete="email"
              />
            </Field>

            <Field label="Password" htmlFor="login-password" required>
              <input
                id="login-password"
                type="password"
                className="input"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </Field>

            <button
              type="submit"
              className="btn btn-primary mt-2 w-full"
              disabled={loading}
            >
              {loading ? 'Signing in...' : 'Sign in'}
            </button>

            <p className="mt-2 text-center text-xs muted">
              Need a citizen account?{' '}
              <button
                type="button"
                className="text-(--accent) hover:underline font-semibold cursor-pointer"
                onClick={() => switchMode('register')}
              >
                Register as Citizen
              </button>
            </p>
          </form>
        ) : (
          <form className="grid gap-4 card card-pad" onSubmit={handleRegister}>
            <Field label="Full Name" htmlFor="register-name" required>
              <input
                id="register-name"
                type="text"
                className="input"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your full name"
                autoComplete="name"
              />
            </Field>

            <Field label="Email Address" htmlFor="register-email" required>
              <input
                id="register-email"
                type="email"
                className="input"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="citizen@example.com"
                autoComplete="email"
              />
            </Field>

            <Field
              label="Password"
              htmlFor="register-password"
              required
              hint="Must be at least 8 characters."
            >
              <input
                id="register-password"
                type="password"
                className="input"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                autoComplete="new-password"
              />
            </Field>

            <Field
              label="Confirm Password"
              htmlFor="register-confirm-password"
              required
            >
              <input
                id="register-confirm-password"
                type="password"
                className="input"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter your password"
                autoComplete="new-password"
              />
            </Field>

            <button
              type="submit"
              className="btn btn-primary mt-2 w-full"
              disabled={loading}
            >
              {loading ? 'Creating account...' : 'Register as Citizen'}
            </button>

            <p className="mt-2 text-center text-xs muted">
              Already have an account?{' '}
              <button
                type="button"
                className="text-(--accent) hover:underline font-semibold cursor-pointer"
                onClick={() => switchMode('login')}
              >
                Sign in
              </button>
            </p>
          </form>
        )}
      </div>
    </main>
  )
}
