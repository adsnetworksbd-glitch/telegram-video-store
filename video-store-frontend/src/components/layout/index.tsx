import { useState, useEffect, useCallback, useRef, type ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useConfigStore, useUserStore } from '@/store'
import { setToastFn, cx } from '@/components/ui'
import { useTelegramBackButton, hasNativeBack, getTelegram } from '@/hooks/useTelegram'
import { ensureCategories } from '@/hooks/useCategories'
import { isHapticEnabled } from '@/utils'
import { refreshUnreadCount } from '@/hooks/useUnreadCount'
import { refreshAppConfig } from '@/hooks/useAppConfig'

// ─── Bottom Navigation ────────────────────────────────────────────────────────
const NAV_ITEMS = [
  {
    label: 'হোম',
    path: '/',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        <polyline points="9 22 9 12 15 12 15 22" />
      </svg>
    ),
  },
  {
    label: 'ভিডিও',
    path: '/videos',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="23 7 16 12 23 17 23 7" />
        <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
      </svg>
    ),
  },
  {
    label: 'ক্যাটাগরি',
    path: '/categories',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ),
  },
  {
    label: 'প্যাকেজ',
    path: '/packages',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      </svg>
    ),
  },
  {
    label: 'অ্যাকাউন্ট',
    path: '/account',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    ),
  },
]

export function BottomNav() {
  const location = useLocation()
  const navigate = useNavigate()

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/'
    return location.pathname.startsWith(path)
  }

  function go(path: string) {
    if (location.pathname === path) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
      return
    }
    try { if (isHapticEnabled()) getTelegram()?.HapticFeedback?.selectionChanged() } catch { /* ignore */ }
    navigate(path)
  }

  return (
    <nav
      aria-label="প্রধান নেভিগেশন"
      className="fixed bottom-0 left-0 right-0 z-50 bg-[rgba(17,24,39,0.97)] backdrop-blur-[12px] border-t border-border"
      style={{
        paddingBottom: 'var(--app-safe-bottom)',
        paddingLeft: 'var(--app-safe-left)',
        paddingRight: 'var(--app-safe-right)',
      }}
    >
      <div className="flex" style={{ minHeight: 'var(--nav-height)' }}>
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.path)
          return (
            <button
              key={item.path}
              onClick={() => go(item.path)}
              aria-current={active ? 'page' : undefined}
              className="flex-1 min-w-0 flex flex-col items-center justify-center gap-[3px] py-2 cursor-pointer border-none bg-transparent"
            >
              <div
                className="w-[22px] h-[22px]"
                style={{
                  stroke: active ? '#3B82F6' : '#6B7280',
                  color: active ? '#3B82F6' : '#6B7280',
                }}
              >
                {item.icon}
              </div>
              <span
                className="text-[10px] font-medium truncate max-w-full px-1"
                style={{ color: active ? '#3B82F6' : '#6B7280' }}
              >
                {item.label}
              </span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}

// ─── App Header ───────────────────────────────────────────────────────────────
interface AppHeaderProps {
  showSearch?: boolean
  showNotif?: boolean
  showProfile?: boolean
}

