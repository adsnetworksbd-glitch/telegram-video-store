import { useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { isHapticEnabled } from '@/utils'

// ─── Telegram WebApp SDK typings (only what the app uses) ────────────────────
interface TelegramInset { top: number; bottom: number; left: number; right: number }

export interface TelegramWebApp {
  initData: string
  initDataUnsafe: {
    user?: {
      id: number
      first_name: string
      last_name?: string
      username?: string
      photo_url?: string
      language_code?: string
    }
    start_param?: string
    hash: string
    auth_date: number
  }
  version: string
  platform: string
  colorScheme: 'light' | 'dark'
  themeParams: Record<string, string>
  isExpanded: boolean
  viewportHeight: number
  viewportStableHeight: number
  /** Bot API 8.0+ — device safe area (notch / system bars) */
  safeAreaInset?: TelegramInset
  /** Bot API 8.0+ — area covered by Telegram's own UI (fullscreen mode) */
  contentSafeAreaInset?: TelegramInset
  BackButton: {
    isVisible: boolean
    show(): void
    hide(): void
    onClick(fn: () => void): void
    offClick(fn: () => void): void
  }
  MainButton: {
    text: string
    color: string
    textColor: string
    isVisible: boolean
    isActive: boolean
    show(): void
    hide(): void
    setText(text: string): void
    onClick(fn: () => void): void
    offClick(fn: () => void): void
    showProgress(leaveActive?: boolean): void
    hideProgress(): void
  }
  HapticFeedback: {
    impactOccurred(style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'): void
    notificationOccurred(type: 'error' | 'success' | 'warning'): void
    selectionChanged(): void
  }
  isVersionAtLeast(version: string): boolean
  onEvent(eventType: string, handler: () => void): void
  offEvent(eventType: string, handler: () => void): void
  expand(): void
  close(): void
  ready(): void
  disableVerticalSwipes?(): void
  enableClosingConfirmation?(): void
  disableClosingConfirmation?(): void
  openTelegramLink(url: string): void
  openLink(url: string, options?: { try_instant_view?: boolean }): void
  showAlert(message: string, callback?: () => void): void
  showConfirm(message: string, callback: (confirmed: boolean) => void): void
  showPopup(params: object, callback?: (id: string) => void): void
  setHeaderColor(color: string): void
  setBackgroundColor(color: string): void
  setBottomBarColor?(color: string): void
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp
    }
  }
}

// ─── Plain helpers (usable outside React) ────────────────────────────────────
const BG_COLOR = '#0A0E1A'

export function getTelegram(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp
}

/** True when running inside a real Telegram client that supports `version`. */
export function tgSupports(version: string): boolean {
  const tg = getTelegram()
  if (!tg || !tg.initData) return false
  try { return tg.isVersionAtLeast(version) } catch { return false }
}

/** Telegram's native BackButton is usable (Bot API 6.1+). */
export function hasNativeBack(): boolean {
  return tgSupports('6.1')
}

// Mirror Telegram's safe-area values into our own CSS variables. The CSS in
// index.css already falls back to env() and Telegram's --tg-* variables, so
// this only refines the values when the JS API reports them.
function syncSafeArea(tg: TelegramWebApp) {
  const root = document.documentElement.style
  const sa = tg.safeAreaInset
  const ca = tg.contentSafeAreaInset
  if (!sa && !ca) return
  const side = (name: 'top' | 'right' | 'bottom' | 'left') =>
    `max(env(safe-area-inset-${name}, 0px), ${sa?.[name] ?? 0}px)`
  root.setProperty('--app-safe-top', `calc(${side('top')} + ${ca?.top ?? 0}px)`)
  root.setProperty('--app-safe-bottom', `calc(${side('bottom')} + ${ca?.bottom ?? 0}px)`)
  root.setProperty('--app-safe-left', `calc(${side('left')} + ${ca?.left ?? 0}px)`)
  root.setProperty('--app-safe-right', `calc(${side('right')} + ${ca?.right ?? 0}px)`)
}

let initialised = false

/**
 * Telegram WebApp bootstrap: ready(), expand(), theme colours, vertical-swipe
 * lock (all once) and safe-area sync (listeners are re-attached on every call,
 * so React StrictMode's mount → cleanup → mount cycle keeps working).
 * No-op outside Telegram. Returns a cleanup function for the listeners.
 */
