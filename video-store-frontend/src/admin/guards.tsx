import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Spinner } from '@/components/ui'
import { adminApi, type AdminApiError } from './api'
import { can, useAdminStore } from './store'

/**
 * Blocks everything below it until the stored token has been re-validated by the
 * server (account still active, role current). No token / rejected token → login.
 */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const token = useAdminStore((s) => s.token)
  const setAdmin = useAdminStore((s) => s.setAdmin)
  const location = useLocation()
  const [state, setState] = useState<'checking' | 'ok' | 'offline'>('checking')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    setState('checking')
    adminApi.me()
      .then((admin) => { if (!cancelled) { setAdmin(admin); setState('ok') } })
      .catch((e: AdminApiError) => {
        // 401 already cleared the session (→ redirect below); anything else is a connection problem.
        if (!cancelled && e.kind !== 'session') setState('offline')
      })
    return () => { cancelled = true }
  }, [token, attempt, setAdmin])

  if (!token) return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />
  if (state === 'checking') {
    return (
      <div className="min-h-app bg-navy flex items-center justify-center">
        <Spinner size={28} />
      </div>
    )
  }
  if (state === 'offline') {
    return (
      <div className="min-h-app bg-navy flex flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-[14px] text-[#9CA3AF]">সার্ভারের সঙ্গে সংযোগ করা যাচ্ছে না।</p>
        <button className="btn-ghost !w-auto px-6" onClick={() => setAttempt((n) => n + 1)}>আবার চেষ্টা করুন</button>
      </div>
    )
  }
  return <>{children}</>
}

/** Shows an access-denied screen unless the admin's role has the permission. */
export function RequirePermission({ permission, children }: { permission: string; children: ReactNode }) {
  const admin = useAdminStore((s) => s.admin)
  return can(admin, permission) ? <>{children}</> : <Forbidden />
}

/** Same as RequirePermission, but any one of the permissions is enough (e.g. view orders OR review payments). */
export function RequireAnyPermission({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const admin = useAdminStore((s) => s.admin)
  return permissions.some((p) => can(admin, p)) ? <>{children}</> : <Forbidden />
}

export function Forbidden() {
  return (
    <div className="min-h-app bg-navy flex flex-col items-center justify-center gap-2 px-6 text-center">
      <div className="text-[40px]">🚫</div>
      <h1 className="text-[16px] font-bold text-white">অনুমতি নেই</h1>
      <p className="text-[13px] text-[#9CA3AF]">এই পেজ দেখার অনুমতি আপনার Role-এ নেই।</p>
    </div>
  )
}
