import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ordersApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import { useOrder, usePaymentMethod, stageOf, stagePath, isPastDeadline } from '@/hooks/useOrder'
import { useVerifyPayment, useAutoVerify } from '@/hooks/useVerifyPayment'
import { hashProblem } from '@/utils/paymentStatus'
import { SubHeader, PageWrapper } from '@/components/layout'
import { Countdown, Spinner, ErrorState, ConfirmSheet, InlineError, toast } from '@/components/ui'
import { formatUsdtExact, formatBDT } from '@/utils'
import { getTelegram } from '@/hooks/useTelegram'

// Binance Payment page.
//  • Binance Pay      → checkout link; verified by the Backend (Binance webhook)
//  • Binance ID/Pay ID, USDT TRC20 / BEP20 / ERC20, other admin methods
//                     → send to the shown address, then submit the transaction
//                       hash for Backend / admin verification
// This page NEVER marks a payment as successful: it only follows the order
// status the Backend reports (GET /orders/:id). "Check my payment" calls
// POST /orders/:id/verify — the Backend asks Binance and decides.
// Method name, Pay ID, merchant, QR and instructions come from the order's
// Backend snapshot (`details`); nothing about a method is hardcoded here.

const POLL_MS = 8000

function isPayIdMethod(payment: { payment_method: string }, method: { kind?: string } | null): boolean {
  return payment.payment_method === 'binance_id' || method?.kind === 'pay_id'
}

function copy(text: string, label: string) {
  navigator.clipboard?.writeText(text)
    .then(() => toast(`${label} কপি হয়েছে`, 'success'))
    .catch(() => toast('কপি করা যায়নি — দীর্ঘ চেপে ধরে কপি করুন।', 'error'))
}

