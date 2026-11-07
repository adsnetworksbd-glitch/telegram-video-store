import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { videosApi, packagesApi, paymentMethodsApi, couponsApi, ordersApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import type { VideoDetail, PackageDetail, PaymentMethod, CouponValidation } from '@/types'
import { useConfigStore } from '@/store'
import { SubHeader, PageWrapper } from '@/components/layout'
import { AccessStateCard } from '@/components/access'
import { Button, Spinner, ErrorState, InlineError, ConfirmSheet, toast } from '@/components/ui'
import { formatBDT, formatFileSize, formatDuration, formatAccessDuration, bdtToUsdt, cx } from '@/utils'

// ─── Individual Purchase Page ─────────────────────────────────────────────────
// Price, duration and availability all come from the Backend content record.
// Coupon discount comes from /coupons/validate; the final amount is computed
// again by the Backend when the order is created.

type Content = VideoDetail | PackageDetail

export default function PurchasePage() {
  const { id } = useParams<{ id: string }>()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const appConfig = useConfigStore((s) => s.appConfig)
  // Route decides the type (/videos/:id/purchase vs /packages/:id/purchase)
  const contentType: 'video' | 'package' = pathname.startsWith('/packages') ? 'package' : 'video'
  const basePath = contentType === 'video' ? '/videos' : '/packages'

  const [content, setContent] = useState<Content | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(false)

  const [methods, setMethods] = useState<PaymentMethod[]>([])
  const [methodsError, setMethodsError] = useState<string | null>(null)
  const [selectedMethod, setSelectedMethod] = useState('')

  const [coupon, setCoupon] = useState('')
  const [couponResult, setCouponResult] = useState<CouponValidation | null>(null)
  const [couponChecked, setCouponChecked] = useState('')   // the exact code that was validated
  const [couponLoading, setCouponLoading] = useState(false)

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [orderLoading, setOrderLoading] = useState(false)
  const orderBusy = useRef(false)   // double-tap guard: at most one order request in flight

  const loadMethods = useCallback(async () => {
    setMethodsError(null)
    try {
      const res = await paymentMethodsApi.list()
      const list = res.data.methods.filter((m) => m.is_enabled !== false)
      setMethods(list)
      setSelectedMethod((cur) => (list.some((m) => m.id === cur) ? cur : list[0]?.id ?? ''))
    } catch (e) {
      setMethodsError(getErrorMessage(e, 'Payment পদ্ধতি লোড করা যায়নি।'))
    }
  }, [])

  const loadContent = useCallback(async () => {
    if (!id) return
    setLoading(true); setError(false)
    try {
      const res = contentType === 'video' ? await videosApi.detail(id) : await packagesApi.detail(id)
      setContent(res.data)
    } catch { setError(true) }
    finally { setLoading(false) }
  }, [id, contentType])

  useEffect(() => {
    setCoupon(''); setCouponResult(null); setCouponChecked('')
    void loadContent()
    void loadMethods()
  }, [loadContent, loadMethods])

  const title = 'Purchase করুন'

  if (loading) return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <div className="flex justify-center py-16"><Spinner size={32} /></div>
    </PageWrapper>
  )
  if (error || !content) return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <ErrorState onRetry={() => void loadContent()} />
    </PageWrapper>
  )

  const isVideo = contentType === 'video'
  const v = content as VideoDetail
  const p = content as PackageDetail
  const name = isVideo ? v.title : p.name
  const thumb = isVideo ? v.thumbnail_url : p.thumbnail_url
  const basePrice = isVideo ? v.price_bdt : p.price_bdt
  const accessHours = isVideo ? v.purchase_duration_hours : (p.duration_type === 'lifetime' ? 0 : p.duration_hours)
  const durationLabel = formatAccessDuration(accessHours)

  // Applied coupon counts only if it is valid AND the box still holds the validated code
  const couponApplied = Boolean(couponResult?.valid) && couponChecked === coupon.trim()
  const discount = couponApplied ? couponResult!.discount_bdt : 0
  const finalBdt = couponApplied ? couponResult!.final_bdt : basePrice

  // USDT estimate only with the admin-set rate (the order shows the exact amount)
  const rate = appConfig?.usdt_to_bdt_rate
  const usdtEstimate = rate ? bdtToUsdt(finalBdt, rate) : null
  const method = methods.find((m) => m.id === selectedMethod)
  const belowMin = Boolean(method && usdtEstimate !== null && usdtEstimate < method.min_amount_usdt)
  const aboveMax = Boolean(method && usdtEstimate !== null && method.max_amount_usdt != null && usdtEstimate > method.max_amount_usdt)

  // ── Availability (Backend decides; this only explains) ───────────────────
  let blocked: { icon: string; text: string } | null = null
  if (content.available_methods.is_free) {
    blocked = { icon: '🎁', text: 'এই ভিডিওটি বিনামূল্যে — কিনতে হবে না।' }
  } else if (content.access.granted) {
    blocked = {
      icon: '✅',
      text: content.access.is_lifetime
        ? 'এতে আপনার Lifetime Access আছে — আবার কিনতে হবে না।'
        : 'আপনার Access এখনো সক্রিয়। মেয়াদ শেষ হলে নতুন করে কিনতে পারবেন।',
    }
  } else if (!content.available_methods.purchase) {
    blocked = { icon: '🚫', text: 'এই কনটেন্ট এখন কেনার জন্য উপলব্ধ নয়।' }
  }

  async function applyCoupon() {
    const code = coupon.trim()
    if (!code || !id) return
    setCouponLoading(true)
    try {
      const res = await couponsApi.validate({
        code, content_type: contentType, content_id: id, order_amount_bdt: basePrice,
      })
      setCouponResult(res.data)
      setCouponChecked(code)
      toast(res.data.valid ? 'Coupon প্রয়োগ হয়েছে!' : (res.data.message || 'Coupon সঠিক নয়।'), res.data.valid ? 'success' : 'error')
    } catch (e) {
      toast(getErrorMessage(e, 'Coupon যাচাই করা যায়নি।'), 'error')
    } finally {
      setCouponLoading(false)
    }
  }

  function removeCoupon() {
    setCoupon(''); setCouponResult(null); setCouponChecked('')
  }

  async function placeOrder() {
    if (!id || !selectedMethod || orderBusy.current) return
    orderBusy.current = true
    setOrderLoading(true)
    try {
      const res = await ordersApi.create({
        content_type: contentType,
        content_id: id,
        payment_method_id: selectedMethod,
        coupon_code: couponApplied ? coupon.trim() : undefined,
      })
      if (res.data.payment_details?.reused) toast('আপনার আগের Order এখনো চালু আছে — সেটিই খোলা হচ্ছে।', 'info')
      navigate(`/payment/${res.data.order_id}`)
    } catch (e) {
      const status = (e as { status?: number })?.status
      setConfirmOpen(false)
      if (status === 409 && /under review/i.test(getErrorMessage(e, ''))) {
        // A payment for this item is already waiting for admin review.
        toast('এই আইটেমের Payment ইতিমধ্যে যাচাইয়ের অপেক্ষায় আছে।', 'info')
        navigate('/transactions')
      } else if (status === 409) {
        toast('এতে আগে থেকেই Access আছে।', 'info')
        void loadContent()
      } else {
        toast(getErrorMessage(e, 'Order তৈরি হয়নি।'), 'error')
      }
    } finally {
      orderBusy.current = false
      setOrderLoading(false)
    }
  }

  const canProceed = !blocked && Boolean(selectedMethod) && !belowMin && !aboveMax

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <div className="px-4 py-4 space-y-4">

        {/* Video information */}
        <div className="flex gap-[10px] bg-card border border-border rounded-[12px] p-[10px] items-center">
          <div className="w-[68px] h-[42px] rounded-[8px] bg-surface flex-shrink-0 overflow-hidden flex items-center justify-center">
            {thumb
              ? <img src={thumb} className="w-full h-full object-cover" alt="" />
              : <svg width="14" height="14" viewBox="0 0 24 24" fill="rgba(255,255,255,0.4)"><polygon points="5,3 19,12 5,21" /></svg>}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[12px] font-semibold text-white leading-[1.3] line-clamp-2 mb-[2px]">{name}</p>
            <p className="text-[10px] text-[#6B7280]">
              {isVideo
                ? `${v.quality} · ${formatDuration(v.duration_seconds)} · ${formatFileSize(v.file_size_mb)}`
                : `${p.video_count}টি ভিডিও`}
            </p>
          </div>
        </div>

        {blocked && (
          <div className="bg-card border border-border rounded-[12px] px-3 py-3 space-y-3">
            <div className="flex gap-2 items-start">
              <span className="text-[18px]">{blocked.icon}</span>
              <p className="text-[12px] text-[#D1D5DB] leading-[1.6]">{blocked.text}</p>
            </div>
            {content.access.granted && <AccessStateCard access={content.access} />}
            <Button variant="ghost" onClick={() => id && navigate(`${basePath}/${id}`, { replace: true })}>
              {isVideo ? 'ভিডিওতে ফিরুন' : 'Package-এ ফিরুন'}
            </Button>
          </div>
        )}

        {/* Dynamic price */}
        <div className="bg-card border border-border rounded-[12px] overflow-hidden">
          <PriceRow label="মূল মূল্য" value={formatBDT(basePrice)} />
          {!isVideo && p.original_price_bdt > p.price_bdt && (
            <PriceRow label="Package ছাড়" value={`- ${formatBDT(p.original_price_bdt - p.price_bdt)}`} valueColor="text-[#6EE7B7]" hint={`(মূল ${formatBDT(p.original_price_bdt)})`} />
          )}
          <PriceRow
            label="Coupon ছাড়"
            value={discount > 0 ? `- ${formatBDT(discount)}` : '—'}
            valueColor={discount > 0 ? 'text-[#6EE7B7]' : undefined}
          />
          <div className="flex justify-between items-center px-3 py-3 bg-primary/6">
            <span className="text-[13px] font-semibold text-white">মোট পরিশোধ</span>
            <div className="text-right">
              <span className="text-[18px] font-extrabold text-primary block">{formatBDT(finalBdt)}</span>
              {usdtEstimate !== null && (
                <span className="text-[10px] text-[#6B7280]">≈ {usdtEstimate.toFixed(2)} USDT</span>
              )}
            </div>
          </div>
        </div>

        {/* Access duration */}
        <div className="flex gap-2 items-center bg-success/8 border border-success/20 rounded-[10px] px-3 py-[9px]">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="1.8" strokeLinecap="round" className="flex-shrink-0">
            <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
          </svg>
          <span className="text-[11px] text-[#6EE7B7]">Access সময়কাল: <strong>{durationLabel}</strong></span>
        </div>

        {/* Coupon */}
        {!blocked && (
          <div>
            <div className="flex gap-2">
              <input
                value={coupon}
                onChange={(e) => setCoupon(e.target.value.toUpperCase())}
                placeholder="Coupon Code (যদি থাকে)"
                maxLength={64}
                autoCapitalize="characters"
                className="flex-1 min-w-0 bg-card border border-border rounded-[10px] px-3 py-[9px] text-[12px] text-white outline-none placeholder:text-[#6B7280]"
              />
              {couponApplied ? (
                <button onClick={removeCoupon} className="px-4 py-[9px] rounded-[10px] bg-danger/10 border border-danger/25 text-[#FCA5A5] text-[12px] font-semibold">
                  সরান
                </button>
              ) : (
                <button
                  onClick={() => void applyCoupon()}
                  disabled={couponLoading || !coupon.trim()}
                  className="px-4 py-[9px] rounded-[10px] bg-primary/15 border border-primary/30 text-primary text-[12px] font-semibold disabled:opacity-50 min-w-[64px] flex items-center justify-center"
                >
                  {couponLoading ? <Spinner size={14} /> : 'প্রয়োগ'}
                </button>
              )}
            </div>
            {couponResult && couponChecked === coupon.trim() && (
              <p className={cx('text-[11px] mt-2', couponResult.valid ? 'text-[#6EE7B7]' : 'text-[#FCA5A5]')}>
                {couponResult.valid ? '✅' : '⚠️'} {couponResult.message}
              </p>
            )}
          </div>
        )}

        {/* Payment methods */}
        {!blocked && (
          <div>
            <p className="text-[11px] text-[#6B7280] font-semibold uppercase tracking-[0.4px] mb-2">Payment পদ্ধতি</p>
            {methodsError ? (
              <InlineError message={methodsError} onRetry={() => void loadMethods()} />
            ) : methods.length === 0 ? (
              <p className="text-[12px] text-[#9CA3AF]">এই মুহূর্তে কোনো Payment পদ্ধতি চালু নেই।</p>
            ) : (
              <div className="space-y-2">
                {methods.map((m) => (
                  <motion.button
                    key={m.id}
                    type="button"
                    whileTap={{ scale: 0.98 }}
                    onClick={() => setSelectedMethod(m.id)}
                    aria-pressed={selectedMethod === m.id}
                    className={cx(
                      'w-full text-left flex items-center gap-3 bg-card border rounded-[10px] p-[10px] cursor-pointer',
                      selectedMethod === m.id ? 'border-primary/50 bg-primary/7' : 'border-border',
                    )}
                  >
                    <div className="w-8 h-8 rounded-[8px] bg-warning/12 flex items-center justify-center text-[16px] flex-shrink-0">
                      {methodIcon(m.type)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[12px] font-semibold text-white">{m.name}</p>
                      <p className="text-[10px] text-[#6B7280]">
                        {m.auto_verification_supported ? 'Auto verify' : 'Manual review'}
                        {m.network_name && m.kind !== 'gateway' ? ` · ${m.network_name}` : ''}
                        {m.min_amount_usdt > 0 ? ` · ন্যূনতম ${m.min_amount_usdt} USDT` : ''}
                        {m.max_amount_usdt != null ? ` · সর্বোচ্চ ${m.max_amount_usdt} USDT` : ''}
                      </p>
                    </div>
                    <div className={cx(
                      'w-4 h-4 rounded-full border-2 flex-shrink-0',
                      selectedMethod === m.id ? 'border-primary bg-primary shadow-[inset_0_0_0_3px_#0A0E1A]' : 'border-border',
                    )} />
                  </motion.button>
                ))}
              </div>
            )}
            {aboveMax && method && (
              <p className="text-[11px] text-[#FCD34D] mt-2">
                এই পদ্ধতিতে সর্বোচ্চ {method.max_amount_usdt} USDT পর্যন্ত গ্রহণযোগ্য। অন্য পদ্ধতি বেছে নিন।
              </p>
            )}
            {belowMin && method && (
              <p className="text-[11px] text-[#FCD34D] mt-2">
                এই পদ্ধতিতে ন্যূনতম {method.min_amount_usdt} USDT প্রয়োজন। অন্য পদ্ধতি বেছে নিন।
              </p>
            )}
          </div>
        )}

        {!blocked && (
          <Button onClick={() => setConfirmOpen(true)} disabled={!canProceed}>
            💳 Purchase নিশ্চিত করুন →
          </Button>
        )}
      </div>

      {/* Purchase confirmation */}
      <ConfirmSheet
        open={confirmOpen}
        title="Purchase নিশ্চিত করুন"
        confirmLabel="Order তৈরি করুন"
        loading={orderLoading}
        onConfirm={() => void placeOrder()}
        onCancel={() => setConfirmOpen(false)}
      >
        <div className="bg-card border border-border rounded-[12px] overflow-hidden">
          <SummaryRow label={isVideo ? 'ভিডিও' : 'Package'} value={name} />
          <SummaryRow label="Access সময়কাল" value={durationLabel} />
          <SummaryRow label="Payment" value={method?.name ?? '—'} />
          {couponApplied && <SummaryRow label="Coupon" value={`${coupon.trim()} (- ${formatBDT(discount)})`} />}
          <SummaryRow
            label="মোট"
            value={`${formatBDT(finalBdt)}${usdtEstimate !== null ? ` ≈ ${usdtEstimate.toFixed(2)} USDT` : ''}`}
            strong
          />
        </div>
        <p className="text-[11px] text-[#9CA3AF] leading-[1.5]">
          Order তৈরির পর পরের ধাপে Payment-এর বিস্তারিত ও সঠিক USDT পরিমাণ দেখানো হবে। Payment যাচাই না হওয়া পর্যন্ত Access চালু হবে না।
        </p>
      </ConfirmSheet>
    </PageWrapper>
  )
}

function methodIcon(type: string): string {
  switch (type) {
    case 'binance_pay': return '🔶'
    case 'binance_id':  return '🆔'
    case 'usdt_trc20':  return '🔴'
    case 'usdt_bep20':  return '🟡'
    case 'usdt_erc20':  return '🔷'
    default:            return '💠'
  }
}

function PriceRow({ label, value, valueColor, hint }: { label: string; value: string; valueColor?: string; hint?: string }) {
  return (
    <div className="flex justify-between items-center px-3 py-[10px] border-b border-border">
      <span className="text-[12px] text-[#9CA3AF]">{label}{hint && <span className="text-[10px] text-[#6B7280] ml-1">{hint}</span>}</span>
      <span className={`text-[12px] font-medium ${valueColor ?? 'text-white'}`}>{value}</span>
    </div>
  )
}

function SummaryRow({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex justify-between gap-3 px-3 py-[9px] border-b border-border last:border-b-0">
      <span className="text-[11px] text-[#9CA3AF] flex-shrink-0">{label}</span>
      <span className={cx('text-[12px] text-right min-w-0 break-words', strong ? 'font-bold text-primary' : 'font-medium text-white')}>{value}</span>
    </div>
  )
}
