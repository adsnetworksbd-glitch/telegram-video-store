import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AppShell, BottomNav, ToastProvider } from '@/components/layout'
import { initTelegramApp } from '@/hooks/useTelegram'
import { AuthGate } from '@/pages/Auth'
import { Spinner } from '@/components/ui'

// Admin Panel (username + password login, NOT Telegram) — kept outside AuthGate.
const AdminApp        = lazy(() => import('@/admin/AdminApp'))

// ─── Lazy-loaded pages ────────────────────────────────────────────────────────
const Home            = lazy(() => import('@/pages/Home'))
const Categories      = lazy(() => import('@/pages/Categories'))
const CategoryDetail  = lazy(() => import('@/pages/CategoryDetail'))
const AllVideos       = lazy(() => import('@/pages/AllVideos'))
const VideoDetail     = lazy(() => import('@/pages/VideoDetail'))
const WatchAds        = lazy(() => import('@/pages/WatchAds'))
const AdsSuccess      = lazy(() => import('@/pages/AdsSuccess'))
const Purchase        = lazy(() => import('@/pages/Purchase'))
const Payment         = lazy(() => import('@/pages/Payment'))
const PaymentPending  = lazy(() => import('@/pages/PaymentPending'))
const PaymentSuccess  = lazy(() => import('@/pages/PaymentSuccess'))
const PaymentFailed   = lazy(() => import('@/pages/PaymentFailed'))
const Packages        = lazy(() => import('@/pages/Packages'))
const PackageDetail   = lazy(() => import('@/pages/PackageDetail'))
const MyPurchases     = lazy(() => import('@/pages/MyPurchases'))
const Account         = lazy(() => import('@/pages/Account'))
const Transactions    = lazy(() => import('@/pages/Transactions'))
const Search          = lazy(() => import('@/pages/Search'))
const Support         = lazy(() => import('@/pages/Support'))
const Notifications   = lazy(() => import('@/pages/Notifications'))
const Referral        = lazy(() => import('@/pages/Referral'))

// ─── Page loader ─────────────────────────────────────────────────────────────
function PageLoader() {
  return (
    <div className="min-h-app bg-navy flex items-center justify-center">
      <Spinner size={28} />
    </div>
  )
}

// ─── App Router ───────────────────────────────────────────────────────────────
export function AppRouter() {
  // Telegram bootstrap (ready / expand / colours / safe area) runs once,
  // before auth, so the native splash is dismissed as early as possible.
  useEffect(() => initTelegramApp(), [])

  return (
    <BrowserRouter>
      <Routes>
        {/* Admin Panel: its own login, never wrapped by the Telegram AuthGate */}
        <Route
          path="/admin/*"
          element={<Suspense fallback={<PageLoader />}><AdminApp /></Suspense>}
        />
        <Route path="*" element={<MiniApp />} />
      </Routes>
    </BrowserRouter>
  )
}

function MiniApp() {
  return (
    <ToastProvider>
      <AuthGate>
        <AppShell>
          <Suspense fallback={<PageLoader />}>
            <AppRoutes />
          </Suspense>
        </AppShell>
      </AuthGate>
    </ToastProvider>
  )
}

function AppRoutes() {
  return (
    <>
      <Routes>
        {/* Home */}
        <Route path="/" element={<Home />} />

        {/* Videos */}
        <Route path="/videos" element={<AllVideos />} />
        <Route path="/videos/:id" element={<VideoDetail />} />
        <Route path="/videos/:id/watch-ads" element={<WatchAds />} />
        <Route path="/videos/:id/ads-success" element={<AdsSuccess />} />
        <Route path="/videos/:id/purchase" element={<Purchase />} />

        {/* Categories */}
        <Route path="/categories" element={<Categories />} />
        <Route path="/categories/:id" element={<CategoryDetail />} />

        {/* Packages */}
        <Route path="/packages" element={<Packages />} />
        <Route path="/packages/:id" element={<PackageDetail />} />
        <Route path="/packages/:id/purchase" element={<Purchase />} />
        <Route path="/packages/:id/watch-ads" element={<WatchAds />} />
        <Route path="/packages/:id/ads-success" element={<AdsSuccess />} />

        {/* Payment */}
        <Route path="/payment/:orderId" element={<Payment />} />
        <Route path="/payment/:orderId/pending" element={<PaymentPending />} />
        <Route path="/payment/:orderId/success" element={<PaymentSuccess />} />
        <Route path="/payment/:orderId/failed" element={<PaymentFailed />} />

        {/* User */}
        <Route path="/my-purchases" element={<MyPurchases />} />
        <Route path="/account" element={<Account />} />
        <Route path="/transactions" element={<Transactions />} />
        <Route path="/notifications" element={<Notifications />} />
        <Route path="/referral" element={<Referral />} />

        {/* Misc */}
        <Route path="/search" element={<Search />} />
        <Route path="/support" element={<Support />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {/* Bottom nav — shown only on root pages */}
      <ConditionalBottomNav />
    </>
  )
}

// Root pages that show the Bottom Navigation (must match ROOT_PATHS in useTelegram)
const BOTTOM_NAV_PATHS = ['/', '/videos', '/categories', '/packages', '/account']

function ConditionalBottomNav() {
  const { pathname } = useLocation()
  return BOTTOM_NAV_PATHS.includes(pathname) ? <BottomNav /> : null
}
