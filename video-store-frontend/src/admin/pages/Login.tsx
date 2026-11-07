import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui'
import { adminApi, type AdminApiError } from '../api'
import { useAdminStore } from '../store'

export default function AdminLogin() {
  const token = useAdminStore((s) => s.token)
  const setSession = useAdminStore((s) => s.setSession)
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (token) return <Navigate to="/admin" replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (loading) return
    if (!username.trim() || !password) {
      setError('ইউজারনেম ও পাসওয়ার্ড দিন।')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await adminApi.login(username.trim(), password)
      setPassword('')
      setSession(res.token, res.expiresIn, res.admin)
      navigate(from && from.startsWith('/admin') && from !== '/admin/login' ? from : '/admin', { replace: true })
    } catch (err) {
      setError((err as AdminApiError)?.message || 'লগইন করা যায়নি। আবার চেষ্টা করুন।')
      setLoading(false)
    }
  }

  const input =
    'w-full rounded-[12px] border border-border bg-card px-4 py-3 text-[14px] text-white ' +
    'placeholder:text-[#6B7280] outline-none focus:border-primary'

  return (
    <div className="min-h-app bg-navy flex items-center justify-center px-5">
      <form onSubmit={submit} className="w-full max-w-[380px] card-base p-6 flex flex-col gap-4" noValidate>
        <div className="text-center">
          <div className="text-[34px]">🛡️</div>
          <h1 className="mt-1 text-[18px] font-bold text-white">Admin Login</h1>
          <p className="mt-1 text-[12px] text-[#9CA3AF]">Video Store Admin Panel</p>
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="text-[12px] font-medium text-[#9CA3AF]">ইউজারনেম</span>
          <input
            className={input}
            type="text"
            name="username"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            maxLength={64}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={loading}
            autoFocus
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-[12px] font-medium text-[#9CA3AF]">পাসওয়ার্ড</span>
          <div className="relative">
            <input
              className={`${input} pr-16`}
              type={showPw ? 'text' : 'password'}
              name="password"
              autoComplete="current-password"
              maxLength={256}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
            />
            <button
              type="button"
              onClick={() => setShowPw((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[12px] font-medium text-primary-light"
              tabIndex={-1}
            >
              {showPw ? 'লুকান' : 'দেখান'}
            </button>
          </div>
        </label>

        {error && (
          <p role="alert" className="rounded-[10px] border border-danger/30 bg-danger/15 px-3 py-2 text-[12.5px] text-[#FCA5A5]">
            {error}
          </p>
        )}

        <Button type="submit" loading={loading}>লগইন</Button>
      </form>
    </div>
  )
}
