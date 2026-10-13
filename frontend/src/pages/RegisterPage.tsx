import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router'
import { homePathFor, useAuth } from '../auth/AuthContext.tsx'
import { AuthCard, Button, ErrorText, Field } from '../components/ui.tsx'

export function RegisterPage() {
  const { user, register, isGuest } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (user && !isGuest) return <Navigate to={homePathFor(user)} replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setError('')
    setSubmitting(true)
    try {
      const created = await register({
        name: String(form.get('name')),
        email: String(form.get('email')),
        password: String(form.get('password')),
        company: String(form.get('company') ?? '') || undefined,
      })
      navigate(homePathFor(created), { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard title="Create a contractor account">
      <form onSubmit={handleSubmit} className="space-y-4">
        <ErrorText>{error}</ErrorText>
        <Field label="Full name" name="name" autoComplete="name" required />
        <Field label="Company (optional)" name="company" autoComplete="organization" />
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          required
        />
        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">
        Already registered?{' '}
        <Link to="/login" className="font-medium text-brand-600 hover:underline">
          Sign in
        </Link>
      </p>
    </AuthCard>
  )
}
