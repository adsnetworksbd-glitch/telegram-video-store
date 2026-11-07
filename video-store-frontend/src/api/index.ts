import type { AxiosResponse } from 'axios'
import api, { AUTH_TIMEOUT_MS, invalidResponseError } from './client'
import type {
  AppConfig, HomepageConfig, UserProfile,
  Video, VideoDetail, Category, Package, PackageDetail,
  AccessStatus, SourceAccess, Entitlement,
  Order, OrderStatus, PaymentMethod, OrderDetail, OrderCreateResult, PaymentVerifyResult,
  AdSession, CouponValidation,
  ReferralInfo, Referral, Transaction, Notification,
  PaginatedResponse,
} from '@/types'

// ─── Response guards ──────────────────────────────────────────────────────────
// A 2xx whose JSON does not have the fields a page dereferences (`items`,
// `sections`, `access`, …) would otherwise crash that page with a TypeError.
// `ok(...)` turns it into a normal rejected call ({ kind: 'invalid' }) that every
// page already shows as an error with a Retry button. Only fields the UI
// actually reads are checked — extra / optional fields are never required.
type Obj = Record<string, unknown>
const isObj = (d: unknown): d is Obj => typeof d === 'object' && d !== null && !Array.isArray(d)
const hasArray = (key: string) => (d: unknown) => isObj(d) && Array.isArray(d[key])
const isPage = hasArray('items')
const isAccessStatus = (d: unknown) => isObj(d) && typeof d.granted === 'boolean'
const isSourceAccess = (d: unknown) => isObj(d) && typeof d.source_type === 'string' && typeof d.redirect_url === 'string'
const isDetail = (d: unknown) => isObj(d) && typeof d.id === 'string' && isObj(d.access) && isObj(d.available_methods)

function ok<T>(check: (d: unknown) => boolean) {
  return (res: AxiosResponse<T>): AxiosResponse<T> => {
    if (!check(res.data)) throw invalidResponseError(res.status)
    return res
  }
}

// ─── Auth ─────────────────────────────────────────────────────────────────────
// A bot web_app button does not put the referral code into Telegram's initData; the
// bot appends it to the launch URL (?startapp=VS-XXXXXXX). It is only an attribution
// hint — the Backend still takes the user's identity from the verified initData.
const REFERRAL_CODE = /^VS-[A-Z0-9]{7}$/
function launchReferralCode(): string | undefined {
  try {
    const v = new URLSearchParams(window.location.search).get('startapp')
    return v && REFERRAL_CODE.test(v) ? v : undefined
  } catch {
    return undefined
  }
}

export const authApi = {
  login: (initData: string) =>
    api.post<{ access_token: string; user: UserProfile }>(
      '/auth/telegram', { init_data: initData, start_param: launchReferralCode() }, { timeout: AUTH_TIMEOUT_MS },
    ).then(ok((d) => isObj(d) && typeof d.access_token === 'string' && d.access_token !== '' && isObj(d.user))),

  refresh: (initData: string) =>
    api.post<{ access_token: string }>('/auth/refresh', { init_data: initData }),
}

// ─── Config ───────────────────────────────────────────────────────────────────
export const configApi = {
  getAppConfig: () =>
    api.get<AppConfig>('/config').then(ok((d) => isObj(d))),

  getHomepageConfig: () =>
    api.get<HomepageConfig>('/config/homepage').then(ok(hasArray('sections'))),
}

// ─── Videos ───────────────────────────────────────────────────────────────────
export const videosApi = {
  list: (params?: { category_id?: string; sort?: string; search?: string; page?: number; limit?: number }) =>
    api.get<PaginatedResponse<Video>>('/videos', { params }).then(ok(isPage)),

  detail: (id: string) =>
    api.get<VideoDetail>(`/videos/${encodeURIComponent(id)}`).then(ok(isDetail)),

  featured: () =>
    api.get<{ videos: Video[] }>('/videos/featured').then(ok(hasArray('videos'))),

  trending: () =>
    api.get<{ videos: Video[] }>('/videos/trending').then(ok(hasArray('videos'))),

  latest: () =>
    api.get<{ videos: Video[] }>('/videos/latest').then(ok(hasArray('videos'))),
}

// ─── Categories ───────────────────────────────────────────────────────────────
export const categoriesApi = {
  list: () =>
    api.get<{ categories: Category[] }>('/categories').then(ok(hasArray('categories'))),

  detail: (id: string) =>
    api.get<{ category: Category; videos: Video[]; total: number }>(`/categories/${encodeURIComponent(id)}`)
      .then(ok((d) => isObj(d) && isObj(d.category))),

  videos: (id: string, params?: { sort?: string; page?: number; limit?: number }) =>
    api.get<PaginatedResponse<Video>>(`/categories/${encodeURIComponent(id)}/videos`, { params }).then(ok(isPage)),
}

// ─── Packages ─────────────────────────────────────────────────────────────────
export const packagesApi = {
  list: (params?: { page?: number; limit?: number }) =>
    api.get<PaginatedResponse<Package>>('/packages', { params }).then(ok(isPage)),

  detail: (id: string) =>
    api.get<PackageDetail>(`/packages/${encodeURIComponent(id)}`)
      .then(ok((d) => isDetail(d) && (!isObj(d) || d.included_videos === undefined || Array.isArray(d.included_videos)))),

  featured: () =>
    api.get<{ packages: Package[] }>('/packages/featured').then(ok(hasArray('packages'))),
}

