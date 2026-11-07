import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore, resetSession } from '@/store'

// ── Base URL ─────────────────────────────────────────────────────────────────
// VITE_API_URL must be set for production builds. There is deliberately NO
// hard-coded production fallback: the JWT is sent with every request, so a
// guessed domain would hand credentials to a host the owner may not control.
// Dev falls back to the local FastAPI server (uvicorn default port).
const RAW_API_URL = (import.meta.env.VITE_API_URL ?? '').trim().replace(/\/+$/, '')
const PLACEHOLDER_URL = /your-backend|your-frontend|your-domain|example\.(com|org)/i

export const API_BASE_URL: string =
  RAW_API_URL || (import.meta.env.DEV ? 'http://localhost:8000/api/v1' : '')

/** Non-null when the build is missing a usable API URL (shown by the Auth gate). */
export const apiConfigProblem: string | null =
  !API_BASE_URL
    ? 'API ঠিকানা সেট করা নেই (VITE_API_URL)। Deploy-এর Environment Variable যাচাই করুন।'
    : PLACEHOLDER_URL.test(API_BASE_URL)
      ? 'API ঠিকানা এখনো নমুনা মানে আছে (VITE_API_URL)। আসল Backend URL দিয়ে আবার Build করুন।'
      : null

const BASE_URL = API_BASE_URL

// Render's free tier sleeps when idle and needs ~30-60 s to wake, so the
// timeout is generous; auth calls get even more headroom (see api/index.ts).
export const DEFAULT_TIMEOUT_MS = 30000
export const AUTH_TIMEOUT_MS = 60000

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: DEFAULT_TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
})

// Admin Panel client (Phase 12). Kept here so this file stays the only place an HTTP
// client is created. Deliberately bare: NO Telegram refresh / session handling —
// its own auth + error interceptors live in src/admin/api.ts.
export const adminClient = axios.create({
  baseURL: BASE_URL,
  timeout: DEFAULT_TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
})

// ── Request interceptor: attach JWT ──────────────────────────────────────────
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── JWT refresh (single-flight) ──────────────────────────────────────────────
// The backend refresh endpoint re-verifies Telegram initData, so refresh uses
// the live initData from the Telegram WebApp object. A bare axios call is used
// (not apiClient) so a failing refresh cannot recurse into this interceptor.
//
// `transient` = the refresh failed for a reason that says nothing about the
// session (no connection, timeout, 5xx). The session is then kept and the
// original request fails with a connection message the user can retry,
// instead of being logged out by a network blip.
interface RefreshResult { token: string | null; transient: boolean }
let refreshPromise: Promise<RefreshResult> | null = null

async function refreshAccessToken(): Promise<RefreshResult> {
  const initData = window.Telegram?.WebApp?.initData
  if (!initData) return { token: null, transient: false }
  try {
    const res = await axios.post<{ access_token?: unknown }>(
      `${BASE_URL}/auth/refresh`,
      { init_data: initData },
      { timeout: AUTH_TIMEOUT_MS },
    )
    const token = res.data?.access_token
    if (typeof token !== 'string' || !token) return { token: null, transient: false }
    useAuthStore.getState().setToken(token)
    return { token, transient: false }
  } catch (e) {
    const status = axios.isAxiosError(e) ? e.response?.status : undefined
    return { token: null, transient: status === undefined || status >= 500 }
  }
}

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean; _netRetries?: number }

// ── Transient-failure retry (GET only) ───────────────────────────────────────
// Only idempotent reads are retried, only for "server not reachable yet"
// conditions (no response / timeout / 502-504). POSTs (orders, payments,
// ads) are never retried automatically — a repeat could double-submit.
const RETRY_DELAYS_MS = [1500, 3500]

function isTransient(error: AxiosError): boolean {
  if (axios.isCancel(error)) return false
  if (!error.response) return true
  const s = error.response.status
  return s === 502 || s === 503 || s === 504
}

// ── Error shape ──────────────────────────────────────────────────────────────
// Every rejection from apiClient is { status, message, kind }:
//   network  – no response (offline / DNS / CORS)      timeout – request timed out
//   invalid  – 2xx but the body is not what the app expects (HTML, empty, wrong shape)
//   session  – the login can no longer be used          http – any other server answer
export type ApiErrorKind = 'network' | 'timeout' | 'invalid' | 'session' | 'http'

export const INVALID_RESPONSE_MESSAGE = 'সার্ভার থেকে অপ্রত্যাশিত উত্তর এসেছে। কিছুক্ষণ পরে আবার চেষ্টা করুন।'
const SESSION_ENDED_MESSAGE = 'Session শেষ হয়েছে। App বন্ধ করে আবার খুলুন।'
const BANNED_MESSAGE = 'এই অ্যাকাউন্ট দিয়ে প্রবেশ করা যাচ্ছে না।'

