import { adminConfigApi, type AdminSchema } from './configApi'

/** Message of an AdminApiError (always already user-safe), with a generic fallback. */
export function errorText(e: unknown): string {
  const m = (e as { message?: unknown } | null)?.message
  return typeof m === 'string' && m ? m : 'কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করুন।'
}

// Firestore-backed records are loosely typed: read every value defensively.
export const str = (v: unknown): string => (typeof v === 'string' ? v : '')
export const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
export const bool = (v: unknown): boolean => v === true

export function fmtCount(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : v.toLocaleString('en-US')
}

export function fmtMoney(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `৳${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

export function fmtDateTime(v: unknown): string {
  if (typeof v !== 'string' || !v) return '—'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
}

export function fmtDuration(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

// The schema (limits, enums, defaults) is fetched once per page load and shared.
let schemaPromise: Promise<AdminSchema> | null = null
export function loadSchema(): Promise<AdminSchema> {
  if (!schemaPromise) {
    schemaPromise = adminConfigApi.schema().catch((e) => { schemaPromise = null; throw e })
  }
  return schemaPromise
}
