import { useEffect, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import { authApi, configApi } from '@/api'
import { useAuthStore, useConfigStore, useUserStore } from '@/store'
import { getErrorMessage, apiConfigProblem } from '@/api/client'

// Backend failures are deliberately generic (no hash/expiry detail), so the
// message shown to the user is chosen from the HTTP status only.
function authErrorMessage(e: unknown): string {
  const status = (e as { status?: number } | null)?.status
  if (status === 401) return 'Telegram যাচাই ব্যর্থ হয়েছে। App বন্ধ করে Telegram থেকে আবার খুলুন।'
  if (status === 403) return 'এই অ্যাকাউন্ট দিয়ে প্রবেশ করা যাচ্ছে না।'
  return getErrorMessage(e, 'Authentication ব্যর্থ হয়েছে।')
}

// ─── Auth Gate ────────────────────────────────────────────────────────────────
// Runs once on app load. Verifies Telegram initData with Backend.
// On success → JWT stored in memory → app renders.
// Never stores JWT in localStorage.

interface AuthGateProps {
  children: ReactNode
}

export function AuthGate({ children }: AuthGateProps) {
  const { isAuthenticated, isLoading, error, setToken, setLoading, setError } = useAuthStore()
  const { setAppConfig } = useConfigStore()
  const { setProfile } = useUserStore()

  useEffect(() => {
    authenticate()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs exactly once on app load
  }, [])

  async function authenticate() {
    setLoading(true) // also covers the "retry" button: show the loading screen again
    if (apiConfigProblem) {
      setError(apiConfigProblem)
      return
    }
    const tg = window.Telegram?.WebApp
    if (!tg) {
      // Dev mode: no Telegram context
      if (import.meta.env.DEV) {
        console.warn('[Dev] No Telegram WebApp context — authentication is not possible outside Telegram')
        await loadConfig()
        setError('Telegram WebApp not found. Open inside Telegram.')
        return
      }
      setError('এই App শুধু Telegram-এর ভিতরে চালানো যায়।')
      return
    }

    const initData = tg.initData
    if (!initData) {
      setError('Telegram Session পাওয়া যায়নি। App বন্ধ করে আবার খুলুন।')
      return
    }

    try {
      // 1. Authenticate with backend
      const authRes = await authApi.login(initData)
      setToken(authRes.data.access_token)
      setProfile(authRes.data.user)

      // 2. Load app config in parallel
      await loadConfig()
    } catch (e: unknown) {
      setError(authErrorMessage(e))
    }
  }

  async function loadConfig() {
    try {
      const [cfgRes] = await Promise.all([
        configApi.getAppConfig(),
      ])
      setAppConfig(cfgRes.data)
    } catch {
      // Non-fatal — app can still work with defaults
    }
  }

  // ── Loading screen ─────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="min-h-app bg-navy flex flex-col items-center justify-center gap-5">
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center gap-4"
        >
          {/* Logo */}
          <div className="w-16 h-16 rounded-[18px] bg-gradient-to-br from-primary to-secondary flex items-center justify-center shadow-[0_0_30px_rgba(59,130,246,0.3)]">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="white">
              <path d="M4 6h16M4 10h16M4 14h8M4 18h6" stroke="white" strokeWidth="2" strokeLinecap="round" fill="none"/>
              <circle cx="18" cy="16" r="4" fill="none" stroke="white" strokeWidth="2"/>
              <path d="M18 14v4M16 16h4" stroke="white" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          </div>
          <div className="text-[20px] font-bold bg-gradient-to-r from-primary-light to-secondary-light bg-clip-text text-transparent">
            Video Store
          </div>

          {/* Spinner */}
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}
            className="w-7 h-7 border-2 border-border border-t-primary rounded-full"
          />
        </motion.div>
      </div>
    )
  }

  // ── Error screen ───────────────────────────────────────────────────────────
  // Protected-route guard: nothing below renders unless a verified session exists
  // (also covers logout / expiry where `error` may be empty).
  if (!isAuthenticated) {
    return (
      <div className="min-h-app bg-navy flex flex-col items-center justify-center px-6 text-center gap-4">
        <div className="text-4xl">⚠️</div>
        <h1 className="text-[16px] font-bold text-white">সংযোগ ব্যর্থ হয়েছে</h1>
        <p className="text-[13px] text-[#9CA3AF] leading-[1.6]">
          {error ?? 'Session পাওয়া যায়নি। আবার চেষ্টা করুন।'}
        </p>
        <button
          onClick={authenticate}
          className="px-6 py-3 rounded-[12px] bg-primary/15 border border-primary/30 text-primary text-[13px] font-semibold"
        >
          আবার চেষ্টা করুন
        </button>
      </div>
    )
  }

  // ── Maintenance mode ───────────────────────────────────────────────────────
  // handled by <AppShell> (components/layout) once the config has loaded

  return <>{children}</>
}
