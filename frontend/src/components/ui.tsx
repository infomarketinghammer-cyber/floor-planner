import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router'

export function Button({ className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50 ${className}`}
      {...props}
    />
  )
}

export function Field({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input
        className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600"
        {...props}
      />
    </label>
  )
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null
  return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{children}</p>
}

export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="mb-1 text-xl font-semibold">
          <Link to="/" className="hover:text-brand-700">
            Floor Planner
          </Link>
        </h1>
        <p className="mb-6 text-sm text-slate-500">{title}</p>
        {children}
      </div>
    </div>
  )
}
