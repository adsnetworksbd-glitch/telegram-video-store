import { useCallback, useEffect, useRef, useState } from 'react'
import { ordersApi, paymentMethodsApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import type { Order, Payment, PaymentMethod, PaymentDetails, TimelineEvent, RetryInfo } from '@/types'

// ─── Order status → page ──────────────────────────────────────────────────────
// Pure mapping lives in utils/orderStage.ts (testable without React); re-exported
// here so every existing import keeps working.
export { stageOf, stagePath, contentPath, isPastDeadline } from '@/utils/orderStage'
export type { OrderStage } from '@/utils/orderStage'

// ─── Polling hook ─────────────────────────────────────────────────────────────
interface Options {
  /** Poll interval in ms; 0 = load once. */
  intervalMs?: number
  /** Stops polling once this returns true for the latest order. */
  stopWhen?: (o: Order) => boolean
}

/**
 * Loads GET /orders/:id (order + payment + admin-configured details) and optionally polls it. Polling
 * pauses while the page is hidden and refreshes immediately when the user
 * returns (e.g. back from the Binance checkout). Errors during polling keep the
 * last good data and raise `pollError` instead of wiping the screen.
 */
export function useOrder(orderId: string | undefined, { intervalMs = 0, stopWhen }: Options = {}) {
  const [order, setOrder] = useState<Order | null>(null)
  const [payment, setPayment] = useState<Payment | null>(null)
  const [details, setDetails] = useState<PaymentDetails | null>(null)
  const [timeline, setTimeline] = useState<TimelineEvent[]>([])
  const [retry, setRetry] = useState<RetryInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pollError, setPollError] = useState(false)

  const stopRef = useRef(stopWhen)
  stopRef.current = stopWhen
  const seq = useRef(0)
  const doneRef = useRef(false)

  const refresh = useCallback(async (): Promise<Order | null> => {
    if (!orderId) return null
    const mine = ++seq.current
    try {
      const res = await ordersApi.detail(orderId)
      if (mine !== seq.current) return null
      setOrder(res.data.order)
      setPayment(res.data.payment)
      // Phase 10 Part 2B: admin-configured screen data + safe timeline + retry info (all from the Backend)
      setDetails(res.data.details ?? null)
      setTimeline(res.data.timeline ?? [])
      setRetry(res.data.retry ?? null)
      setError(null)
      setPollError(false)
      if (stopRef.current?.(res.data.order)) doneRef.current = true
      return res.data.order
    } catch (e) {
      if (mine !== seq.current) return null
      // First load failure is fatal for the page; later ones are just a banner.
      setPollError(true)
      setError((prev) => prev ?? getErrorMessage(e, 'Order লোড করা যায়নি।'))
      return null
    } finally {
      if (mine === seq.current) setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    doneRef.current = false
    setLoading(true)
    setOrder(null); setPayment(null); setDetails(null); setTimeline([]); setRetry(null); setError(null)
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (!orderId || intervalMs <= 0) return
    const tick = () => {
      if (document.visibilityState === 'hidden' || doneRef.current) return
      void refresh()
    }
    const t = setInterval(tick, intervalMs)
    document.addEventListener('visibilitychange', tick)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', tick) }
  }, [orderId, intervalMs, refresh])

  // `error` is only meaningful while there is no order to show.
  return { order, payment, details, timeline, retry, loading, error: order ? null : error, pollError, refresh }
}

// ─── Payment method lookup (QR, instructions, limits) ─────────────────────────
// GET /orders/:id carries QR / instructions / Pay ID, but the amount LIMITS (and a
// fallback when `details` is missing) come from the public method list; they are
// admin-controlled fields of the payment method the order was created with.
export function usePaymentMethod(methodId: string | undefined) {
  const [method, setMethod] = useState<PaymentMethod | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!methodId) return
    let live = true
    paymentMethodsApi.list()
      .then((r) => { if (live) setMethod(r.data.methods.find((m) => m.id === methodId) ?? null) })
      .catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [methodId])

  return { method, failed }
}