/** Rejection value for a 2xx response whose body failed validation. */
export function invalidResponseError(status?: number) {
  return { status, message: INVALID_RESPONSE_MESSAGE, kind: 'invalid' as ApiErrorKind }
}

// ── Response interceptor: validate, refresh on 401, then clean errors ────────
apiClient.interceptors.response.use(
  (res) => {
    // Every endpoint answers with a JSON object. A string / empty body on a 2xx
    // is a captive portal, a proxy error page or a wrong VITE_API_URL — never
    // hand that to a page (it would crash on `.items` / `.map`).
    if (res.data === null || res.data === undefined || typeof res.data === 'string') {
      return Promise.reject(invalidResponseError(res.status))
    }
    return res
  },
  async (error: AxiosError) => {
    const status = error.response?.status
    const original = error.config as RetriableConfig | undefined
    const url = original?.url ?? ''
    const isAuthCall = url.startsWith('/auth/')

    if (original && (original.method ?? 'get').toLowerCase() === 'get' && isTransient(error)) {
      const attempt = original._netRetries ?? 0
      if (attempt < RETRY_DELAYS_MS.length) {
        original._netRetries = attempt + 1
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS_MS[attempt]))
        return apiClient(original)
      }
    }

    if (status === 401 && original && !isAuthCall) {
      if (!original._retried) {
        original._retried = true
        refreshPromise ??= refreshAccessToken().finally(() => { refreshPromise = null })
        const refreshed = await refreshPromise
        if (refreshed.token) {
          original.headers.Authorization = `Bearer ${refreshed.token}`
          return apiClient(original)
        }
        if (refreshed.transient) {
          // Could not reach the server to renew — keep the session, let the user retry.
          return Promise.reject({
            status: undefined,
            message: 'ইন্টারনেট সংযোগ পরীক্ষা করে আবার চেষ্টা করুন।',
            kind: 'network' as ApiErrorKind,
          })
        }
      }
      // No Telegram context / initData rejected, or a freshly issued token was
      // refused again: this session cannot be used any more.
      resetSession(SESSION_ENDED_MESSAGE)
      return Promise.reject({ status, message: SESSION_ENDED_MESSAGE, kind: 'session' as ApiErrorKind })
    }

    // Banned mid-session: every protected call now answers 403 "Account banned".
    if (status === 403 && original && !isAuthCall && responseDetail(error) === 'Account banned') {
      resetSession(BANNED_MESSAGE)
      return Promise.reject({ status, message: BANNED_MESSAGE, kind: 'session' as ApiErrorKind })
    }

    // Never leak server internals to UI — always return a clean, string message
    return Promise.reject({ status, message: extractErrorMessage(error), kind: errorKind(error) })
  },
)

// ── Error normalisation ──────────────────────────────────────────────────────
// FastAPI `detail` can be a string, an array (422 validation) or an object.
// The UI renders `message` directly, so it must always be a plain string.
const GENERIC_ERROR = 'কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করুন।'

function responseDetail(error: AxiosError): unknown {
  return (error.response?.data as { detail?: unknown } | undefined)?.detail
}

function errorKind(error: AxiosError): ApiErrorKind {
  if (!error.response) return error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT' ? 'timeout' : 'network'
  return 'http'
}

function extractErrorMessage(error: AxiosError): string {
  if (!error.response) {
    return error.code === 'ECONNABORTED'
      ? 'সংযোগে বেশি সময় লাগছে। আবার চেষ্টা করুন।'
      : 'ইন্টারনেট সংযোগ পরীক্ষা করে আবার চেষ্টা করুন।'
  }
  const detail = (error.response.data as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) return 'প্রদত্ত তথ্য সঠিক নয়।'
  if (detail && typeof detail === 'object') {
    const m = (detail as { message?: unknown }).message
    if (typeof m === 'string' && m.trim()) return m
  }
  return GENERIC_ERROR
}

/** HTTP status of a rejected API call (undefined for network / timeout). */
export function getErrorStatus(e: unknown): number | undefined {
  const s = (e as { status?: unknown } | null)?.status
  return typeof s === 'number' ? s : undefined
}

/**
 * The message to show when the problem is the connection itself (offline,
 * timeout, unexpected response, ended session) — those are the cases where the
 * page's generic "could not load X" text would hide the real, actionable cause.
 * Returns null for ordinary server answers so pages keep their own wording.
 */
export function connectionMessage(e: unknown): string | null {
  const kind = (e as { kind?: unknown } | null)?.kind
  if (kind === 'network' || kind === 'timeout' || kind === 'invalid' || kind === 'session') {
    return getErrorMessage(e)
  }
  return null
}

/** Safe message getter for `catch (e)` blocks in pages / services. */
export function getErrorMessage(e: unknown, fallback: string = GENERIC_ERROR): string {
  const m = (e as { message?: unknown } | null)?.message
  return typeof m === 'string' && m.trim() ? m : fallback
}

export default apiClient
