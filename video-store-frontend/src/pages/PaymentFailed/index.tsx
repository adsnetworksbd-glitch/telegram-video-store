import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ordersApi, paymentMethodsApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import type { PaymentMethod } from '@/types'
import { useOrder, stageOf, stagePath, contentPath } from '@/hooks/useOrder'
import { useVerifyPayment } from '@/hooks/useVerifyPayment'
import { SubHeader, PageWrapper } from '@/components/layout'
import { Spinner, ErrorState, toast } from '@/components/ui'
import { cx } from '@/utils'

// Failed / expired / refunded payment. The reason comes from the Backend order
// status. "Retry" calls POST /orders/:id/retry: the Backend creates a NEW order
// (new id, price and USDT amount recomputed, retry cap from admin settings) —
// an old order is never revived on the client. A Binance Pay order may still be
// paid late, so the user can ask the Backend to re-check it with Binance.

type Reason = 'expired' | 'rejected' | 'refunded' | 'timeout'

const COPY: Record<Reason, { title: string; body: string }> = {
  expired:  { title: 'Payment-এর সময় শেষ',   body: 'নির্ধারিত সময়ের মধ্যে Payment যাচাই হয়নি, তাই Order বাতিল হয়েছে।' },
  timeout:  { title: 'Payment-এর সময় শেষ',   body: 'নির্ধারিত সময় পেরিয়ে গেছে। যদি সময়ের মধ্যে পরিশোধ করে থাকেন, নিচের Order ID সহ Support-এ জানান।' },
  rejected: { title: 'Payment যাচাই হয়নি',    body: 'আপনার Payment যাচাই করা যায়নি বা বাতিল হয়েছে। Hash/পরিমাণ/Network ঠিক ছিল কিনা দেখে আবার চেষ্টা করুন, নইলে Support-এ জানান।' },
  refunded: { title: 'Payment ফেরত দেওয়া হয়েছে', body: 'এই Order-এর Payment ফেরত দেওয়া হয়েছে। চাইলে নতুন করে কিনতে পারেন।' },
}

