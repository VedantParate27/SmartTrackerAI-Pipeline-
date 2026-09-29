import { useState } from 'react'
import { Callout, ErrorState, Field, Spinner } from './ui'
import { fieldErrors } from '#/lib/api'
import { registerAndSignIn, signIn, signOut, useAuth } from '#/lib/auth'

/** Roles each staff area accepts — mirrors get_current_admin_user / get_current_cleaner_user. */
const ACCEPTED: Record<'admin' | 'cleaner', string[]> = {
  admin: ['admin'],
  cleaner: ['cleaner', 'admin'],
}

export default function AuthPanel({
  requireRole,
}: {
  /** A staff area; hides citizen registration and flags the wrong role. */
  requireRole?: 'admin' | 'cleaner'
}) {
  const { session, hydrated } = useAuth()
  const staffOnly = requireRole !== undefined
  const [registering, setRegistering] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fields, setFields] = useState<Record<string, string>>({})

  if (!hydrated) {
    return <Callout title="Checking account">Restoring your session…</Callout>
  }

  if (session) {
    const wrongRole =
      requireRole !== undefined && !ACCEPTED[requireRole].includes(session.role)
    return (
      <Callout
        tone={wrongRole ? 'danger' : 'ok'}
        title={
          wrongRole
            ? `${requireRole === 'admin' ? 'Admin' : 'Cleaner'} account required`
            : 'Signed in'
        }
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span>
            Backend role: <strong>{session.role}</strong>
          </span>
          <button type="button" className="btn btn-sm" onClick={signOut}>
            Sign out
          </button>
        </div>
      </Callout>
    )
  }

  return (
    <section className="card card-pad" aria-labelledby="account-heading">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="account-heading" className="card-title">
            {requireRole === 'admin'
              ? 'Admin sign in'
              : requireRole === 'cleaner'
                ? 'Cleaner sign in'
                : registering
                  ? 'Create a citizen account'
                  : 'Sign in to continue'}
          </h2>
          <p className="hint">
            Complaints are protected by the backend and require a JWT session.
          </p>
        </div>
        {!staffOnly ? (
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy}
            onClick={() => {
              setRegistering((value) => !value)
              setError(null)
            }}
          >
            {registering ? 'Use existing account' : 'Create account'}
          </button>
        ) : null}
      </div>

      {error ? (
        <div className="mt-3">
          <ErrorState title="Authentication failed" message={error} />
        </div>
      ) : null}

      <form
        className="mt-4 grid gap-3"
        onSubmit={async (event) => {
          event.preventDefault()
          setBusy(true)
          setError(null)
          setFields({})
          try {
            if (registering && !staffOnly) {
              await registerAndSignIn({
                name: name.trim(),
                email: email.trim(),
                password,
              })
            } else {
              await signIn(email.trim(), password)
            }
          } catch (caught) {
            setFields(fieldErrors(caught))
            setError(
              caught instanceof Error
                ? caught.message
                : 'Authentication failed.',
            )
          } finally {
            setBusy(false)
          }
        }}
      >
        {registering && !staffOnly ? (
          <Field
            label="Full name"
            htmlFor="auth-name"
            required
            error={fields.name}
          >
            <input
              id="auth-name"
              className="input"
              autoComplete="name"
              minLength={2}
              maxLength={100}
              required
              value={name}
              aria-invalid={Boolean(fields.name)}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
        ) : null}
        <Field label="Email" htmlFor="auth-email" required error={fields.email}>
          <input
            id="auth-email"
            className="input"
            type="email"
            autoComplete="email"
            required
            value={email}
            aria-invalid={Boolean(fields.email)}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>
        <Field
          label="Password"
          htmlFor="auth-password"
          required
          hint={registering ? 'At least 8 characters.' : undefined}
          error={fields.password}
        >
          <input
            id="auth-password"
            className="input"
            type="password"
            autoComplete={registering ? 'new-password' : 'current-password'}
            minLength={8}
            maxLength={128}
            required
            value={password}
            aria-invalid={Boolean(fields.password)}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? <Spinner /> : null}
          {busy
            ? 'Signing in…'
            : registering && !staffOnly
              ? 'Create account and sign in'
              : 'Sign in'}
        </button>
      </form>
    </section>
  )
}
