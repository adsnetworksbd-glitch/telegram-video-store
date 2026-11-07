import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { adminClient, apiConfigProblem, AUTH_TIMEOUT_MS } from '@/api/client'
import { useAdminStore, type AdminProfile } from './store'

// adminClient is a separate instance from the Mini App's: that one refreshes 401s with
// Telegram initData, which must never happen for admin calls.

adminClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAdminStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export interface AdminApiError {
  status?: number
  message: string
  kind: 'network' | 'session' | 'forbidden' | 'http' | 'invalid'
}

const SESSION_ENDED = 'সেশন শেষ হয়েছে। আবার লগইন করুন।'

function messageFor(error: AxiosError, isLogin: boolean): string {
  const status = error.response?.status
  if (!error.response) {
    return error.code === 'ECONNABORTED'
      ? 'সংযোগে বেশি সময় লাগছে। আবার চেষ্টা করুন।'
      : 'ইন্টারনেট সংযোগ পরীক্ষা করে আবার চেষ্টা করুন।'
  }
  if (isLogin) {
    if (status === 401) return 'ইউজারনেম বা পাসওয়ার্ড ভুল।'
    if (status === 403) return 'এই Admin অ্যাকাউন্টটি বন্ধ করা আছে।'
    if (status === 429) {
      const secs = Number(error.response.headers?.['retry-after'])
      const mins = Number.isFinite(secs) && secs > 0 ? Math.ceil(secs / 60) : null
      return mins
        ? `অনেকবার ভুল চেষ্টা হয়েছে। প্রায় ${mins} মিনিট পরে আবার চেষ্টা করুন।`
        : 'অনেকবার ভুল চেষ্টা হয়েছে। কিছুক্ষণ পরে আবার চেষ্টা করুন।'
    }
    if (status === 422) return 'ইউজারনেম ও পাসওয়ার্ড দিন।'
  }
  if (status === 403) return 'এই কাজের অনুমতি আপনার নেই।'
  // Forms need the server's own reason (e.g. "a purchasable, non-free video needs price_bdt > 0").
  // Only plain-string `detail` of client-fixable statuses is shown; nothing else leaks through.
  if (status === 404 || status === 409 || status === 422 || status === 503) {
    const detail = (error.response.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string' && detail.trim()) return detail.slice(0, 300)
  }
  return 'কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করুন।'
}

adminClient.interceptors.response.use(
  (res) => {
    if (res.data === null || res.data === undefined || typeof res.data === 'string') {
      return Promise.reject({ status: res.status, message: 'সার্ভার থেকে অপ্রত্যাশিত উত্তর এসেছে।', kind: 'invalid' } as AdminApiError)
    }
    return res
  },
  (error: AxiosError) => {
    const status = error.response?.status
    const isLogin = (error.config?.url ?? '') === '/admin/login'
    if (status === 401 && !isLogin) {
      useAdminStore.getState().clear()   // RequireAdmin sends the user to the login page
      return Promise.reject({ status, message: SESSION_ENDED, kind: 'session' } as AdminApiError)
    }
    const kind: AdminApiError['kind'] = !error.response ? 'network' : status === 403 ? 'forbidden' : 'http'
    return Promise.reject({ status, message: messageFor(error, isLogin), kind } as AdminApiError)
  },
)

function isProfile(a: unknown): a is AdminProfile {
  const p = a as Partial<AdminProfile> | null
  return !!p && typeof p.username === 'string' && typeof p.role === 'string' && Array.isArray(p.permissions)
}

export interface AdminLoginResult { token: string; expiresIn: number; admin: AdminProfile }

export const adminApi = {
  async login(username: string, password: string): Promise<AdminLoginResult> {
    if (apiConfigProblem) throw { message: apiConfigProblem, kind: 'invalid' } as AdminApiError
    const { data } = await adminClient.post<{ access_token?: unknown; expires_in?: unknown; admin?: unknown }>(
      '/admin/login', { username, password }, { timeout: AUTH_TIMEOUT_MS },
    )
    if (typeof data.access_token !== 'string' || !data.access_token || !isProfile(data.admin)) {
      throw { message: 'সার্ভার থেকে অপ্রত্যাশিত উত্তর এসেছে।', kind: 'invalid' } as AdminApiError
    }
    return {
      token: data.access_token,
      expiresIn: typeof data.expires_in === 'number' ? data.expires_in : 3600,
      admin: data.admin,
    }
  },

  /** Re-validates the session and returns the live role / permissions. */
  async me(): Promise<AdminProfile> {
    const { data } = await adminClient.get<{ admin?: unknown }>('/admin/me')
    if (!isProfile(data.admin)) {
      throw { message: 'সার্ভার থেকে অপ্রত্যাশিত উত্তর এসেছে।', kind: 'invalid' } as AdminApiError
    }
    return data.admin
  },
}