export function initTelegramApp(): () => void {
  const tg = getTelegram()
  if (!tg) return () => {}

  if (!initialised) {
    initialised = true
    try { tg.ready() } catch { /* ignore */ }
    try { tg.expand() } catch { /* ignore */ }

    // Colour / swipe APIs throw or warn on old clients — guard by version.
    if (tg.isVersionAtLeast('6.1')) {
      try { tg.setBackgroundColor(BG_COLOR) } catch { /* ignore */ }
      try { tg.setHeaderColor(BG_COLOR) } catch { /* ignore */ }
    }
    if (tg.isVersionAtLeast('7.10')) {
      try { tg.setBottomBarColor?.(BG_COLOR) } catch { /* ignore */ }
    }
    if (tg.isVersionAtLeast('7.7')) {
      // Stops an accidental swipe-down from closing the app while scrolling.
      try { tg.disableVerticalSwipes?.() } catch { /* ignore */ }
    }
  }

  const sync = () => syncSafeArea(tg)
  sync()
  tg.onEvent('safeAreaChanged', sync)
  tg.onEvent('contentSafeAreaChanged', sync)
  tg.onEvent('viewportChanged', sync)

  return () => {
    tg.offEvent('safeAreaChanged', sync)
    tg.offEvent('contentSafeAreaChanged', sync)
    tg.offEvent('viewportChanged', sync)
  }
}

// ─── Back button routing ─────────────────────────────────────────────────────
// Pages that live in the bottom navigation are "root" pages: no back button.
const ROOT_PATHS = ['/', '/videos', '/categories', '/packages', '/account']

/**
 * Drives Telegram's native BackButton from the router location:
 * hidden on root pages, visible everywhere else. If the app was opened on a
 * deep link (no in-app history), Back goes Home instead of closing the app.
 */
export function useTelegramBackButton() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const isRoot = ROOT_PATHS.includes(pathname)

  useEffect(() => {
    const tg = getTelegram()
    if (!tg || !tgSupports('6.1')) return

    if (isRoot) {
      tg.BackButton.hide()
      return
    }

    // Finished payment screens: Back leaves the payment flow (going "back"
    // would land on a stale payment page or a consumed order).
    const terminalPayment = /^\/payment\/[^/]+\/(pending|success|failed)$/.test(pathname)

    const handler = () => {
      if (terminalPayment) { navigate('/', { replace: true }); return }
      const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0
      if (idx > 0) navigate(-1)
      else navigate('/', { replace: true })
    }
    tg.BackButton.show()
    tg.BackButton.onClick(handler)
    return () => {
      tg.BackButton.offClick(handler)
    }
  }, [isRoot, pathname, navigate])
}

// ─── Hook (kept API-compatible with Phase 1-5 usage) ─────────────────────────
export function useTelegram() {
  const tg = getTelegram()
  const navigate = useNavigate()

  const showBackButton = useCallback((onBack?: () => void) => {
    if (!tg) return
    tg.BackButton.show()
    const handler = onBack ?? (() => navigate(-1))
    tg.BackButton.onClick(handler)
    return () => tg.BackButton.offClick(handler)
  }, [tg, navigate])

  const hideBackButton = useCallback(() => {
    if (!tg) return
    tg.BackButton.hide()
  }, [tg])

  const haptic = useCallback((type: 'light' | 'medium' | 'selection' | 'success' | 'error' | 'warning' = 'light') => {
    if (!tg?.HapticFeedback || !isHapticEnabled()) return
    try {
      if (type === 'success' || type === 'error' || type === 'warning') {
        tg.HapticFeedback.notificationOccurred(type)
      } else if (type === 'selection') {
        tg.HapticFeedback.selectionChanged()
      } else {
        tg.HapticFeedback.impactOccurred(type)
      }
    } catch { /* ignore on unsupported clients */ }
  }, [tg])

  return {
    tg,
    initData: tg?.initData ?? '',
    user: tg?.initDataUnsafe?.user ?? null,
    startParam: tg?.initDataUnsafe?.start_param ?? null,
    showBackButton,
    hideBackButton,
    haptic,
  }
}
