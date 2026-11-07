import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Badge, cx } from '@/components/ui'
import { ToastProvider } from '@/components/layout'
import { can, ROLE_LABEL, useAdminStore } from './store'

// Navigation entries appear only for roles that hold the permission (the server enforces it regardless).
const NAV = [
  { to: '/admin', label: 'ড্যাশবোর্ড', permission: 'dashboard.view', end: true },
  { to: '/admin/videos', label: 'ভিডিও', permission: 'videos.view', end: false },
  { to: '/admin/categories', label: 'ক্যাটাগরি', permission: 'videos.view', end: false },
  { to: '/admin/packages', label: 'প্যাকেজ', permission: 'videos.view', end: false },
  { to: '/admin/homepage', label: 'হোমপেজ', permission: 'settings.manage', end: false },
  { to: '/admin/ads', label: 'Ads', permission: 'ads.manage', end: false },
  { to: '/admin/payments', label: 'Payment', permission: 'payment_methods.manage', end: false },
  { to: '/admin/coupons', label: 'Coupon', permission: 'coupons.manage', end: false },
  { to: '/admin/referral', label: 'Referral', permission: 'settings.manage', end: false },
  { to: '/admin/orders', label: 'Order', permission: ['orders.view', 'payments.review'], end: false },
  { to: '/admin/users', label: 'ইউজার', permission: 'users.view', end: false },
  { to: '/admin/support', label: 'Support', permission: 'support.manage', end: false },
  { to: '/admin/notifications', label: 'Notification', permission: 'notifications.send', end: false },
  { to: '/admin/settings', label: 'সেটিংস', permission: 'settings.manage', end: false },
  { to: '/admin/audit', label: 'Audit Log', permission: 'audit.view', end: false },
  { to: '/admin/admins', label: 'Admin', permission: 'admins.manage', end: false },
]

export default function AdminLayout() {
  const admin = useAdminStore((s) => s.admin)
  const clear = useAdminStore((s) => s.clear)
  const navigate = useNavigate()
  if (!admin) return null

  function logout() {
    clear()
    navigate('/admin/login', { replace: true })
  }

  return (
    <ToastProvider>
      <div className="min-h-app bg-navy pb-page">
        <header className="sticky-safe z-40 border-b border-border bg-surface/95 backdrop-blur">
          <div className="mx-auto flex max-w-[960px] items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <div className="truncate text-[14px] font-bold text-white">{admin.display_name}</div>
              <div className="mt-0.5 flex items-center gap-1.5">
                <Badge variant="blue">{ROLE_LABEL[admin.role] ?? admin.role}</Badge>
                <span className="truncate text-[11px] text-[#9CA3AF]">@{admin.username}</span>
              </div>
            </div>
            <button className="btn-ghost !w-auto px-4 !py-2" onClick={logout}>লগআউট</button>
          </div>
          <nav className="mx-auto flex max-w-[960px] gap-1 overflow-x-auto px-3 pb-2">
            {NAV.filter((n) => [n.permission].flat().some((p) => can(admin, p))).map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) => cx(
                  'whitespace-nowrap rounded-[10px] px-3.5 py-1.5 text-[13px] font-medium',
                  isActive ? 'bg-primary/15 text-primary-light' : 'text-[#9CA3AF]',
                )}
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="mx-auto max-w-[960px] px-4 py-4">
          <Outlet />
        </main>
      </div>
    </ToastProvider>
  )
}
