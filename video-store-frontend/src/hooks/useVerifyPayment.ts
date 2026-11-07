import { useCallback, useEffect, useRef, useState } from 'react'
import { ordersApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import type { PaymentVerifyResult } from '@/types'
import { cooldownFromMessage, verifyNote, type NoteKind } from '@/utils/paymentStatus'

// "Check my payment" for Binance Pay orders (POST /orders/:id/verify).
//
// The Backend asks Binance's signed API and decides; this hook only calls it,
// respects the Backend throttle (HTTP 429 → cooldown) and reports what the
// Backend answered. A result never changes the screen by itself: callers
// re-read the order (`onSettled` → refresh) and the screen follows its status.

const DEFAULT_COOLDOWN_S = 5

export interface VerifyNote { kind: NoteKind; text: string }

interface Options {
  /** Called after every attempt that reached the Backend (also 429/503), so the page re-reads the order. */
  onSettled?: (r: PaymentVerifyResult | null) => void
}

export function useVerifyPayment(orderId: string | undefined, { onSettled }: Options = {}) {
  const [checking, setChecking] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const [note, setNote] = useState<VerifyNote | null>(null)
  const busy = useRef(false)          // blocks double taps / overlapping auto checks
  const alive = useRef(true)
  const settledRef = useRef(onSettled)
  settledRef.current = onSettled

  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  useEffect(() => {
    if (cooldown <= 0) return
    const t = setTimeout(() => setCooldown((c) => Math.max(0, c - 1)), 1000)
    return () => clearTimeout(t)
  }, [cooldown])

  /**
   * `silent` = automatic background check: errors / throttling are not shown.
   * Resolves with the Backend's answer, or null when none was obtained.
   */
  const check = useCallback(async (opts: { silent?: boolean } = {}): Promise<PaymentVerifyResult | null> => {
    if (!orderId || busy.current) return null
    busy.current = true
    if (alive.current) setChecking(true)
    let result: PaymentVerifyResult | null = null
    try {
      const res = await ordersApi.verify(orderId)
      const answer: PaymentVerifyResult = res.data
      result = answer
      if (alive.current) {
        setCooldown(DEFAULT_COOLDOWN_S)
        if (!opts.silent || answer.outcome === 'fulfilled' || answer.outcome === 'review') setNote(verifyNote(answer))
      }
    } catch (e) {
      const status = (e as { status?: number } | null)?.status
      const msg = getErrorMessage(e, 'যাচাই করা যায়নি।')
      if (alive.current) {
        if (status === 429) setCooldown(cooldownFromMessage(msg, DEFAULT_COOLDOWN_S))
        if (!opts.silent) setNote({ kind: status === 429 ? 'info' : 'error', text: msg })
      }
    } finally {
      busy.current = false
      if (alive.current) setChecking(false)
      settledRef.current?.(result)
    }
    return result
  }, [orderId])

  return { check, checking, cooldown, note, clearNote: () => setNote(null) }
}

/**
 * Background checks while `enabled`: every `intervalMs` (paused while the page is
 * hidden) and once whenever the user comes back to the app (e.g. from the Binance
 * checkout). The Backend throttle bounds the real Binance traffic.
 */
export function useAutoVerify(enabled: boolean, check: (o: { silent: boolean }) => unknown, intervalMs = 20000) {
  const checkRef = useRef(check)
  checkRef.current = check
  useEffect(() => {
    if (!enabled) return
    const run = () => { if (document.visibilityState !== 'hidden') void checkRef.current({ silent: true }) }
    const t = setInterval(run, intervalMs)
    document.addEventListener('visibilitychange', run)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', run) }
  }, [enabled, intervalMs])
}
