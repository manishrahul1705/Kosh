import React, { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Gem } from 'lucide-react'
import { authConfigured, DEV_LOGIN, signIn } from '@/lib/auth'
import { Button } from '@/components/ui/Button'

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
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white border border-gray-200 rounded-xl p-6 space-y-4">
        <div className="flex items-center gap-2">
          <div className="bg-[#1e5aab] rounded-lg p-1.5"><Gem size={18} className="text-white" /></div>
          <h1 className="text-lg font-semibold text-gray-900">GeM Tender Intelligence</h1>
        </div>
        {DEV_LOGIN && (
          <p className="text-sm text-amber-800 bg-amber-50 rounded-md p-2">
            Local test sign-in: enter any email, no password. For use on this computer only.
          </p>
        )}
        {!authConfigured() && (
          <p className="text-sm text-amber-700 bg-amber-50 rounded-md p-2">
            Sign-in is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.
          </p>
        )}
        <label className="block text-sm">
          <span className="text-gray-700">Email</span>
          <input type="email" required autoComplete="username" value={email}
                 onChange={(e) => setEmail(e.target.value)}
                 className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2" />
        </label>
        {!DEV_LOGIN && (
          <label className="block text-sm">
            <span className="text-gray-700">Password</span>
            <input type="password" required autoComplete="current-password" value={password}
                   onChange={(e) => setPassword(e.target.value)}
                   className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2" />
          </label>
        )}
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <Button type="submit" loading={busy} className="w-full">Sign in</Button>
      </form>
    </div>
  )
}
