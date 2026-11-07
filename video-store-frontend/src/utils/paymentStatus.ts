import type { ReviewCode, PaymentVerifyResult } from '@/types'

// Pure helpers for the Binance payment screens (no React, no network).
// Everything here only TRANSLATES what the Backend reported into Bengali copy or
// does cheap input validation. None of it decides that a payment succeeded.

// ─── Why is the payment waiting for an admin? (Backend `payment.review_code`) ─
export function reviewCopy(code: ReviewCode | string | null | undefined): { title: string; body: string } {
  switch (code) {
    case 'amount_mismatch':
      return { title: 'পরিমাণ মেলেনি — Admin দেখছেন', body: 'Binance-এ পাওয়া Payment-এর পরিমাণ বা মুদ্রা Order-এর সঙ্গে মেলেনি। Admin যাচাই করে সিদ্ধান্ত নেবেন; এর আগে Access চালু হবে না।' }
    case 'reference_mismatch':
      return { title: 'Reference মেলেনি — Admin দেখছেন', body: 'Binance-এর উত্তর এই Order-এর সঙ্গে সরাসরি মেলেনি, তাই Admin হাতে যাচাই করবেন।' }
    case 'manual_mode':
      return { title: 'Admin যাচাই চলছে', body: 'এই পদ্ধতির Payment Admin হাতে নিশ্চিত করেন। যাচাই শেষ হলে Access চালু হবে।' }
    case 'late_payment':
      return { title: 'দেরিতে আসা Payment — Admin দেখছেন', body: 'Order বন্ধ হওয়ার পরে Payment পাওয়া গেছে। Admin যাচাই করে সিদ্ধান্ত নেবেন।' }
    case 'user_submitted':
      return { title: 'Manual Review চলছে', body: 'আপনার জমা দেওয়া প্রমাণ Admin হাতে যাচাই করছেন। যাচাই শেষ হলে Notification আসবে এবং এই পেজ নিজে থেকেই আপডেট হবে।' }
    default:
      return { title: 'Manual Review চলছে', body: 'আপনার Payment Admin যাচাই করছেন। যাচাই শেষ হলে এই পেজ নিজে থেকেই আপডেট হবে।' }
  }
}

// ─── Result of POST /orders/:id/verify → what to tell the user ────────────────
export type NoteKind = 'success' | 'info' | 'error'

export function verifyNote(r: Pick<PaymentVerifyResult, 'outcome' | 'message'>): { kind: NoteKind; text: string } {
  switch (r.outcome) {
    case 'fulfilled': return { kind: 'success', text: r.message }
    case 'failed':    return { kind: 'error', text: r.message }
    case 'review':
    case 'wait':
    case 'manual':
    case 'noop':
    default:          return { kind: 'info', text: r.message }
  }
}

/** Seconds to wait after a 429 ("৩ সেকেন্ড পর আবার চেষ্টা করুন।"); never 0, never absurd. */
export function cooldownFromMessage(msg: string | undefined, fallback = 5): number {
  const m = /(\d{1,4})/.exec(msg ?? '')
  const n = m ? parseInt(m[1], 10) : fallback
  return Math.min(Math.max(n || fallback, 1), 120)
}

// ─── Transaction hash shape per network (mirror of the Backend rules) ─────────
// The Backend validates again (and is the only authority); this just saves a
// round trip for an impossible hash. Admin-defined / Binance ID methods accept a
// free-form reference.
const HEX64 = /^[0-9a-f]{64}$/
export const FREE_REF_RE = /^[A-Za-z0-9x]{8,128}$/

export function normalizeHash(methodType: string, raw: string): string {
  const h = raw.trim().toLowerCase()
  if ((methodType === 'usdt_bep20' || methodType === 'usdt_erc20') && HEX64.test(h)) return '0x' + h
  return h
}

/** Bengali message when the hash cannot be valid for the method; null = looks fine. */
export function hashProblem(methodType: string, raw: string): string | null {
  const h = normalizeHash(methodType, raw)
  if (!h) return null
  if (methodType === 'usdt_trc20') return HEX64.test(h) ? null : 'TRC20 Transaction Hash ৬৪ অক্ষরের হেক্স (0-9, a-f) হতে হবে।'
  if (methodType === 'usdt_bep20' || methodType === 'usdt_erc20') {
    return /^0x[0-9a-f]{64}$/.test(h) ? null : 'Transaction Hash 0x দিয়ে শুরু হওয়া ৬৪ অক্ষরের হেক্স হতে হবে।'
  }
  return FREE_REF_RE.test(h) ? null : 'কমপক্ষে ৮ অক্ষর; শুধু ইংরেজি অক্ষর ও সংখ্যা চলবে।'
}

// ─── Timeline labels (Backend `timeline[].step`) ──────────────────────────────
const STEP_LABEL: Record<string, string> = {
  created: 'Order তৈরি',
  under_review: 'যাচাইয়ে পাঠানো',
  verified: 'Payment যাচাই হয়েছে',
  rejected: 'Payment যাচাই হয়নি',
  expired: 'সময় শেষ',
  failed: 'Payment ব্যর্থ',
  completed: 'Access চালু',
}
export const stepLabel = (step: string): string => STEP_LABEL[step] ?? 'স্ট্যাটাস পরিবর্তন'

export const SOURCE_LABEL: Record<string, string> = {
  order: 'আপনি', user: 'আপনি', binance: 'Binance', admin: 'Admin', system: 'সিস্টেম',
}
