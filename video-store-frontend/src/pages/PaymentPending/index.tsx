import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useOrder, stageOf, stagePath, contentPath } from '@/hooks/useOrder'
import { useVerifyPayment, useAutoVerify } from '@/hooks/useVerifyPayment'
import { reviewCopy, stepLabel, SOURCE_LABEL } from '@/utils/paymentStatus'
import { SubHeader, PageWrapper } from '@/components/layout'
import { Countdown, Spinner, ErrorState, InlineError, toast } from '@/components/ui'
import { formatUsdtExact, formatDate } from '@/utils'
import { getTelegram } from '@/hooks/useTelegram'

// Payment verification status screen. Everything shown here is read from the
// Backend order/payment — the page never advances on its own:
//   under_review / payment_submitted  → manual (admin) review
//   awaiting_payment + Binance Pay    → waiting for the Binance webhook
//   completed → Success, failed/expired/refunded → Failed (automatic redirect)
// Binance Pay orders are also re-checked against Binance through the Backend
// (POST /orders/:id/verify, throttled) — the answer arrives as the order status.

const POLL_MS = 6000

export default function PaymentPendingPage() {
  const { orderId } = useParams<{ orderId: string }>()
  const navigate = useNavigate()
  const { order, payment, timeline, loading, error, pollError, refresh } = useOrder(orderId, { intervalMs: POLL_MS })
  const { check, checking, cooldown, note } = useVerifyPayment(orderId, { onSettled: () => { void refresh() } })
  const isBinanceOrder = payment?.payment_method === 'binance_pay'
  const waiting = order !== null && (order.status === 'awaiting_payment' || order.status === 'pending')
  // Automatic Binance re-check only while we are really waiting for Binance (not while an admin reviews).
  useAutoVerify(isBinanceOrder && waiting, check, 20000)

  useEffect(() => {
    if (!order || !orderId) return
    const stage = stageOf(order)
    if (stage === 'success' || stage === 'failed') {
      navigate(stagePath(orderId, stage), { replace: true })
    } else if (stage === 'pay' && payment && payment.payment_method !== 'binance_pay') {
      // Manual method that was never submitted → back to the payment screen.
      navigate(stagePath(orderId, 'pay'), { replace: true })
    }
  }, [order, payment, orderId, navigate])

  const goHome = () => navigate('/', { replace: true })
  const header = <SubHeader title="Payment যাচাই" onBack={goHome} />

  if (loading) return <PageWrapper hasBottomNav={false}>{header}<div className="flex justify-center py-16"><Spinner size={32} /></div></PageWrapper>
  if (error || !order || !payment) {
    return <PageWrapper hasBottomNav={false}>{header}<ErrorState message={error ?? 'Order পাওয়া যায়নি।'} onRetry={() => void refresh()} /></PageWrapper>
  }

  const isBinancePay = payment.payment_method === 'binance_pay'
  const inReview = order.status === 'under_review' || order.status === 'payment_submitted'
  // Awaiting Binance's automatic confirmation (no manual submission yet).
  const waitingBinance = isBinancePay && !inReview

  const review = reviewCopy(payment.review_code)
  const headline = waitingBinance ? 'Binance-এর নিশ্চিতকরণের অপেক্ষা' : review.title
  const lead = waitingBinance
    ? 'পরিশোধ হয়ে থাকলে Binance আমাদের Server-কে জানাবে; Server যাচাই করলেই Access চালু হবে। সাধারণত কয়েক মিনিট লাগে।'
    : review.body

  // Stepper — each step is derived from Backend state, not from timers.
  const steps = [
    { label: isBinancePay && !inReview ? 'Binance-এ পরিশোধ' : 'Payment জমা', done: true },
    { label: waitingBinance ? 'Binance নিশ্চিতকরণ' : 'Admin যাচাই', done: false, active: true },
    { label: 'Access চালু', done: false },
  ]

  return (
    <PageWrapper hasBottomNav={false}>
      {header}
      <div className="flex flex-col items-center text-center px-6 pt-8 pb-6 space-y-4">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ repeat: Infinity, duration: 2, ease: 'linear' }}
          className="w-20 h-20 rounded-full border-4 border-warning/30 border-t-warning"
          aria-hidden
        />
        <h1 className="text-[18px] font-bold text-white">{headline}</h1>
        <p className="text-[13px] text-[#9CA3AF] leading-[1.6]">{lead}</p>

        {pollError && <div className="w-full"><InlineError message="সংযোগ সমস্যা — আবার চেষ্টা করা হচ্ছে।" onRetry={() => void refresh()} /></div>}

        {/* Steps */}
        <ol className="w-full flex items-start justify-between gap-2" aria-label="যাচাইয়ের ধাপ">
          {steps.map((s, i) => (
            <li key={s.label} className="flex-1 flex flex-col items-center gap-1">
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold border ${
                s.done ? 'bg-success/15 border-success/40 text-[#6EE7B7]'
                : s.active ? 'bg-warning/15 border-warning/40 text-[#FCD34D]'
                : 'bg-card border-border text-[#6B7280]'}`}>
                {s.done ? '✓' : i + 1}
              </span>
              <span className="text-[10px] text-[#9CA3AF] leading-[1.3]">{s.label}</span>
            </li>
          ))}
        </ol>

        {/* Facts */}
        <div className="w-full bg-card border border-border rounded-[12px] overflow-hidden text-left">
          {[
            { k: 'Order ID', v: `#${order.id.slice(0, 12).toUpperCase()}` },
            { k: 'পরিমাণ', v: `${formatUsdtExact(order.final_usdt)} USDT` },
            { k: 'তৈরি', v: formatDate(order.created_at) },
            { k: 'যাচাই পদ্ধতি', v: payment.verification_method === 'binance_webhook' ? 'Binance স্বয়ংক্রিয়' : 'Admin (Manual)' },
          ].map((r, i, a) => (
            <div key={r.k} className={`flex justify-between px-3 py-[9px] ${i < a.length - 1 ? 'border-b border-border' : ''}`}>
              <span className="text-[11px] text-[#6B7280]">{r.k}</span>
              <span className="text-[11px] font-semibold text-white">{r.v}</span>
            </div>
          ))}
          {waitingBinance && (
            <div className="flex justify-between px-3 py-[9px] border-t border-border">
              <span className="text-[11px] text-[#6B7280]">Payment-এর সময় বাকি</span>
              <Countdown expiresAt={order.expires_at} onExpire={() => void refresh()} className="text-[11px] text-warning" />
            </div>
          )}
        </div>

        <div className="w-full bg-warning/8 border border-warning/20 rounded-[12px] p-4 text-left">
          <p className="text-[12px] text-[#FCD34D] font-semibold mb-2">⏳ কী করবেন:</p>
          <ul className="space-y-1">
            {[
              'App বন্ধ করতে পারেন — যাচাই চলতে থাকবে',
              'যাচাই হলে Notification পাবেন; ভিডিও "আমার Purchases"-এ থাকবে',
              ...(waitingBinance ? ['এখনো পরিশোধ না করে থাকলে নিচের বোতামে Payment পেজে ফিরুন'] : []),
              'অনেক দেরি হলে Order ID সহ Support-এ জানান',
            ].map((t) => <li key={t} className="text-[11px] text-[#FCD34D]/80">• {t}</li>)}
          </ul>
        </div>

        {/* Verification timeline (Backend, user-safe: no admin names or notes) */}
        {timeline.length > 0 && (
          <div className="w-full bg-card border border-border rounded-[12px] p-3 text-left">
            <p className="text-[10px] text-[#6B7280] font-semibold uppercase tracking-[0.4px] mb-2">যাচাইয়ের ইতিহাস</p>
            <ul className="space-y-[6px]">
              {timeline.map((e, i) => (
                <li key={`${e.at}-${i}`} className="flex justify-between gap-3 text-[11px]">
                  <span className="text-white">{stepLabel(e.step)} <span className="text-[#6B7280]">· {SOURCE_LABEL[e.source] ?? 'সিস্টেম'}</span></span>
                  <span className="text-[#6B7280] flex-shrink-0">{formatDate(e.at)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Binance Pay: ask the Backend to re-check with Binance (never grants access by itself) */}
        {waitingBinance && (
          <>
            <button
              onClick={() => void check()}
              disabled={checking || cooldown > 0}
              className="btn-primary w-full disabled:opacity-60"
            >
              {checking ? <Spinner size={18} /> : cooldown > 0 ? `আবার দেখা যাবে ${cooldown} সেকেন্ড পর` : '🔍 Binance-এ Payment যাচাই করুন'}
            </button>
            {note && (
              <p className={`w-full text-[11px] leading-[1.5] rounded-[10px] px-3 py-2 border ${note.kind === 'error' ? 'text-[#FCA5A5] bg-danger/8 border-danger/20' : 'text-[#9CA3AF] bg-card border-border'}`} role="status">{note.text}</p>
            )}
          </>
        )}

        <button onClick={() => void refresh().then(() => toast('স্ট্যাটাস হালনাগাদ হয়েছে', 'info'))} className="btn-ghost w-full">🔄 স্ট্যাটাস রিফ্রেশ করুন</button>

        {waitingBinance && payment.binance_checkout_url && (
          <button
            onClick={() => {
              const tg = getTelegram(); const u = payment.binance_checkout_url!
              if (!/^https:\/\//i.test(u)) return
              if (tg?.initData && typeof tg.openLink === 'function') tg.openLink(u); else window.open(u, '_blank', 'noopener,noreferrer')
            }}
            className="w-full text-[12px] text-primary font-medium"
          >Binance Checkout আবার খুলুন</button>
        )}
        {waitingBinance && (
          <button onClick={() => navigate(stagePath(order.id, 'pay'), { replace: true })} className="w-full text-[12px] text-primary font-medium">Payment পেজে ফিরুন (Manual Review-এ পাঠাতে)</button>
        )}
        <button onClick={() => navigate(contentPath(order))} className="btn-ghost w-full">কনটেন্টে ফিরে যান</button>
        <button onClick={goHome} className="text-[12px] text-[#9CA3AF]">← হোমে ফিরে যান</button>
        <button onClick={() => navigate('/support')} className="text-[12px] text-primary font-medium">Support-এ যোগাযোগ করুন</button>
      </div>
    </PageWrapper>
  )
}
