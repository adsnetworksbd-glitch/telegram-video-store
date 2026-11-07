import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { RequireAdmin, RequireAnyPermission, RequirePermission } from './guards'
import AdminLayout from './AdminLayout'
import AdminLogin from './pages/Login'
import Dashboard from './pages/Dashboard'
import Videos from './pages/Videos'
import VideoForm from './pages/VideoForm'
import Categories from './pages/Categories'
import Packages from './pages/Packages'
import PackageForm from './pages/PackageForm'
import Homepage from './pages/Homepage'
import Ads from './pages/Ads'
import Payments from './pages/Payments'
import Coupons from './pages/Coupons'
import Referral from './pages/Referral'
import Orders from './pages/Orders'
import Users from './pages/Users'
import Support from './pages/Support'
import Notifications from './pages/Notifications'
import Settings from './pages/Settings'
import Audit from './pages/Audit'
import Admins from './pages/Admins'

// Everything under /admin. Rendered OUTSIDE the Mini App's Telegram AuthGate:
// admins sign in with username + password, not Telegram. Every page sits behind
// <RequirePermission>; the server enforces the same permissions on every API call.
export default function AdminApp() {
  useEffect(() => {
    const prev = document.title
    document.title = 'Admin'
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex,nofollow'
    document.head.appendChild(meta)
    return () => { document.title = prev; meta.remove() }
  }, [])

  return (
    <Routes>
      <Route path="login" element={<AdminLogin />} />
      <Route element={<RequireAdmin><AdminLayout /></RequireAdmin>}>
        <Route index element={<RequirePermission permission="dashboard.view"><Dashboard /></RequirePermission>} />
        <Route path="videos" element={<RequirePermission permission="videos.view"><Videos /></RequirePermission>} />
        <Route path="videos/new" element={<RequirePermission permission="videos.manage"><VideoForm /></RequirePermission>} />
        <Route path="videos/:id" element={<RequirePermission permission="videos.view"><VideoForm /></RequirePermission>} />
        <Route path="categories" element={<RequirePermission permission="videos.view"><Categories /></RequirePermission>} />
        <Route path="packages" element={<RequirePermission permission="videos.view"><Packages /></RequirePermission>} />
        <Route path="packages/new" element={<RequirePermission permission="videos.manage"><PackageForm /></RequirePermission>} />
        <Route path="packages/:id" element={<RequirePermission permission="videos.view"><PackageForm /></RequirePermission>} />
        <Route path="homepage" element={<RequirePermission permission="settings.manage"><Homepage /></RequirePermission>} />
        <Route path="ads" element={<RequirePermission permission="ads.manage"><Ads /></RequirePermission>} />
        <Route path="payments" element={<RequirePermission permission="payment_methods.manage"><Payments /></RequirePermission>} />
        <Route path="coupons" element={<RequirePermission permission="coupons.manage"><Coupons /></RequirePermission>} />
        <Route path="referral" element={<RequirePermission permission="settings.manage"><Referral /></RequirePermission>} />
        <Route path="orders" element={<RequireAnyPermission permissions={['orders.view', 'payments.review']}><Orders /></RequireAnyPermission>} />
        <Route path="users" element={<RequirePermission permission="users.view"><Users /></RequirePermission>} />
        <Route path="support" element={<RequirePermission permission="support.manage"><Support /></RequirePermission>} />
        <Route path="notifications" element={<RequirePermission permission="notifications.send"><Notifications /></RequirePermission>} />
        <Route path="settings" element={<RequirePermission permission="settings.manage"><Settings /></RequirePermission>} />
        <Route path="audit" element={<RequirePermission permission="audit.view"><Audit /></RequirePermission>} />
        <Route path="admins" element={<RequirePermission permission="admins.manage"><Admins /></RequirePermission>} />
      </Route>
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  )
}
