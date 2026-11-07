import type { VideoQuality } from '@/types'

// ─── Currency ─────────────────────────────────────────────────────────────────

export function formatBDT(amount: number): string {
  return `৳${amount.toLocaleString('bn-BD')}`
}

export function formatUSDT(amount: number): string {
  return `${amount.toFixed(2)} USDT`
}

/**
 * Exact amount to send (up to 8 decimals, trailing zeros trimmed). The Backend
 * stores `final_usdt` with 8-decimal precision, and a transfer is matched
 * against it — rounding to 2 decimals on the payment screen would mislead.
 */
export function formatUsdtExact(amount: number): string {
  const s = amount.toFixed(8).replace(/0+$/, '').replace(/\.$/, '')
  return s.includes('.') ? s : `${s}.00`
}

export function bdtToUsdt(bdt: number, rate: number): number {
  if (!rate || rate === 0) return 0
  return Math.round((bdt / rate) * 100) / 100
}

// ─── Duration ─────────────────────────────────────────────────────────────────

export function formatDuration(seconds: number): string {
  if (seconds <= 0) return '০:০০'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }
  return `${m}:${String(s).padStart(2, '0')}`
}

export function formatDurationLong(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0 && m > 0) return `${h} ঘণ্টা ${m} মিনিট`
  if (h > 0) return `${h} ঘণ্টা`
  if (m > 0) return `${m} মিনিট`
  return `${seconds} সেকেন্ড`
}

// ─── File size ────────────────────────────────────────────────────────────────

export function formatFileSize(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${Math.round(mb)} MB`
}

// ─── Date ─────────────────────────────────────────────────────────────────────

const BN_MONTHS = [
  'জানুয়ারি', 'ফেব্রুয়ারি', 'মার্চ', 'এপ্রিল',
  'মে', 'জুন', 'জুলাই', 'আগস্ট',
  'সেপ্টেম্বর', 'অক্টোবর', 'নভেম্বর', 'ডিসেম্বর',
]

export function formatDate(iso: string): string {
  const d = new Date(iso)
  return `${d.getDate()} ${BN_MONTHS[d.getMonth()]} ${d.getFullYear()}`
}

export function formatTimeLeft(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now()
  if (diff <= 0) return 'মেয়াদ শেষ'
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  if (h >= 24) {
    const d = Math.floor(h / 24)
    return `${d} দিন বাকি`
  }
  if (h > 0) return `${h} ঘণ্টা ${m} মিনিট বাকি`
  return `${m} মিনিট বাকি`
}

export function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

// ─── Access Duration ──────────────────────────────────────────────────────────

export function formatAccessDuration(hours: number): string {
  if (hours === 0) return 'Lifetime Access'
  if (hours < 24) return `${hours} ঘণ্টা`
  const days = Math.floor(hours / 24)
  return `${days} দিন`
}

// ─── Source Handler ───────────────────────────────────────────────────────────
// Implementation lives in utils/sources.ts; re-exported here so existing
// imports (`import { handleSourceRedirect } from '@/utils'`) keep working.
export { handleSourceRedirect, getSourceInfo, SOURCE_INFO } from './sources'
export type { SourceInfo, SourceSupport } from './sources'

// ─── Quality color ────────────────────────────────────────────────────────────

export function qualityColor(q: VideoQuality): string {
  switch (q) {
    case '4K':  return 'bg-primary/85'
    case 'FHD': return 'bg-primary/85'
    case 'HD':  return 'bg-secondary/85'
    case 'SD':  return 'bg-success/80'
    default:    return 'bg-primary/85'
  }
}

// ─── Truncate ─────────────────────────────────────────────────────────────────

export function truncate(str: string, max: number): string {
  if (str.length <= max) return str
  return str.slice(0, max) + '...'
}

// ─── Class merge (simple) ─────────────────────────────────────────────────────

export function cx(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ')
}


// ─── Client-side preferences (Settings) ───────────────────────────────────────
// Per-device convenience only; storage can be blocked, so every access is guarded.
const HAPTIC_KEY = 'vs:haptic'

export function isHapticEnabled(): boolean {
  try { return localStorage.getItem(HAPTIC_KEY) !== 'off' } catch { return true }
}

export function setHapticEnabled(on: boolean): void {
  try { localStorage.setItem(HAPTIC_KEY, on ? 'on' : 'off') } catch { /* ignore */ }
}
