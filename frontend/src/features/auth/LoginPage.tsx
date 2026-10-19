import React, { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Landmark, Shield, Sparkles } from 'lucide-react'
import { authConfigured, DEV_LOGIN, signIn } from '@/lib/auth'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'

export const LoginPage: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await signIn(email, password)
      const from = (location.state as { from?: string } | null)?.from ?? '/'
      navigate(from, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8fafb] dark:bg-metal-950 px-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 text-white shadow-metal mx-auto">
            <Landmark size={24} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-metal-900 dark:text-white tracking-tight">Kosh</h1>
            <p className="text-xs text-metal-500 font-medium">SME Finance Copilot · Autom Squad</p>
          </div>
        </div>

        <form onSubmit={submit} className="bg-white dark:bg-metal-900 border border-metal-200/80 dark:border-metal-800 rounded-2xl p-6 shadow-metal-lg space-y-4">
          <div className="flex items-center gap-2 pb-2 border-b border-metal-100 dark:border-metal-800">
            <span className="w-1.5 h-4 rounded-full bg-primary-500 shrink-0" />
            <h2 className="text-sm font-bold text-metal-900 dark:text-white">Sign in to your workspace</h2>
          </div>

          {DEV_LOGIN && (
            <p className="text-xs text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-xl p-3 font-medium">
              Local test sign-in: enter any email, no password. For use on this computer only.
            </p>
          )}
          {!authConfigured() && (
            <p className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-xl p-3 font-medium">
              Sign-in is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.
            </p>
          )}

          <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300">
            <span>Email</span>
            <input
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1.5 w-full border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white rounded-xl px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
            />
          </label>

          {!DEV_LOGIN && (
            <label className="block text-xs font-semibold text-metal-700 dark:text-metal-300">
              <span>Password</span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1.5 w-full border border-metal-200 dark:border-metal-700 bg-white dark:bg-metal-800 text-metal-900 dark:text-white rounded-xl px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
              />
            </label>
          )}

          {error && <p role="alert" className="text-xs font-medium text-rose-700 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/40 p-2.5 rounded-xl border border-rose-200 dark:border-rose-800">{error}</p>}

          <Button type="submit" variant="primary" loading={busy} className="w-full">
            Sign in
          </Button>

          <p className="text-[11px] text-center text-metal-400 pt-2">
            Protected local sandbox environment · Zero external data leak
          </p>
        </form>
      </div>
    </div>
  )
}