function openExternal(url: string) {
  if (!/^https:\/\//i.test(url)) return   // only https checkout links are ever opened
  const tg = getTelegram()
  if (tg?.initData && typeof tg.openLink === 'function') tg.openLink(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}

export default function PaymentPage() {
  const { orderId } = useParams<{ orderId: string }>()
  const navigate = useNavigate()
  const { order, payment, details, loading, error, pollError, refresh } = useOrder(orderId, { intervalMs: POLL_MS })
  const { method, failed: methodFailed } = usePaymentMethod(order?.payment_method_id)

  const [txHash, setTxHash] = useState('')
  const [note, setNote] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [showFallback, setShowFallback] = useState(false)
  const [openedCheckout, setOpenedCheckout] = useState(false)   // user went to Binance → check again when they return
  const { check, checking, cooldown, note: verifyMsg } = useVerifyPayment(orderId, { onSettled: () => { void refresh() } })

  // Follow the Backend status: any non-payable status leaves this page.
  // `replace` so the Back button never returns to a stale payment screen.
  useEffect(() => {
    if (!order || !orderId) return
    const stage = stageOf(order)
    if (stage !== 'pay') navigate(stagePath(orderId, stage), { replace: true })
  }, [order, orderId, navigate])

  const isBinancePay = payment?.payment_method === 'binance_pay'
  const txProblem = txHash.trim() ? hashProblem(payment?.payment_method ?? '', txHash) : null
  const txValid = txHash.trim().length > 0 && txProblem === null
  // After returning from the Binance checkout, ask the Backend (throttled) without the user pressing anything.
  useAutoVerify(isBinancePay && openedCheckout && order !== null && stageOf(order) === 'pay', check, 15000)
  const expired = useMemo(() => (order ? isPastDeadline(order) : false), [order])

  function goFailed() { if (orderId) navigate(stagePath(orderId, 'failed'), { replace: true }) }

  async function submit() {
    if (!orderId || !txValid) return
    setSubmitting(true)
    try {
      await ordersApi.submit(orderId, {
        transaction_hash: txHash.trim(),
        ...(note.trim() ? { user_note: note.trim().slice(0, 500) } : {}),
      })
      setConfirmOpen(false)
      navigate(stagePath(orderId, 'pending'), { replace: true })
    } catch (e) {
      setConfirmOpen(false)
      const msg = getErrorMessage(e, 'Payment জমা দেওয়া যায়নি।')
      const status = (e as { status?: number } | null)?.status
      if (status === 409 && /already submitted|already processed/i.test(msg)) {
        // Already in review (or finished) — the status poll will route us.
        navigate(stagePath(orderId, 'pending'), { replace: true })
      } else if (/expired/i.test(msg)) {
        goFailed()
      } else {
        toast(msg, 'error')   // e.g. "Transaction hash already used"
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function checkNow() {
    if (!orderId) return
    // The Backend asks Binance. Success / review / failure all arrive as the
    // order's status (the effect above routes to the matching screen).
    const r = await check()
    if (r?.outcome === 'wait') {
      // Binance has not confirmed yet → the waiting screen keeps checking.
      navigate(stagePath(orderId, 'pending'), { replace: true })
    }
  }

  const header = <SubHeader title="Payment" />

  if (loading) return <PageWrapper hasBottomNav={false}>{header}<div className="flex justify-center py-16"><Spinner size={32} /></div></PageWrapper>
  if (error || !order || !payment) {
    return (
      <PageWrapper hasBottomNav={false}>
        {header}
        <ErrorState message={error ?? 'Order পাওয়া যায়নি।'} onRetry={() => void refresh()} />
      </PageWrapper>
    )
  }

  // The order's own snapshot wins (admin edits never change an open order); the method is only a fallback.
  const address = payment.wallet_address ?? details?.wallet_address ?? details?.pay_id ?? payment.pay_id ?? method?.pay_id ?? method?.wallet_address ?? null
  const network = payment.network ?? details?.network ?? method?.network_name ?? null
  const qr = !isBinancePay ? details?.qr_code_url ?? method?.qr_code_url ?? null : null
  const exact = formatUsdtExact(order.final_usdt)
  const methodName = details?.method_name || method?.name || payment.payment_method
  const isPayId = isPayIdMethod(payment, method)
  const merchantName = (details?.merchant_name ?? method?.merchant_name)?.trim() || null
  const instructions = (details?.instructions_text ?? method?.instructions_text ?? '').trim()
  const methodLoaded = Boolean(details || method)

  return (
    <PageWrapper hasBottomNav={false}>
      {header}
      <div className="px-4 py-4 space-y-4">

        {pollError && <InlineError message="সংযোগ সমস্যা — স্ট্যাটাস আপডেট হচ্ছে না। আবার চেষ্টা করা হবে।" onRetry={() => void refresh()} />}

        {/* Amount, rate & timeout */}
        <div className="bg-card border border-border rounded-[12px] p-[14px] text-center">
          <p className="text-[11px] text-[#6B7280] mb-1">{methodName}</p>
          <p className="text-[26px] font-extrabold text-white mb-[3px] tabular-nums">{exact} <span className="text-[14px] font-semibold text-[#9CA3AF]">USDT</span></p>
          <p className="text-[11px] text-[#6B7280]">
            {formatBDT(order.final_bdt)} · ১ USDT = ৳{order.usdt_rate_at_creation}
            {order.discount_bdt > 0 && ` · ছাড় ${formatBDT(order.discount_bdt)}`}
          </p>
          <div className="flex items-center justify-center gap-2 mt-2">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
              <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
            </svg>
            {expired
              ? <span className="text-[12px] text-danger font-semibold">সময় শেষ</span>
              : <>
                  <Countdown expiresAt={order.expires_at} onExpire={goFailed} className="text-[12px] text-warning" />
                  <span className="text-[11px] text-[#6B7280]">বাকি</span>
                </>}
          </div>
          {(method?.min_amount_usdt != null || method?.max_amount_usdt != null) && (
            <p className="text-[10px] text-[#6B7280] mt-2">
              এই পদ্ধতিতে সীমা: ন্যূনতম {method?.min_amount_usdt} USDT
              {method?.max_amount_usdt != null && ` · সর্বোচ্চ ${method.max_amount_usdt} USDT`}
            </p>
          )}
        </div>

        {/* Verification status (Backend value) */}
        <div className="flex items-center justify-between bg-card border border-border rounded-[10px] px-3 py-2">
          <span className="text-[11px] text-[#6B7280]">যাচাই অবস্থা</span>
          <span className="text-[11px] font-semibold text-warning">
            {payment.verification_status === 'failed'
              ? 'যাচাই ব্যর্থ — Support-এ জানান'
              : isBinancePay ? 'Binance-এর নিশ্চিতকরণের অপেক্ষায়' : 'আপনার Hash জমার অপেক্ষায়'}
          </span>
        </div>

        {/* ── Binance Pay ── */}
        {isBinancePay && (
          <div className="space-y-3">
            {payment.binance_checkout_url ? (
              <motion.button
                whileTap={{ scale: 0.98 }}
                onClick={() => { setOpenedCheckout(true); openExternal(payment.binance_checkout_url!) }}
                disabled={expired}
                className="flex items-center justify-center gap-3 w-full py-[14px] rounded-btn bg-[#F0B90B] text-[#1E2026] font-bold text-[14px] disabled:opacity-50"
              >
                🔶 Binance Pay দিয়ে পরিশোধ করুন
              </motion.button>
            ) : (
              <InlineError message="Binance Checkout লিংক পাওয়া যায়নি। পরে আবার চেষ্টা করুন বা অন্য পদ্ধতি বেছে নিন।" />
            )}
            <ol className="bg-card border border-border rounded-[12px] p-3 space-y-1 text-[11px] text-[#9CA3AF] leading-[1.6] list-decimal list-inside">
              <li>উপরের বোতামে Binance Checkout খুলুন ও পরিশোধ সম্পন্ন করুন।</li>
              <li>Payment হলে Binance আমাদের Server-কে জানাবে; Server যাচাই করলেই Access চালু হবে।</li>
              <li>পরিশোধের পর এখানে ফিরে "পরিশোধ করেছি" চাপুন — স্ট্যাটাস নিজে থেকেই আপডেট হয়।</li>
            </ol>
            {instructions && (
              <p className="text-[11px] text-[#FCD34D]/90 leading-[1.6] whitespace-pre-line break-words bg-warning/8 border border-warning/20 rounded-[12px] p-3">{instructions}</p>
            )}
            <Primary onClick={() => void checkNow()} loading={checking} disabled={cooldown > 0}>
              {cooldown > 0 ? `আবার দেখা যাবে ${cooldown} সেকেন্ড পর` : '✅ পরিশোধ করেছি — Binance-এ যাচাই করুন'}
            </Primary>
            {verifyMsg && (
              <p className={`text-[11px] leading-[1.5] rounded-[10px] px-3 py-2 border ${verifyMsg.kind === 'error' ? 'text-[#FCA5A5] bg-danger/8 border-danger/20' : 'text-[#9CA3AF] bg-card border-border'}`} role="status">{verifyMsg.text}</p>
            )}

            {/* Manual-review fallback when the webhook is slow */}
            <button onClick={() => setShowFallback((v) => !v)} className="w-full text-center text-[11px] text-primary font-medium">
              {showFallback ? 'ঢেকে ফেলুন ▴' : 'অনেকক্ষণেও নিশ্চিত হয়নি? Manual Review-এ পাঠান ▾'}
            </button>
            {showFallback && (
              <ProofForm
                label="Binance Order / Transaction ID"
                placeholder="Binance-এর Order বা Transaction ID"
                txHash={txHash} setTxHash={setTxHash} note={note} setNote={setNote}
                valid={txValid} problem={txProblem} disabled={expired || submitting} onSubmit={() => setConfirmOpen(true)}
                help="Admin হাতে যাচাই করবেন। Binance-এর স্বয়ংক্রিয় নিশ্চিতকরণ এলে সেটিই কার্যকর হবে।"
              />
            )}
          </div>
        )}

        {/* ── Manual crypto / Binance ID ── */}
        {!isBinancePay && (
          <>
            {address ? (
              <div className="bg-card border border-border rounded-[12px] p-3 space-y-3">
                <p className="text-[10px] text-[#6B7280] font-semibold uppercase tracking-[0.4px]">
                  {isPayId ? 'Binance ID / Pay ID-তে পাঠান' : `${network ?? 'নির্দিষ্ট Network'} ঠিকানায় পাঠান`}
                </p>

                {qr && (
                  <div className="flex justify-center">
                    <img src={qr} alt="Payment QR Code" className="w-[168px] h-[168px] rounded-[10px] bg-white p-2 object-contain" loading="lazy" />
                  </div>
                )}

                <div className="flex items-start gap-2">
                  <p className="text-[11px] text-primary font-mono flex-1 break-all leading-[1.5]">{address}</p>
                  <button onClick={() => copy(address, isPayId ? 'ID' : 'Address')} className="px-[10px] py-[4px] rounded-[6px] border border-primary/30 bg-primary/10 text-primary text-[10px] font-semibold flex-shrink-0">Copy</button>
                </div>

                {network && (
                  <div className="flex justify-between items-center text-[11px]">
                    <span className="text-[#9CA3AF]">Network</span>
                    <strong className="text-white">{network}</strong>
                  </div>
                )}
                {merchantName && (
                  <div className="flex justify-between items-center text-[11px] gap-3">
                    <span className="text-[#9CA3AF] flex-shrink-0">{isPayId ? 'অ্যাকাউন্টের নাম' : 'Merchant'}</span>
                    <strong className="text-white text-right break-words min-w-0">{merchantName}</strong>
                  </div>
                )}
                <div className="flex justify-between items-center bg-primary/5 rounded-[8px] px-[10px] py-[7px]">
                  <span className="text-[11px] text-[#9CA3AF]">হুবহু পাঠান</span>
                  <div className="flex items-center gap-2">
                    <strong className="text-[12px] text-white tabular-nums">{exact} USDT</strong>
                    <button onClick={() => copy(exact, 'Amount')} className="px-[8px] py-[3px] rounded-[5px] border border-primary/30 bg-primary/10 text-primary text-[9px] font-semibold">Copy</button>
                  </div>
                </div>
                <p className="text-[10px] text-[#FCD34D] leading-[1.5]">
                  ⚠️ {network && !isPayId ? `শুধু ${network} Network-এ ` : ''}পাঠান। ভুল Network-এ বা কম পরিমাণ পাঠালে টাকা হারাতে পারেন এবং Payment যাচাই হবে না।
                </p>
              </div>
            ) : (
              <InlineError message="এই পদ্ধতির Payment তথ্য পাওয়া যায়নি। অন্য পদ্ধতি বেছে নিন বা Support-এ জানান।" />
            )}

            {instructions && (
              <div className="bg-warning/8 border border-warning/20 rounded-[12px] p-3">
                <p className="text-[11px] text-[#FCD34D] font-semibold mb-1">📋 নির্দেশনা</p>
                {/* plain text only — admin text is never injected as HTML */}
                <p className="text-[11px] text-[#FCD34D]/90 leading-[1.6] whitespace-pre-line break-words">{instructions}</p>
              </div>
            )}
            {methodFailed && !methodLoaded && (
              <p className="text-[10px] text-[#6B7280]">QR ও বিস্তারিত নির্দেশনা এখন লোড করা যায়নি; উপরের ঠিকানা ও পরিমাণ সঠিক।</p>
            )}

            <ProofForm
              label="Transaction Hash জমা দিন"
              placeholder="পাঠানোর পর পাওয়া Hash / TXID"
              txHash={txHash} setTxHash={setTxHash} note={note} setNote={setNote}
              valid={txValid} problem={txProblem} disabled={expired || submitting} onSubmit={() => setConfirmOpen(true)}
              help="জমা দিলে Backend/Admin যাচাই করবেন। যাচাইয়ের আগে Access চালু হয় না।"
            />
          </>
        )}

        {expired && (
          <div className="bg-danger/8 border border-danger/20 rounded-[10px] px-3 py-2 text-[11px] text-[#FCA5A5]">
            Payment-এর সময় শেষ। নতুন Order তৈরি করতে{' '}
            <button className="underline font-semibold" onClick={goFailed}>এখানে যান</button>।
          </div>
        )}

        <button onClick={() => navigate('/support')} className="w-full text-center text-[11px] text-[#6B7280]">সমস্যা হচ্ছে? Support-এ যোগাযোগ করুন</button>
      </div>

      <ConfirmSheet
        open={confirmOpen}
        title="Payment জমা দেবেন?"
        confirmLabel="হ্যাঁ, জমা দিন"
        loading={submitting}
        onConfirm={() => void submit()}
        onCancel={() => setConfirmOpen(false)}
      >
        <div className="space-y-2">
          <p className="text-[12px] text-[#9CA3AF] leading-[1.6]">এই Hash জমা দিলে Order যাচাইয়ে যাবে এবং পরে বদলানো যাবে না।</p>
          <p className="text-[11px] font-mono text-white bg-card border border-border rounded-[8px] px-3 py-2 break-all">{txHash.trim()}</p>
        </div>
      </ConfirmSheet>
    </PageWrapper>
  )
}

// ─── Small pieces ─────────────────────────────────────────────────────────────
function Primary({ children, onClick, loading, disabled }: { children: ReactNode; onClick: () => void; loading?: boolean; disabled?: boolean }) {
  return (
    <motion.button whileTap={{ scale: 0.98 }} onClick={onClick} disabled={loading || disabled} className="btn-primary disabled:opacity-60">
      {loading ? <Spinner size={18} /> : children}
    </motion.button>
  )
}

interface ProofFormProps {
  label: string; placeholder: string; help: string
  txHash: string; setTxHash: (v: string) => void
  note: string; setNote: (v: string) => void
  valid: boolean; problem: string | null; disabled: boolean; onSubmit: () => void
}
function ProofForm({ label, placeholder, help, txHash, setTxHash, note, setNote, valid, problem, disabled, onSubmit }: ProofFormProps) {
  const showErr = txHash.trim().length > 0 && !valid
  return (
    <div className="space-y-2">
      <p className="text-[10px] text-[#6B7280] font-semibold uppercase tracking-[0.4px]">{label}</p>
      <input
        value={txHash}
        onChange={(e) => setTxHash(e.target.value.replace(/\s/g, ''))}
        placeholder={placeholder}
        autoCapitalize="off" autoCorrect="off" spellCheck={false} maxLength={128}
        aria-invalid={showErr}
        className="w-full bg-card border border-border rounded-[9px] px-3 py-[9px] text-[11px] text-white font-mono outline-none placeholder:text-[#6B7280] placeholder:font-sans"
      />
      {showErr && problem && <p className="text-[10px] text-[#FCA5A5]">{problem}</p>}
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Admin-এর জন্য নোট (ঐচ্ছিক)"
        maxLength={500} rows={2}
        className="w-full bg-card border border-border rounded-[9px] px-3 py-[9px] text-[11px] text-white outline-none placeholder:text-[#6B7280] resize-none"
      />
      <p className="text-[10px] text-[#6B7280] leading-[1.5]">{help}</p>
      <motion.button whileTap={{ scale: 0.98 }} onClick={onSubmit} disabled={disabled || !valid} className="btn-success disabled:opacity-50">
        ✅ Payment জমা দিন
      </motion.button>
    </div>
  )
}
