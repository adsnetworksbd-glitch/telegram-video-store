import { adminClient } from '@/api/client'

// Admin configuration client (Phase 12 / Part 1B). Same adminClient (admin JWT, 401 handling in ./api.ts),
// same backend + Firestore as the Mini App. Every limit, default, enum and permission an admin form needs
// comes from GET /admin/config/schema — this file contains NO business value.

export type FieldType =
  | 'string' | 'text' | 'url' | 'int' | 'number' | 'bool' | 'enum' | 'enum_or_slug' | 'ref' | 'ref_list' | 'flags'

export interface FieldSpec {
  type: FieldType
  label: string
  required?: boolean
  default?: unknown
  min?: number
  max?: number
  min_exclusive?: number
  min_len?: number
  pattern?: string
  slug_pattern?: string
  options?: string[]
  keys?: string[]
  ref?: string
  https_only?: boolean
  write_only?: boolean
  help?: string
}

export interface ModuleSpec {
  label: string
  store: string
  permission: string
  can_view: boolean
  can_manage: boolean
  base_path: string
  fields: Record<string, FieldSpec>
  settings_fields?: Record<string, FieldSpec>
  extra_paths?: Record<string, string>
  choices?: Record<string, string[]>
  relations?: Array<{ field?: string; to?: string; used_by?: string; kind: 'one' | 'many' | 'reverse' }>
  derived?: string[]
  read_only?: string[]
}

export interface AdminSchema {
  version: string
  modules: Record<'videos' | 'packages' | 'ads' | 'payments' | 'coupons' | 'referral' | 'homepage' | 'settings' | 'notifications' | 'access'
    | 'dashboard' | 'orders' | 'users' | 'support' | 'audit' | 'categories' | 'admins', ModuleSpec>
}

export interface Page<T> { items: T[]; total: number; page: number; has_more: boolean }
export type AdminRecord = { id: string } & Record<string, unknown>
export type PendingPayment = { order_id: string } & Record<string, unknown>
export type TicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed'

export interface AdminDashboard {
  generated_at: string
  orders: {
    window_days: number; orders_in_window: number; orders_today: number; awaiting_review: number
    by_status: Record<string, number>; truncated: boolean
    revenue_bdt: { today: number; last_7_days: number; last_30_days: number }
  }
  users: { total: number | null; new_last_7_days: number | null; banned?: number | null }
  catalog: {
    videos_total: number | null; videos_published: number | null; packages_total: number | null; packages_published: number | null
    videos_hidden?: number | null; videos_featured?: number | null; videos_trending?: number | null
    categories_total?: number | null; categories_visible?: number | null
  }
  support: { open_tickets: number | null }      // null = count unavailable (show "—", not 0)
  // Role-gated: null when this role may not see the section, or it could not be loaded.
  top_videos?: AdminRecord[] | null
  recent_orders?: AdminRecord[] | null
  recent_activity?: AdminRecord[] | null
}

export interface AdminAccount {
  username: string; source: 'firestore' | 'env'; role: string; display_name: string | null; is_active: boolean | null
  is_locked: boolean; last_login_at: string | null; created_at: string | null; updated_at: string | null; created_by: string | null
}

