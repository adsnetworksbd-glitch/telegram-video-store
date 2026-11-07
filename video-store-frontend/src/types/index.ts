// ─── User ────────────────────────────────────────────────────────────────────
export interface TelegramUser {
  id: number
  first_name: string
  last_name?: string
  username?: string
  photo_url?: string
  language_code?: string
}

export interface UserProfile {
  telegram_id: string
  username: string | null
  first_name: string
  last_name: string | null
  photo_url: string | null
  referral_code: string
  referral_count: number
  referral_reward_total_bdt: number
  total_spent_bdt: number
  wallet_balance: number
  wallet_enabled: boolean
  is_banned: boolean
  created_at: string
  last_seen_at: string
}

// ─── App Config ───────────────────────────────────────────────────────────────
export interface HomepageSection {
  id: string
  label: string
  enabled: boolean
  order: number
}

export interface AppConfig {
  app_name: string
  app_logo_url: string | null
  maintenance_mode: boolean
  maintenance_message: string
  currency_display: string
  usdt_to_bdt_rate: number
  referral_enabled: boolean
  wallet_enabled: boolean
  homepage_announcement: string | null
  homepage_announcement_url: string | null
  // Optional, admin-controlled links. The current Backend AppConfig does not
  // send these yet — when absent the Support page shows them as "not set".
  terms_url?: string | null
  privacy_url?: string | null
  support_username?: string | null
  support_url?: string | null
}

export interface HomepageBanner {
  id: string
  title: string | null
  image_url: string
  link_type: 'none' | 'video' | 'package' | 'url'
  link_id: string | null
  link_url: string | null
  order: number
}

export interface HomepageConfig {
  sections: HomepageSection[]
  banners?: HomepageBanner[]   // additive (Phase 12 / 1C); the Home page does not render them yet
}

// ─── Video ───────────────────────────────────────────────────────────────────
export type VideoQuality = 'SD' | 'HD' | 'FHD' | '4K'
export type SourceType =
  | 'telegram_bot'
  | 'telegram_channel'
  | 'google_drive'
  | 'dropbox'
  | 'direct_mp4'
  | 'custom_url'

export interface Video {
  id: string
  title: string
  slug: string
  thumbnail_url: string
  category_ids: string[]
  primary_category_id: string
  quality: VideoQuality
  duration_seconds: number
  file_size_mb: number
  price_bdt: number
  is_free: boolean
  is_featured: boolean
  is_trending: boolean
  is_latest: boolean
  ads_unlock_enabled: boolean
  purchase_enabled: boolean
  ads_required: number
  ads_unlock_duration_hours: number
  purchase_duration_hours: number
  view_count: number
  purchase_count: number
  created_at: string
}

export interface VideoDetail extends Video {
  description: string
  source_type: SourceType
  access: AccessStatus
  available_methods: AvailableMethods
}

// ─── Category ─────────────────────────────────────────────────────────────────
export interface Category {
  id: string
  name: string
  slug: string
  thumbnail_url: string
  description: string | null
  video_count: number
  display_order: number
}

// ─── Package ─────────────────────────────────────────────────────────────────
export interface Package {
  id: string
  name: string
  thumbnail_url: string
  description: string
  video_ids: string[]
  video_count: number
  price_bdt: number
  original_price_bdt: number
  discount_percentage: number
  ads_unlock_enabled: boolean
  purchase_enabled: boolean
  duration_type: 'lifetime' | 'custom'
  duration_hours: number
  ads_required: number
  is_featured: boolean
  purchase_count: number
  created_at: string
}

export interface PackageDetail extends Package {
  included_videos: Video[]
  access: AccessStatus
  available_methods: AvailableMethods
}

// ─── Access ───────────────────────────────────────────────────────────────────
export type AccessSource = 'free' | 'ads_unlock' | 'individual_purchase' | 'package_purchase' | 'admin_grant'

export interface AccessStatus {
  granted: boolean
  source: AccessSource | null
  expires_at: string | null
  is_lifetime: boolean
  /** true when temporary access existed but has run out (Expired badge) */
  expired?: boolean
  /** every access source valid right now, best first (each is a separate Backend record) */
  active_sources?: AccessSource[]
}

export interface AvailableMethods {
  ads_unlock: boolean
  purchase: boolean
  is_free: boolean
}

export interface SourceAccess {
  source_type: SourceType
  redirect_url: string
}

// ─── Entitlement ─────────────────────────────────────────────────────────────
export type EntitlementStatus = 'active' | 'expired' | 'revoked'

export interface Entitlement {
  id: string
  user_id: string
  content_type: 'video' | 'package'
  content_id: string
  included_video_ids: string[]
  access_source: AccessSource
  order_id: string | null
  ad_unlock_session_id: string | null
  start_at: string
  expires_at: string | null
  is_lifetime: boolean
  status: EntitlementStatus
  created_at: string
  // Joined data for display
  video?: Video
  package?: Package
}

// ─── Order ───────────────────────────────────────────────────────────────────
export type OrderStatus =
  | 'pending'
  | 'awaiting_payment'
  | 'payment_submitted'
  | 'under_review'
  | 'completed'
  | 'failed'
  | 'refunded'
  | 'expired'

export interface Order {
  id: string
  user_id: string
  content_type: 'video' | 'package'
  content_id: string
  amount_bdt: number
  coupon_code: string | null
  discount_bdt: number
  final_bdt: number
  final_usdt: number
  usdt_rate_at_creation: number
  payment_method_id: string
  status: OrderStatus
  created_at: string
  expires_at: string
  completed_at: string | null
  currency: string
  payment_method_type?: string | null
}

