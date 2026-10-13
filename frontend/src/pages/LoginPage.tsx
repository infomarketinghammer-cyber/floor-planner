import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { homePathFor, useAuth } from '../auth/AuthContext.tsx'
import { AuthCard, Button, ErrorText, Field } from '../components/ui.tsx'

export function LoginPage() {
  const { user, login, isGuest, startGuest } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (user && !isGuest) return <Navigate to={homePathFor(user)} replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setError('')
    setSubmitting(true)
    try {
      const loggedIn = await login(String(form.get('email')), String(form.get('password')))
      navigate(from ?? homePathFor(loggedIn), { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard title="Sign in to your account">
      <form onSubmit={handleSubmit} className="space-y-4">
        <ErrorText>{error}</ErrorText>
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Password" name="password" type="password" autoComplete="current-password" required />
        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">
        New contractor?{' '}
        <Link to="/register" className="font-medium text-brand-600 hover:underline">
          Create an account
        </Link>
      </p>
      <p className="mt-2 text-center text-sm text-slate-500">
        <button
          type="button"
          onClick={async () => {
            await startGuest()
            navigate('/', { replace: true })
          }}
          className="text-slate-600 hover:underline"
        >
          Continue without an account
        </button>
      </p>
    </AuthCard>
  )
}