export function AppHeader({ showSearch = true, showNotif = true, showProfile = true }: AppHeaderProps) {
  const navigate = useNavigate()
  const { appConfig } = useConfigStore()
  const { unreadCount } = useUserStore()

  return (
    <header className="sticky-safe z-40 bg-[rgba(10,14,26,0.95)] backdrop-blur-[8px] border-b border-border px-4 py-3">
      <div className="flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-2">
          {appConfig?.app_logo_url ? (
            <img
              src={appConfig.app_logo_url}
              alt=""
              className="w-8 h-8 rounded-[8px] object-cover bg-card"
            />
          ) : (
            <div className="w-8 h-8 rounded-[8px] bg-gradient-blue flex items-center justify-center">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="white">
                <path d="M4 6h16M4 10h16M4 14h8M4 18h6" stroke="white" strokeWidth="2" strokeLinecap="round" fill="none" />
                <circle cx="18" cy="16" r="4" fill="none" stroke="white" strokeWidth="2" />
                <path d="M18 14v4M16 16h4" stroke="white" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </div>
          )}
          <span className="text-[17px] font-semibold bg-gradient-to-r from-primary-light to-secondary-light bg-clip-text text-transparent">
            {appConfig?.app_name ?? 'Video Store'}
          </span>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3">
          {showSearch && (
            <button
              onClick={() => navigate('/search')}
              aria-label="খুঁজুন"
              className="w-9 h-9 rounded-full bg-card border border-border flex items-center justify-center"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" strokeWidth="1.8" strokeLinecap="round">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
              </svg>
            </button>
          )}
          {showNotif && (
            <button
              onClick={() => navigate('/notifications')}
              aria-label={unreadCount > 0 ? `Notifications, ${unreadCount}টি অপঠিত` : 'Notifications'}
              className="relative w-9 h-9 rounded-full bg-card border border-border flex items-center justify-center"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" strokeWidth="1.8" strokeLinecap="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
              {unreadCount > 0 && (
                <span className="absolute -top-[2px] -right-[2px] min-w-[16px] h-4 px-[3px] rounded-full bg-danger border-[1.5px] border-navy text-[9px] font-bold text-white flex items-center justify-center">
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </button>
          )}
          {showProfile && (
            <button
              onClick={() => navigate('/account')}
              className="w-9 h-9 rounded-full bg-card border border-primary/30 flex items-center justify-center"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" strokeWidth="1.8" strokeLinecap="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </header>
  )
}

// ─── Sub Page Header (with back button) ──────────────────────────────────────
interface SubHeaderProps {
  title: string
  onBack?: () => void
  right?: ReactNode
}

export function SubHeader({ title, onBack, right }: SubHeaderProps) {
  const navigate = useNavigate()
  // Inside Telegram the native BackButton (see useTelegramBackButton) already
  // handles "back"; keep the in-app arrow for browsers, old clients and for
  // pages that pass a custom onBack.
  const showArrow = Boolean(onBack) || !hasNativeBack()
  return (
    <header className="flex items-center gap-3 px-4 py-3 border-b border-border bg-[rgba(10,14,26,0.95)] backdrop-blur-[8px] sticky-safe z-40">
      {showArrow && (
        <button
          onClick={onBack ?? (() => navigate(-1))}
          aria-label="ফিরে যান"
          className="w-8 h-8 rounded-full bg-card border border-border flex items-center justify-center flex-shrink-0"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#F9FAFB" strokeWidth="2" strokeLinecap="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
      )}
      <span className="flex-1 text-[15px] font-semibold text-white truncate">{title}</span>
      {right}
    </header>
  )
}

// ─── Page Wrapper ─────────────────────────────────────────────────────────────
interface PageWrapperProps {
  children: ReactNode
  className?: string
  hasBottomNav?: boolean
}

export function PageWrapper({ children, className = '', hasBottomNav = true }: PageWrapperProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15 }}
      className={cx(
        'min-h-app overflow-y-auto bg-navy',
        hasBottomNav ? 'pb-nav' : 'pb-page',
        className,
      )}
    >
      {children}
    </motion.div>
  )
}

// ─── Announcement Bar ─────────────────────────────────────────────────────────
// Admin-controlled text, optionally with a link (homepage_announcement_url).
// The link is opened only if it is a real http(s) URL; the text is rendered as
// plain text (never as HTML).
export function AnnouncementBar() {
  const { appConfig } = useConfigStore()
  const text = appConfig?.homepage_announcement?.trim()
  if (!text) return null

  const rawUrl = appConfig?.homepage_announcement_url?.trim()
  let href: string | null = null
  if (rawUrl) {
    try { const u = new URL(rawUrl); if (u.protocol === 'https:' || u.protocol === 'http:') href = u.toString() } catch { /* ignore bad URL */ }
  }

  function open() {
    if (!href) return
    const tg = getTelegram()
    const isTg = /^https?:\/\/(t|telegram)\.me\//.test(href)
    if (tg?.initData && isTg && typeof tg.openTelegramLink === 'function') tg.openTelegramLink(href)
    else if (tg?.initData && typeof tg.openLink === 'function') tg.openLink(href)
    else window.open(href, '_blank', 'noopener,noreferrer')
  }

  const body = (
    <>
      <span className="text-[13px] flex-shrink-0" aria-hidden>🔔</span>
      <span className="flex-1 text-left text-[12px] text-[#93C5FD] leading-[1.4] break-words">{text}</span>
      {href && <span className="text-[11px] text-primary font-semibold flex-shrink-0">খুলুন ›</span>}
    </>
  )
  const cls = 'mx-4 mt-3 bg-primary/10 border border-primary/25 rounded-[10px] px-3 py-2 flex items-center gap-2'
  return href
    ? <button onClick={open} className={cx(cls, 'w-[calc(100%-32px)]')}>{body}</button>
    : <div className={cls}>{body}</div>
}

// ─── Maintenance Screen ───────────────────────────────────────────────────────
export function MaintenanceScreen() {
  const { appConfig } = useConfigStore()
  return (
    <div className="min-h-app bg-navy flex flex-col items-center justify-center px-6 text-center">
      <div className="text-5xl mb-5">🔧</div>
      <h1 className="text-[20px] font-bold text-white mb-3">রক্ষণাবেক্ষণ চলছে</h1>
      <p className="text-[14px] text-[#9CA3AF] leading-[1.6]">
        {appConfig?.maintenance_message || 'আমরা কিছু সময়ের জন্য রক্ষণাবেক্ষণ কাজ করছি। একটু পরে আবার চেষ্টা করুন।'}
      </p>
    </div>
  )
}

// ─── Toast Provider ───────────────────────────────────────────────────────────
interface ToastMessage {
  id: string
  text: string
  type: 'success' | 'error' | 'info'
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([])
  const counter = useRef(0)

  const addToast = useCallback((text: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = String(++counter.current)
    setToasts(ts => [...ts, { id, text, type }])
    setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), 3000)
  }, [])

  useEffect(() => { setToastFn(addToast) }, [addToast])

  const colors = {
    success: 'bg-success/15 border-success/30 text-[#6EE7B7]',
    error:   'bg-danger/15 border-danger/30 text-[#FCA5A5]',
    info:    'bg-primary/15 border-primary/30 text-[#93C5FD]',
  }

  return (
    <>
      {children}
      <div className="fixed left-4 right-4 z-[200] flex flex-col gap-2 pointer-events-none" style={{ top: 'calc(var(--app-safe-top) + 12px)' }}>
        <AnimatePresence>
          {toasts.map(t => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className={cx('border rounded-[10px] px-4 py-3 text-[13px] font-medium shadow-lg', colors[t.type])}
            >
              {t.text}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </>
  )
}

// ─── App Shell ────────────────────────────────────────────────────────────────
// Wraps every routed page (rendered inside AuthGate, so config is loaded):
//  • drives Telegram's native BackButton from the router
//  • preloads category names used by video cards
//  • shows the admin-controlled maintenance screen
//  • paints the top safe-area strip so scrolled content never shows behind it
export function AppShell({ children }: { children: ReactNode }) {
  const { appConfig } = useConfigStore()

  useTelegramBackButton()

  useEffect(() => { void ensureCategories() }, [])

  // Unread badge + app settings: load once, then again whenever the user comes
  // back to the app (settings only when stale — see hooks/useAppConfig).
  useEffect(() => {
    void refreshUnreadCount()
    void refreshAppConfig()
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      void refreshUnreadCount()
      void refreshAppConfig()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [])

  // If the login-time settings load failed, keep trying (bounded) — otherwise
  // maintenance mode, the USDT rate and support links would stay missing.
  const configMissing = appConfig === null
  useEffect(() => {
    if (!configMissing) return
    let tries = 0
    const t = setInterval(() => {
      if (++tries > 6) { clearInterval(t); return }
      void refreshAppConfig()
    }, 15000)
    return () => clearInterval(t)
  }, [configMissing])

  if (appConfig?.maintenance_mode) return <MaintenanceScreen />

  return (
    <>
      <div
        aria-hidden
        className="fixed top-0 left-0 right-0 z-[60] bg-navy pointer-events-none"
        style={{ height: 'var(--app-safe-top)' }}
      />
      {children}
    </>
  )
}