// ─── Access ───────────────────────────────────────────────────────────────────
export const accessApi = {
  checkVideo: (videoId: string) =>
    api.get<AccessStatus>(`/entitlements/check/video/${encodeURIComponent(videoId)}`).then(ok(isAccessStatus)),

  checkPackage: (packageId: string) =>
    api.get<AccessStatus>(`/entitlements/check/package/${encodeURIComponent(packageId)}`).then(ok(isAccessStatus)),

  getSource: (videoId: string) =>
    api.get<SourceAccess>(`/access/video/${encodeURIComponent(videoId)}/source`).then(ok(isSourceAccess)),
}

// ─── Entitlements ─────────────────────────────────────────────────────────────
export const entitlementsApi = {
  list: (params?: { status?: string; type?: string; page?: number; limit?: number }) =>
    api.get<PaginatedResponse<Entitlement>>('/entitlements', { params }).then(ok(isPage)),

  active: () =>
    api.get<PaginatedResponse<Entitlement>>('/entitlements', { params: { status: 'active' } }).then(ok(isPage)),
}

// ─── Orders ───────────────────────────────────────────────────────────────────
export const ordersApi = {
  create: (body: {
    content_type: 'video' | 'package'
    content_id: string
    payment_method_id: string
    coupon_code?: string
  }) =>
    api.post<OrderCreateResult>('/orders', body),

  detail: (id: string) =>
    api.get<OrderDetail>(`/orders/${encodeURIComponent(id)}`)
      .then(ok((d) => isObj(d) && isObj(d.order) && isObj(d.payment))),

  /** Binance Pay "check my payment": the Backend asks Binance; this never grants access by itself. */
  verify: (id: string) =>
    api.post<PaymentVerifyResult>(`/orders/${encodeURIComponent(id)}/verify`)
      .then(ok((d) => isObj(d) && typeof d.outcome === 'string')),

  /** Pay again after an expired / failed order: creates a NEW order (price recomputed by the Backend). */
  retry: (id: string, body: { payment_method_id?: string } = {}) =>
    api.post<OrderCreateResult>(`/orders/${encodeURIComponent(id)}/retry`, body)
      .then(ok((d) => isObj(d) && typeof d.order_id === 'string')),

  submit: (id: string, body: { transaction_hash?: string; screenshot_url?: string; user_note?: string }) =>
    api.post<{ status: OrderStatus; message: string }>(`/orders/${encodeURIComponent(id)}/submit`, body),

  history: (params?: { status?: string; page?: number; limit?: number }) =>
    api.get<PaginatedResponse<Order>>('/orders/history', { params }).then(ok(isPage)),
}

// ─── Payment Methods ──────────────────────────────────────────────────────────
export const paymentMethodsApi = {
  list: () =>
    api.get<{ methods: PaymentMethod[] }>('/payment-methods'),
}

// ─── Coupons ──────────────────────────────────────────────────────────────────
export const couponsApi = {
  validate: (body: { code: string; content_type: string; content_id: string; order_amount_bdt: number }) =>
    api.post<CouponValidation>('/coupons/validate', body),
}

// ─── Ads ──────────────────────────────────────────────────────────────────────
export const adsApi = {
  startSession: (body: { content_type: string; content_id: string }) =>
    api.post<AdSession>('/ads/session/start', body),

  checkSession: (sessionId: string, serverToken: string) =>
    api.post<AdSession>('/ads/session/complete', { session_id: sessionId, server_token: serverToken }),
}

// ─── Search ───────────────────────────────────────────────────────────────────
export const searchApi = {
  search: (q: string, params?: { type?: string; page?: number; limit?: number }) =>
    api.get<{ videos: Video[]; packages: Package[]; total: number }>('/search', { params: { q, ...params } })
      .then(ok((d) => hasArray('videos')(d) && hasArray('packages')(d))),
}

// ─── Referral ─────────────────────────────────────────────────────────────────
export const referralApi = {
  info: () =>
    api.get<ReferralInfo>('/referral/info'),

  history: (params?: { page?: number; limit?: number }) =>
    api.get<PaginatedResponse<Referral>>('/referral/history', { params }),
}

// ─── User ─────────────────────────────────────────────────────────────────────
export const userApi = {
  profile: () =>
    api.get<UserProfile>('/user/profile').then(ok((d) => isObj(d) && typeof d.telegram_id === 'string')),

  transactions: (params?: { type?: string; page?: number; limit?: number }) =>
    api.get<PaginatedResponse<Transaction>>('/user/transactions', { params }).then(ok(isPage)),

  notifications: (params?: { unread_only?: boolean; page?: number }) =>
    api.get<{ notifications: Notification[]; unread_count: number }>('/user/notifications', { params })
      .then(ok((d) => hasArray('notifications')(d) && typeof (d as Obj).unread_count === 'number')),

  markRead: (ids: string[] | 'all') =>
    api.post<{ updated: number }>('/user/notifications/read', { notification_ids: ids }),
}

// ─── Support ──────────────────────────────────────────────────────────────────
export const supportApi = {
  faq: () =>
    api.get<{ faqs: Array<{ id: string; question: string; answer: string }> }>('/support/faq').then(ok(hasArray('faqs'))),

  submitTicket: (body: { subject: string; message: string; category: string }) =>
    api.post<{ ticket_id: string }>('/support/ticket', body),
}
