import { useEffect, useState } from 'react'
import { Badge, ConfirmSheet, EmptyState, ErrorState, FilterChip, LoadMoreButton, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord, type PendingPayment } from '../configApi'
import { can, useAdminStore } from '../store'
import { ErrorBanner, Field, inputCls } from '../ui'
import { errorText, fmtCount, fmtDateTime, fmtMoney, loadSchema, num, str } from '../util'
import { useAdminList } from '../useAdminList'

const STATUS_VARIANT: Record<string, 'blue' | 'green' | 'orange' | 'red' | 'gray'> = {
  completed: 'green', under_review: 'orange', payment_submitted: 'orange', pending: 'gray', created: 'gray',
  failed: 'red', expired: 'gray', refunded: 'red', rejected: 'red',
}
const isHttps = (u: string) => u.startsWith('https://')

type Decision = { kind: 'approve' | 'reject'; orderId: string } | null

function PendingReview() {
  const admin = useAdminStore((s) => s.admin)
  const canReview = can(admin, 'payments.review')
  const list = useAdminList<PendingPayment>((p) => adminConfigApi.pendingPayments(p), [])
  const [decision, setDecision] = useState<Decision>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [reverifying, setReverifying] = useState<string | null>(null)

  async function confirm() {
    if (!decision || busy) return
    setBusy(true)
    setErr(null)
    try {
      if (decision.kind === 'approve') await adminConfigApi.approvePayment(decision.orderId, note.trim())
      else await adminConfigApi.rejectPayment(decision.orderId, note.trim())
      toast(decision.kind === 'approve' ? 'Payment অনুমোদিত হয়েছে, Access দেওয়া হয়েছে।' : 'Payment বাতিল করা হয়েছে।', 'success')
      setDecision(null)
      setNote('')
      list.reload()
    } catch (e) {
      setErr(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function reverify(orderId: string) {
    setReverifying(orderId)
    try {
      await adminConfigApi.reverifyPayment(orderId)
      toast('আবার যাচাই করা হয়েছে।', 'success')
      list.reload()
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setReverifying(null)
    }
  }

  if (list.error && list.items.length === 0) return <ErrorState message={list.error} onRetry={list.reload} />
  if (list.loading && list.items.length === 0) return <Skeleton className="h-[110px] rounded-[12px]" />
  if (list.items.length === 0) return <EmptyState icon="✅" title="রিভিউয়ের জন্য কোনো Payment নেই" />

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[12px] text-[#9CA3AF]">রিভিউ অপেক্ষমাণ: {fmtCount(list.total)}</p>
      <ul className="flex flex-col gap-2">
        {list.items.map((p) => {
          const id = str(p.order_id)
          const shot = str(p.screenshot_url)
          return (
            <li key={id} className="card-base flex flex-col gap-1.5 p-3">
              <div className="flex items-center justify-between gap-2">
                <Badge variant="orange">রিভিউ অপেক্ষমাণ</Badge>
                <span className="text-[11px] text-[#6B7280]">{fmtDateTime(p.submitted_at)}</span>
              </div>
              <div className="break-all text-[12px] text-[#9CA3AF]">Order: <span className="text-white">{id}</span></div>
              <div className="text-[12px] text-[#9CA3AF]">User: <span className="text-white">{str(p.user_id)}</span> · {str(p.content_type)}: <span className="break-all text-white">{str(p.content_id)}</span></div>
              <div className="text-[12px] text-[#9CA3AF]">Amount: <span className="text-white">{fmtMoney(num(p.final_bdt))}</span>{num(p.final_usdt) !== null && <> · {num(p.final_usdt)} USDT</>} · {str(p.payment_method) || '—'}</div>
              {str(p.transaction_hash) && <div className="break-all text-[12px] text-[#9CA3AF]">TxHash: <span className="text-white">{str(p.transaction_hash)}</span></div>}
              {str(p.user_note) && <div className="text-[12px] text-[#9CA3AF]">User note: <span className="text-white">{str(p.user_note)}</span></div>}
              {str(p.review_reason) && <div className="text-[11.5px] text-[#FCD34D]">রিভিউ কারণ: {str(p.review_reason)}</div>}
              {isHttps(shot) && <a href={shot} target="_blank" rel="noopener noreferrer nofollow" className="text-[12px] text-primary-light underline">Screenshot দেখুন</a>}
              {canReview && (
                <div className="flex gap-2 pt-1">
                  <button className="btn-success !w-auto px-4 !py-2" onClick={() => { setNote(''); setErr(null); setDecision({ kind: 'approve', orderId: id }) }}>অনুমোদন</button>
                  <button className="btn-ghost !w-auto px-4 !py-2" onClick={() => { setNote(''); setErr(null); setDecision({ kind: 'reject', orderId: id }) }}>বাতিল</button>
                  <button className="btn-ghost !w-auto px-4 !py-2 disabled:opacity-50" disabled={reverifying === id} onClick={() => void reverify(id)}>আবার যাচাই</button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {list.hasMore && <LoadMoreButton onClick={list.more} loading={list.loading} />}

      <ConfirmSheet
        open={!!decision}
        title={decision?.kind === 'approve' ? 'Payment অনুমোদন করবেন?' : 'Payment বাতিল করবেন?'}
        confirmLabel={decision?.kind === 'approve' ? 'অনুমোদন করুন' : 'বাতিল করুন'}
        loading={busy}
        onConfirm={() => void confirm()}
        onCancel={() => setDecision(null)}
      >
        <p className="text-[12px] text-[#9CA3AF]">
          {decision?.kind === 'approve'
            ? 'অনুমোদন করলে ব্যবহারকারী সঙ্গে সঙ্গে Access পাবেন। শুধু Payment সত্যিই পেয়ে থাকলে অনুমোদন করুন।'
            : 'বাতিল করলে এই Order-এ Access দেওয়া হবে না।'}
        </p>
        <Field label="Admin নোট (ঐচ্ছিক)"><textarea className={inputCls} rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <ErrorBanner message={err} />
      </ConfirmSheet>
    </div>
  )
}

function AllOrders() {
  const [statuses, setStatuses] = useState<string[]>([])
  const [status, setStatus] = useState('')
  const [ctype, setCtype] = useState<'' | 'video' | 'package'>('')
  const [userId, setUserId] = useState('')
  const [userFilter, setUserFilter] = useState('')
  const list = useAdminList<AdminRecord>(
    (p) => adminConfigApi.orders({ status: status || undefined, content_type: ctype || undefined, user_id: userFilter || undefined, page: p }),
    [status, ctype, userFilter],
  )

  useEffect(() => { loadSchema().then((s) => setStatuses(s.modules.orders.choices?.statuses ?? [])).catch(() => setStatuses([])) }, [])

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <FilterChip active={status === ''} onClick={() => setStatus('')}>সব Status</FilterChip>
        {statuses.map((s) => <FilterChip key={s} active={status === s} onClick={() => setStatus(s)}>{s}</FilterChip>)}
      </div>
      <div className="flex flex-wrap gap-2">
        <FilterChip active={ctype === ''} onClick={() => setCtype('')}>ভিডিও + প্যাকেজ</FilterChip>
        <FilterChip active={ctype === 'video'} onClick={() => setCtype('video')}>ভিডিও</FilterChip>
        <FilterChip active={ctype === 'package'} onClick={() => setCtype('package')}>প্যাকেজ</FilterChip>
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setUserFilter(userId.trim()) }}>
        <input className={inputCls} placeholder="User ID দিয়ে খুঁজুন" value={userId} onChange={(e) => setUserId(e.target.value)} />
        <button type="submit" className="btn-ghost !w-auto px-4">খুঁজুন</button>
      </form>
      <p className="text-[12px] text-[#9CA3AF]">মোট: {fmtCount(list.total)}</p>
      {list.error && list.items.length === 0 ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading && list.items.length === 0 ? (
        <Skeleton className="h-[96px] rounded-[12px]" />
      ) : list.items.length === 0 ? <EmptyState icon="🧾" title="কোনো Order নেই" /> : (
        <ul className="flex flex-col gap-2">
          {list.items.map((o) => (
            <li key={o.id} className="card-base flex flex-col gap-1 p-3">
              <div className="flex items-center justify-between gap-2">
                <Badge variant={STATUS_VARIANT[str(o.status)] ?? 'gray'}>{str(o.status) || '—'}</Badge>
                <span className="text-[11px] text-[#6B7280]">{fmtDateTime(o.created_at)}</span>
              </div>
              <div className="break-all text-[12px] text-[#9CA3AF]">Order: <span className="text-white">{o.id}</span></div>
              <div className="text-[12px] text-[#9CA3AF]">User: <span className="text-white">{str(o.user_id)}</span> · {str(o.content_type)}: <span className="break-all text-white">{str(o.content_id)}</span></div>
              <div className="text-[12px] text-[#9CA3AF]">
                মূল {fmtMoney(num(o.amount_bdt))}
                {num(o.discount_bdt) ? <> − ছাড় {fmtMoney(num(o.discount_bdt))}{str(o.coupon_code) && ` (${str(o.coupon_code)})`}</> : null}
                {' = '}<span className="text-white">{fmtMoney(num(o.final_bdt))}</span>
                {num(o.final_usdt) !== null && <> · {num(o.final_usdt)} USDT</>} · {str(o.payment_method_type) || '—'}
              </div>
              {str(o.completed_at) && <div className="text-[11.5px] text-[#6EE7B7]">সম্পন্ন: {fmtDateTime(o.completed_at)}</div>}
            </li>
          ))}
        </ul>
      )}
      {list.hasMore && <LoadMoreButton onClick={list.more} loading={list.loading} />}
    </div>
  )
}

export default function Orders() {
  const admin = useAdminStore((s) => s.admin)
  const canReview = can(admin, 'payments.review')
  const canView = can(admin, 'orders.view')
  const [tab, setTab] = useState<'review' | 'all'>(canReview ? 'review' : 'all')
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">Order ও Payment</h1>
      <div className="flex gap-2">
        {canReview && <FilterChip active={tab === 'review'} onClick={() => setTab('review')}>Payment রিভিউ</FilterChip>}
        {canView && <FilterChip active={tab === 'all'} onClick={() => setTab('all')}>সব Order</FilterChip>}
      </div>
      {tab === 'review' && canReview ? <PendingReview /> : canView ? <AllOrders /> : null}
    </div>
  )
}
