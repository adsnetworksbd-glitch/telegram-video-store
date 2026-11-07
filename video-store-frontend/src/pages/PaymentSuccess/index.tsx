import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { accessApi } from '@/api'
import type { AccessStatus } from '@/types'
import { useOrder, stageOf, stagePath, contentPath } from '@/hooks/useOrder'
import { useContentLookup } from '@/hooks/useContentLookup'
import { useOpenSource } from '@/hooks/useOpenSource'
import { SubHeader, PageWrapper } from '@/components/layout'
import { AccessStateCard } from '@/components/access'
import { Spinner, ErrorState } from '@/components/ui'
import { formatDate, formatUsdtExact, formatBDT } from '@/utils'

// Shown ONLY for an order the Backend reports as `completed`. Typing the URL of
// someone else's / an unpaid order cannot show success — the page redirects to
// the screen that matches the real status. Access details (source, expiry) are
// read from the Backend access check, not assumed.

export default function PaymentSuccessPage() {
  const { orderId } = useParams<{ orderId: string }>()
  const navigate = useNavigate()
  const { order, loading, error, refresh } = useOrder(orderId)
  const { openingId, open } = useOpenSource()
  const [access, setAccess] = useState<AccessStatus | null>(null)
  const [accessFailed, setAccessFailed] = useState(false)

  const lookup = useContentLookup(order ? [{ content_type: order.content_type, content_id: order.content_id }] : [])
  const content = order ? lookup(order.content_type, order.content_id) : undefined

  useEffect(() => {
    if (!order || !orderId) return
    const stage = stageOf(order)
    if (stage !== 'success') navigate(stagePath(orderId, stage), { replace: true })
  }, [order, orderId, navigate])

  useEffect(() => {
    if (!order || order.status !== 'completed') return
    let live = true
    setAccessFailed(false)
    const req = order.content_type === 'video' ? accessApi.checkVideo(order.content_id) : accessApi.checkPackage(order.content_id)
    req.then((r) => { if (live) setAccess(r.data) }).catch(() => { if (live) setAccessFailed(true) })
    return () => { live = false }
  }, [order])

  const goHome = () => navigate('/', { replace: true })
  const header = <SubHeader title="Payment সফল" onBack={goHome} />

  if (loading || (order && order.status !== 'completed')) {
    return <PageWrapper hasBottomNav={false}>{header}<div className="flex justify-center py-16"><Spinner size={32} /></div></PageWrapper>
  }
  if (error || !order) {
    return <PageWrapper hasBottomNav={false}>{header}<ErrorState message={error ?? 'Order পাওয়া যায়নি।'} onRetry={() => void refresh()} /></PageWrapper>
  }

  const isVideo = order.content_type === 'video'

  return (
    <PageWrapper hasBottomNav={false}>
      {header}

      <motion.div
        initial={{ opacity: 0, scale: 0.85 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: 'spring', stiffness: 180 }}
        className="flex flex-col items-center text-center px-4 pt-8 pb-4"
      >
        <div className="w-[72px] h-[72px] rounded-full bg-success/10 border-2 border-success/30 flex items-center justify-center mb-4" aria-hidden>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="2.2" strokeLinecap="round"><polyline points="20 6 9 17 4 12" /></svg>
        </div>
        <h1 className="text-[18px] font-bold text-white mb-2">Payment যাচাই হয়েছে! 🎉</h1>
        <p className="text-[12px] text-[#9CA3AF]">{content?.title ? `“${content.title}”-এ ` : ''}আপনার Access চালু করা হয়েছে।</p>
      </motion.div>

      <div className="px-4 space-y-4">
        {/* Real Access state from the Backend */}
        {access && <AccessStateCard access={access} />}
        {accessFailed && (
          <p className="text-[11px] text-[#FCD34D] bg-warning/8 border border-warning/20 rounded-[10px] px-3 py-2">
            Access-এর বিস্তারিত এখন লোড করা যায়নি। "আমার Purchases" থেকে দেখে নিন।
          </p>
        )}

        <div className="bg-card border border-border rounded-[12px] overflow-hidden">
          {[
            { k: 'Order ID', v: `#${order.id.slice(0, 12).toUpperCase()}` },
            { k: 'পরিশোধ', v: `${formatBDT(order.final_bdt)} · ${formatUsdtExact(order.final_usdt)} USDT` },
            ...(order.coupon_code ? [{ k: 'Coupon', v: `${order.coupon_code} (−${formatBDT(order.discount_bdt)})` }] : []),
            { k: 'তারিখ', v: formatDate(order.completed_at ?? order.created_at) },
          ].map((row, i, arr) => (
            <div key={row.k} className={`flex justify-between items-center px-3 py-[9px] ${i < arr.length - 1 ? 'border-b border-border' : ''}`}>
              <span className="text-[11px] text-[#6B7280]">{row.k}</span>
              <span className="text-[11px] font-semibold text-white">{row.v}</span>
            </div>
          ))}
        </div>

        {isVideo ? (
          <motion.button whileTap={{ scale: 0.98 }} disabled={openingId === order.content_id} onClick={() => void open(order.content_id)} className="btn-success">
            {openingId === order.content_id ? <Spinner size={18} /> : '⬇️ এখনই Open / Download করুন'}
          </motion.button>
        ) : (
          <motion.button whileTap={{ scale: 0.98 }} onClick={() => navigate(contentPath(order), { replace: true })} className="btn-success">
            📦 Package-এর ভিডিওগুলো দেখুন
          </motion.button>
        )}
        {isVideo && <button onClick={() => navigate(contentPath(order), { replace: true })} className="btn-ghost">ভিডিও পেজে যান</button>}
        <button onClick={() => navigate('/my-purchases')} className="btn-ghost">📋 আমার Purchases দেখুন</button>
      </div>
    </PageWrapper>
  )
}