export const adminConfigApi = {
  async schema(): Promise<AdminSchema> {
    return (await adminClient.get<AdminSchema>('/admin/config/schema')).data
  },

  // Generic list / get / save for the videos and packages modules (paths come from the schema).
  async list(basePath: string, params?: { q?: string; published?: boolean; active?: boolean; page?: number; limit?: number }) {
    return (await adminClient.get<Page<AdminRecord>>(basePath, { params })).data
  },
  async get(basePath: string, id: string) {
    return (await adminClient.get<AdminRecord>(`${basePath}/${encodeURIComponent(id)}`)).data
  },
  async create(basePath: string, body: Record<string, unknown>) {
    return (await adminClient.post<AdminRecord>(basePath, body)).data
  },
  async update(basePath: string, id: string, body: Record<string, unknown>) {
    return (await adminClient.put<AdminRecord>(`${basePath}/${encodeURIComponent(id)}`, body)).data
  },
  async setPublished(basePath: string, id: string, isPublished: boolean) {
    return (await adminClient.patch<AdminRecord>(`${basePath}/${encodeURIComponent(id)}/published`, { is_published: isPublished })).data
  },

  // Ads
  async adsOverview() {
    return (await adminClient.get('/admin/ads-config')).data
  },
  async listAdNetworks() {
    return (await adminClient.get('/admin/ad-networks')).data
  },
  async adNetworkVerification(id: string) {
    return (await adminClient.get(`/admin/ad-networks/${encodeURIComponent(id)}/verification`)).data
  },
  async saveAdNetwork(id: string, body: Record<string, unknown>) {
    return (await adminClient.put(`/admin/ad-networks/${encodeURIComponent(id)}`, body)).data
  },

  // Payments
  async paymentOverview() {
    return (await adminClient.get('/admin/payment-config')).data
  },
  async listPaymentMethods() {
    return (await adminClient.get('/admin/payment-methods')).data
  },
  async createPaymentMethod(body: Record<string, unknown>) {
    return (await adminClient.post('/admin/payment-methods', body)).data
  },
  async updatePaymentMethod(id: string, body: Record<string, unknown>) {
    return (await adminClient.put(`/admin/payment-methods/${encodeURIComponent(id)}`, body)).data
  },
  async setPaymentMethodEnabled(id: string, isEnabled: boolean) {
    return (await adminClient.patch(`/admin/payment-methods/${encodeURIComponent(id)}/enabled`, { is_enabled: isEnabled })).data
  },
  async expireStaleOrders() {
    return (await adminClient.post<{ scanned: number; expired: number }>('/admin/orders/expire-stale')).data
  },
  async savePaymentSettings(body: Record<string, number>) {
    return (await adminClient.put('/admin/payment-settings', body)).data
  },

  // ── Part 1C: coupons (list/get/create/update/setPublished-style helpers above work with base path
  //    `/admin/coupons`; activation uses PATCH …/active) ──
  async setCouponActive(id: string, isActive: boolean) {
    return (await adminClient.patch<AdminRecord>(`/admin/coupons/${encodeURIComponent(id)}/active`, { is_active: isActive })).data
  },
  async couponUsage(id: string, page = 1) {
    return (await adminClient.get<Page<AdminRecord>>(`/admin/coupons/${encodeURIComponent(id)}/usage`, { params: { page } })).data
  },

  // Referral
  async referralSettings() { return (await adminClient.get('/admin/referral-settings')).data },
  async saveReferralSettings(body: Record<string, unknown>) { return (await adminClient.put('/admin/referral-settings', body)).data },
  async referrals(params?: { status?: string; referrer_id?: string; page?: number }) {
    return (await adminClient.get<Page<AdminRecord>>('/admin/referrals', { params })).data
  },

  // Homepage (sections, banners, announcement) and global settings (maintenance, rate, links)
  async homepage() { return (await adminClient.get('/admin/homepage')).data },
  async saveHomepage(body: Record<string, unknown>) { return (await adminClient.put('/admin/homepage', body)).data },
  async appSettings() { return (await adminClient.get('/admin/app-settings')).data },
  async saveAppSettings(body: Record<string, unknown>) { return (await adminClient.put('/admin/app-settings', body)).data },

  // Notifications
  async notificationConfig() { return (await adminClient.get('/admin/notifications/config')).data },
  async sendNotification(body: Record<string, unknown>) {
    return (await adminClient.post<{ broadcast_id: string; recipients: number }>('/admin/notifications/send', body)).data
  },
  async userNotifications(userId: string, page = 1) {
    return (await adminClient.get<Page<AdminRecord>>('/admin/notifications', { params: { user_id: userId, page } })).data
  },

  // User access & expiry
  async userAccess(uid: string) { return (await adminClient.get(`/admin/users/${encodeURIComponent(uid)}/access`)).data },
  async grantAccess(body: Record<string, unknown>) { return (await adminClient.post('/admin/entitlements/grant', body)).data },
  async revokeAccess(entId: string, reason?: string) {
    return (await adminClient.post(`/admin/entitlements/${encodeURIComponent(entId)}/revoke`, { reason })).data
  },
  async extendAccess(entId: string, body: { hours?: number; lifetime?: boolean }) {
    return (await adminClient.post(`/admin/entitlements/${encodeURIComponent(entId)}/extend`, body)).data
  },
  async setBanned(uid: string, isBanned: boolean, reason?: string) {
    return (await adminClient.patch(`/admin/users/${encodeURIComponent(uid)}/banned`, { is_banned: isBanned, reason })).data
  },

  // ── Part 1D: dashboard, orders, users, support, audit log, categories, admin accounts ──
  async dashboard() { return (await adminClient.get<AdminDashboard>('/admin/dashboard')).data },

  async orders(params?: { status?: string; user_id?: string; content_type?: 'video' | 'package'; page?: number; limit?: number }) {
    return (await adminClient.get<Page<AdminRecord>>('/admin/orders', { params })).data
  },
  async order(id: string) { return (await adminClient.get<AdminRecord>(`/admin/orders/${encodeURIComponent(id)}`)).data },
  async transactions(params?: { user_id?: string; type?: string; direction?: 'credit' | 'debit'; page?: number; limit?: number }) {
    return (await adminClient.get<Page<AdminRecord>>('/admin/transactions', { params })).data
  },

  async users(params?: { q?: string; banned?: boolean; page?: number; limit?: number }) {
    return (await adminClient.get<Page<AdminRecord>>('/admin/users', { params })).data
  },
  async user(uid: string) { return (await adminClient.get<AdminRecord>(`/admin/users/${encodeURIComponent(uid)}`)).data },

  async tickets(params?: { status?: TicketStatus; user_id?: string; page?: number; limit?: number }) {
    return (await adminClient.get<Page<AdminRecord>>('/admin/support/tickets', { params })).data
  },
  async ticket(id: string) { return (await adminClient.get<AdminRecord>(`/admin/support/tickets/${encodeURIComponent(id)}`)).data },
  async replyTicket(id: string, reply: string, status?: TicketStatus) {
    return (await adminClient.post<AdminRecord>(`/admin/support/tickets/${encodeURIComponent(id)}/reply`, { reply, status })).data
  },
  async setTicketStatus(id: string, status: TicketStatus) {
    return (await adminClient.patch<AdminRecord>(`/admin/support/tickets/${encodeURIComponent(id)}/status`, { status })).data
  },
  async faqs() { return (await adminClient.get<{ items: AdminRecord[]; fields: Record<string, FieldSpec> }>('/admin/faqs')).data },
  async createFaq(body: Record<string, unknown>) { return (await adminClient.post<AdminRecord>('/admin/faqs', body)).data },
  async updateFaq(id: string, body: Record<string, unknown>) {
    return (await adminClient.put<AdminRecord>(`/admin/faqs/${encodeURIComponent(id)}`, body)).data
  },
  async deleteFaq(id: string) { return (await adminClient.delete<{ id: string; deleted: boolean }>(`/admin/faqs/${encodeURIComponent(id)}`)).data },

  async auditLogs(params?: { action?: string; performed_by?: string; target_type?: string; target_id?: string; since?: string; until?: string; page?: number; limit?: number }) {
    return (await adminClient.get<Page<AdminRecord> & { scan_cap: number }>('/admin/audit-logs', { params })).data
  },

  async categories() { return (await adminClient.get<{ items: AdminRecord[] }>('/admin/categories')).data },
  async category(id: string) { return (await adminClient.get<AdminRecord>(`/admin/categories/${encodeURIComponent(id)}`)).data },
  async createCategory(body: Record<string, unknown>) { return (await adminClient.post<AdminRecord>('/admin/categories', body)).data },
  async updateCategory(id: string, body: Record<string, unknown>) {
    return (await adminClient.put<AdminRecord>(`/admin/categories/${encodeURIComponent(id)}`, body)).data
  },
  async recountCategory(id: string) {
    return (await adminClient.post<{ id: string; video_count: number }>(`/admin/categories/${encodeURIComponent(id)}/recount`)).data
  },

  // ── Part 2C: payment review (admin.py). Approve / reject act only on orders in `under_review`;
  //    the server re-checks the state, so a double click can never grant access twice. ──
  async pendingPayments(page = 1) {
    return (await adminClient.get<Page<PendingPayment>>('/admin/payments/pending', { params: { page } })).data
  },
  async approvePayment(orderId: string, adminNote?: string) {
    return (await adminClient.post<{ status: string; entitlement_id?: string }>(`/admin/payments/${encodeURIComponent(orderId)}/approve`, { admin_note: adminNote || undefined })).data
  },
  async rejectPayment(orderId: string, adminNote?: string) {
    return (await adminClient.post<{ status: string }>(`/admin/payments/${encodeURIComponent(orderId)}/reject`, { admin_note: adminNote || undefined })).data
  },
  async reverifyPayment(orderId: string) {
    return (await adminClient.post<Record<string, unknown>>(`/admin/payments/${encodeURIComponent(orderId)}/reverify`)).data
  },

  async admins() { return (await adminClient.get<{ items: AdminAccount[]; fields: Record<string, FieldSpec>; roles: string[] }>('/admin/admins')).data },
  async createAdmin(body: { username: string; role: string; password: string; display_name?: string }) {
    return (await adminClient.post<AdminAccount>('/admin/admins', body)).data
  },
  async updateAdmin(username: string, body: { role?: string; display_name?: string; is_active?: boolean }) {
    return (await adminClient.put<AdminAccount>(`/admin/admins/${encodeURIComponent(username)}`, body)).data
  },
  async resetAdminPassword(username: string, password: string) {
    return (await adminClient.post<{ username: string; password_reset: boolean }>(`/admin/admins/${encodeURIComponent(username)}/password`, { password })).data
  },
}