export default function PaymentFailedPage() {
  const { orderId } = useParams<{ orderId: string }>()
  const navigate = useNavigate()
  const { order, payment, retry, loading, error, refresh } = useOrder(orderId)
  const { check, checking, cooldown, note } = useVerifyPayment(orderId, { onSettled: () => { void refresh() } })

  const [methods, setMethods] = useState<PaymentMethod[]>([])
  const [methodsError, setMethodsError] = useState(false)
  const [selected, setSelected] = useState('')
  const [retrying, setRetrying] = useState(false)
  const retryBusy = useRef(false)   // double-tap guard: one retry request at a time

  // Never show "failed" for an order the Backend says is paid / in review.
  useEffect(() => {
    if (!order || !orderId) return
    const stage = stageOf(order)
    if (stage === 'success' || stage === 'pending') navigate(stagePath(orderId, stage), { replace: true })
  }, [order, orderId, navigate])

  // Methods the admin currently offers (for "pay with another method").
  const canRetry = retry?.allowed === true && order?.status !== 'refunded'
  useEffect(() => {
    if (!canRetry) return
    let live = true
    paymentMethodsApi.list()
      .then((r) => {
        if (!live) return
        const list = r.data.methods.filter((m) => m.is_enabled !== false)
        setMethods(list)
        setSelected((cur) => (list.some((m) => m.id === cur) ? cur : (list.find((m) => m.id === order?.payment_method_id) ?? list[0])?.id ?? ''))
      })
      .catch(() => { if (live) setMethodsError(true) })
    return () => { live = false }
  }, [canRetry, order?.payment_method_id])

  async function startRetry() {
    if (!orderId || retryBusy.current) return
    retryBusy.current = true
    setRetrying(true)
    try {
      const res = await ordersApi.retry(orderId, selected ? { payment_method_id: selected } : {})
      if (res.data.payment_details?.reused) toast('আপনার আগের Order এখনো চালু আছে।', 'info')
      navigate(`/payment/${res.data.order_id}`, { replace: true })
    } catch (e) {
      const status = (e as { status?: number } | null)?.status
      const msg = getErrorMessage(e, 'নতুন Order তৈরি করা যায়নি।')
      if (status === 409 && /active access/i.test(msg)) {
        toast('এতে আগে থেকেই Access আছে।', 'info')
        if (order) navigate(contentPath(order), { replace: true })
      } else if (status === 409) {
        void refresh()                      // state changed (e.g. paid meanwhile) → follow the Backend
        toast('Order-এর অবস্থা বদলেছে — আবার দেখুন।', 'info')
      } else {
        toast(msg, 'error')                 // 429 limit, 503 Binance down, 400 amount limits …
      }
    } finally {
      retryBusy.current = false
      setRetrying(false)
    }
  }

  const goHome = () => navigate('/', { replace: true })
  const header = <SubHeader title="Payment ব্যর্থ" onBack={goHome} />

  if (loading) return <PageWrapper hasBottomNav={false}>{header}<div className="flex justify-center py-16"><Spinner size={32} /></div></PageWrapper>
  if (error || !order) return <PageWrapper hasBottomNav={false}>{header}<ErrorState message={error ?? 'Order পাওয়া যায়নি।'} onRetry={() => void refresh()} /></PageWrapper>

  const reason: Reason =
    order.status === 'refunded' ? 'refunded'
    : order.status === 'expired' ? 'expired'
    : order.status === 'failed' ? 'rejected'
    : 'timeout'   // still unpaid on the Backend but the deadline passed
  const copy = COPY[reason]
  const shortId = `#${order.id.slice(0, 12).toUpperCase()}`
  // A Binance Pay order can still be paid after it closed; the Backend re-checks with Binance and decides.
  const canRecheck = payment?.payment_method === 'binance_pay' && order.status !== 'refunded'
  const limitReached = retry !== null && !retry.allowed && retry.remaining === 0

  return (
    <PageWrapper hasBottomNav={false}>
      {header}
      <div className="flex flex-col items-center text-center px-6 pt-10 pb-6 space-y-4">
        <div className="w-20 h-20 rounded-full bg-danger/10 border-2 border-danger/30 flex items-center justify-center" aria-hidden>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#EF4444" strokeWidth="2.2" strokeLinecap="round">
            <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
          </svg>
        </div>
        <h1 className="text-[18px] font-bold text-white">{copy.title}</h1>
        <p className="text-[13px] text-[#9CA3AF] leading-[1.6]">{copy.body}</p>

        <button
          onClick={() => { navigator.clipboard?.writeText(order.id).then(() => toast('Order ID কপি হয়েছে', 'success')).catch(() => {}) }}
          className="text-[11px] font-mono text-[#9CA3AF] bg-card border border-border rounded-[8px] px-3 py-[6px]"
          aria-label="Order ID কপি করুন"
        >
          Order {shortId} · কপি
        </button>

        {/* Binance Pay: paid after the order closed? Ask the Backend to check with Binance. */}
        {canRecheck && (
          <div className="w-full space-y-2">
            <button onClick={() => void check()} disabled={checking || cooldown > 0} className="btn-ghost w-full disabled:opacity-60">
              {checking ? <Spinner size={18} /> : cooldown > 0 ? `আবার দেখা যাবে ${cooldown} সেকেন্ড পর` : '🔍 আমি পরিশোধ করেছি — Binance-এ যাচাই করুন'}
            </button>
            {note && (
              <p className={cx('text-[11px] leading-[1.5] rounded-[10px] px-3 py-2 border text-left', note.kind === 'error' ? 'text-[#FCA5A5] bg-danger/8 border-danger/20' : 'text-[#9CA3AF] bg-card border-border')} role="status">{note.text}</p>
            )}
          </div>
        )}

        {/* Retry → NEW order created by the Backend */}
        {canRetry && (
          <div className="w-full space-y-2 text-left">
            {methods.length > 1 && (
              <>
                <p className="text-[10px] text-[#6B7280] font-semibold uppercase tracking-[0.4px]">Payment পদ্ধতি</p>
                <div className="space-y-2">
                  {methods.map((m) => (
                    <button
                      key={m.id} type="button" onClick={() => setSelected(m.id)} aria-pressed={selected === m.id}
                      className={cx('w-full text-left flex items-center justify-between gap-3 bg-card border rounded-[10px] px-3 py-[10px]',
                        selected === m.id ? 'border-primary/50 bg-primary/7' : 'border-border')}
                    >
                      <span className="text-[12px] font-semibold text-white">{m.name}</span>
                      <span className="text-[10px] text-[#6B7280]">{m.auto_verification_supported ? 'Auto verify' : 'Manual review'}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
            {methodsError && <p className="text-[10px] text-[#6B7280]">অন্য পদ্ধতির তালিকা লোড হয়নি; আগের পদ্ধতিতেই নতুন Order হবে।</p>}
            <button onClick={() => void startRetry()} disabled={retrying} className="btn-primary w-full disabled:opacity-60">
              {retrying ? <Spinner size={18} /> : '🔄 আবার চেষ্টা করুন (নতুন Order)'}
            </button>
            {retry?.remaining != null && <p className="text-[10px] text-[#6B7280] text-center">আজ আর {retry.remaining}বার চেষ্টা করা যাবে</p>}
          </div>
        )}

        {limitReached && (
          <p className="w-full text-[12px] text-[#FCD34D] bg-warning/8 border border-warning/20 rounded-[10px] px-3 py-2">
            আজকের চেষ্টার সীমা শেষ। কিছুক্ষণ পর আবার চেষ্টা করুন বা Support-এ জানান।
          </p>
        )}
        {!canRetry && !limitReached && (
          <button onClick={() => navigate(`${contentPath(order)}/purchase`, { replace: true })} className="btn-primary w-full">
            🛒 নতুন করে কিনুন
          </button>
        )}

        <button onClick={() => navigate('/support')} className="btn-ghost w-full">Support-এ জানান</button>
        <button onClick={goHome} className="text-[12px] text-[#9CA3AF]">← হোমে ফিরে যান</button>
      </div>
    </PageWrapper>
  )
}