// ─── Payment ─────────────────────────────────────────────────────────────────
// The Backend stores the method type as a free string (admin-created methods),
// so unknown values must stay representable. Known values get dedicated UI.
export type PaymentMethodType =
  | 'binance_pay' | 'binance_id' | 'usdt_trc20' | 'usdt_bep20' | 'usdt_erc20' | 'other'
  | (string & Record<never, never>)
export type VerificationStatus = 'pending' | 'verified' | 'failed'

export interface PaymentMethod {
  id: string
  name: string
  type: PaymentMethodType
  is_enabled: boolean
  display_order: number
  wallet_address: string | null
  network_name: string | null
  qr_code_url: string | null
  min_amount_usdt: number
  max_amount_usdt: number | null
  payment_timeout_minutes: number
  instructions_text: string
  auto_verification_supported: boolean
  // Phase 10 — set by the admin per method
  kind: 'gateway' | 'pay_id' | 'wallet' | 'custom' | (string & Record<never, never>)
  pay_id: string | null
  merchant_name: string | null
  currency: string
  manual_review_supported: boolean
}

export interface Payment {
  id: string
  order_id: string
  payment_method: PaymentMethodType
  expected_usdt: number
  paid_amount_usdt: number | null
  binance_checkout_url: string | null
  wallet_address: string | null
  network: string | null
  verification_method: 'binance_webhook' | 'manual'
  verification_status: VerificationStatus
  created_at: string
  // Phase 10 Part 2B (optional, user-safe — the Backend never sends admin notes/names)
  review_code?: ReviewCode | null
  attempts?: number
  last_checked_at?: string | null
  pay_id?: string | null
}

/** Why a payment waits for an admin (Backend coarse code). */
export type ReviewCode =
  | 'user_submitted' | 'amount_mismatch' | 'reference_mismatch' | 'manual_mode' | 'late_payment' | 'other'
  | (string & Record<never, never>)

export interface TimelineEvent {
  at: string
  /** created | under_review | verified | rejected | expired | failed | completed */
  step: string
  /** order | user | binance | admin | system */
  source: string
}

export interface RetryInfo {
  allowed: boolean
  /** null = the admin set no cap */
  remaining: number | null
}

/** GET /orders/:id */
export interface OrderDetail {
  order: Order
  payment: Payment
  details?: PaymentDetails | null
  timeline?: TimelineEvent[]
  retry?: RetryInfo
}

/** POST /orders and POST /orders/:id/retry */
export interface OrderCreateResult {
  order_id: string
  final_bdt: number
  final_usdt: number
  usdt_rate: number
  expires_at: string
  payment_details: PaymentDetails
}

/** POST /orders/:id/verify — the Backend's own answer, never a client claim. */
export type VerifyOutcome = 'fulfilled' | 'review' | 'failed' | 'wait' | 'noop' | 'manual' | (string & Record<never, never>)
export interface PaymentVerifyResult {
  status: OrderStatus
  outcome: VerifyOutcome
  message: string
  entitlement_id: string | null
}

export interface PaymentDetails {
  payment_id: string
  method: PaymentMethodType
  expected_usdt: number
  wallet_address: string | null
  network: string | null
  qr_code_url: string | null
  binance_checkout_url: string | null
  instructions_text: string
  expires_at: string
  // Phase 10 — everything the payment screen needs, decided by the Backend
  method_name: string
  currency: string
  pay_id: string | null
  merchant_name: string | null
  auto_verification_supported: boolean
  manual_review_supported: boolean
  /** true when the Backend returned an already-open identical order (no duplicate created) */
  reused: boolean
}

// ─── Ads ──────────────────────────────────────────────────────────────────────
export interface AdNetworkConfig {
  network_id: string
  zone_id: string | null
  type: string
  /** Phase 9 (optional, public only — never a secret) */
  provider_id?: string | null
  sdk_url?: string | null
}

export type AdSessionStatus = 'pending' | 'in_progress' | 'completed' | 'expired'
export type AdPlacement = 'video_unlock' | 'package_unlock' | 'rewarded' 

export interface AdSession {
  session_id: string
  server_token: string
  ads_required: number
  ads_completed: number
  s2s_verified_count?: number
  is_complete: boolean
  network_config: AdNetworkConfig
  expires_at: string
  entitlement_id: string | null
  /** Phase 9 (optional): Backend-derived session status */
  status?: AdSessionStatus | null
  placement?: AdPlacement | null
}

// ─── Coupon ───────────────────────────────────────────────────────────────────
export interface CouponValidation {
  valid: boolean
  discount_bdt: number
  final_bdt: number
  message: string
}

// ─── Referral ─────────────────────────────────────────────────────────────────
export interface ReferralInfo {
  referral_code: string
  referral_count: number
  reward_total_bdt: number
  referral_link: string
}

export interface Referral {
  id: string
  referred_user_id: string
  status: string
  reward_type: string
  reward_amount_bdt: number | null
  created_at: string
}

// ─── Transaction ──────────────────────────────────────────────────────────────
export type TransactionType = 'purchase' | 'refund' | 'referral_reward' | 'admin_adjustment' | 'deposit'

export interface Transaction {
  id: string
  type: TransactionType
  amount_bdt: number
  direction: 'credit' | 'debit'
  reference_type: string
  reference_id: string
  description: string
  created_at: string
}

// ─── Notification ────────────────────────────────────────────────────────────
export interface Notification {
  id: string
  type: string
  title: string
  body: string
  is_read: boolean
  action_type: string | null
  action_id: string | null
  created_at: string
}

// ─── Pagination ───────────────────────────────────────────────────────────────
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  has_more: boolean
}

// ─── API Error ────────────────────────────────────────────────────────────────
export interface ApiError {
  status: number
  message: string
  code?: string
}
