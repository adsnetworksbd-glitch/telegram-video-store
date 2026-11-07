import { useState } from 'react'
import { Badge, EmptyState, ErrorState, LoadMoreButton, Skeleton } from '@/components/ui'
import { adminConfigApi, type AdminRecord } from '../configApi'
import { inputCls } from '../ui'
import { fmtCount, fmtDateTime, str } from '../util'
import { useAdminList } from '../useAdminList'

interface Filters { action: string; performed_by: string; target_type: string; target_id: string }
const EMPTY: Filters = { action: '', performed_by: '', target_type: '', target_id: '' }

export default function Audit() {
  const [draft, setDraft] = useState<Filters>(EMPTY)
  const [applied, setApplied] = useState<Filters>(EMPTY)
  const [open, setOpen] = useState<string | null>(null)
  const list = useAdminList<AdminRecord>(
    (p) => adminConfigApi.auditLogs({
      action: applied.action || undefined, performed_by: applied.performed_by || undefined,
      target_type: applied.target_type || undefined, target_id: applied.target_id || undefined, page: p,
    }),
    [applied],
  )
  const bind = (k: keyof Filters, label: string) => (
    <input className={inputCls} placeholder={label} value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
  )

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">Audit Log <span className="text-[12px] font-normal text-[#9CA3AF]">({fmtCount(list.total)})</span></h1>
      <p className="text-[11.5px] text-[#6B7280]">Admin-এর প্রতিটি কাজ এখানে সংরক্ষিত থাকে। এটি শুধু পড়া যায়, মোছা বা বদলানো যায় না; গোপন তথ্য আড়াল করা থাকে।</p>
      <form className="grid grid-cols-2 gap-2" onSubmit={(e) => { e.preventDefault(); setApplied({ action: draft.action.trim(), performed_by: draft.performed_by.trim(), target_type: draft.target_type.trim(), target_id: draft.target_id.trim() }) }}>
        {bind('action', 'Action (যেমন payment_approved)')}
        {bind('performed_by', 'Admin username')}
        {bind('target_type', 'Target ধরন')}
        {bind('target_id', 'Target ID')}
        <button type="submit" className="btn-secondary col-span-2">ফিল্টার করুন</button>
      </form>
      {list.error && list.items.length === 0 ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading && list.items.length === 0 ? (
        <Skeleton className="h-[72px] rounded-[12px]" />
      ) : list.items.length === 0 ? <EmptyState icon="📜" title="কোনো Log নেই" /> : (
        <ul className="flex flex-col gap-2">
          {list.items.map((a) => (
            <li key={a.id} className="card-base flex flex-col gap-1 p-3">
              <button className="flex flex-col gap-1 text-left" onClick={() => setOpen(open === a.id ? null : a.id)}>
                <span className="flex items-center justify-between gap-2">
                  <Badge variant="blue">{str(a.action)}</Badge>
                  <span className="text-[11px] text-[#6B7280]">{fmtDateTime(a.created_at)}</span>
                </span>
                <span className="text-[12px] text-[#9CA3AF]">{str(a.performed_by) || '—'} → {str(a.target_type)} <span className="break-all text-white">{str(a.target_id)}</span></span>
              </button>
              {open === a.id && (
                <div className="flex flex-col gap-1.5 border-t border-border pt-2 text-[11px]">
                  {str(a.ip_address) && <div className="text-[#6B7280]">IP: {str(a.ip_address)}</div>}
                  <div className="text-[#9CA3AF]">আগে</div>
                  <pre className="overflow-x-auto rounded-[8px] bg-card p-2 text-[#D1D5DB]">{JSON.stringify(a.snapshot_before ?? null, null, 2)}</pre>
                  <div className="text-[#9CA3AF]">পরে</div>
                  <pre className="overflow-x-auto rounded-[8px] bg-card p-2 text-[#D1D5DB]">{JSON.stringify(a.snapshot_after ?? null, null, 2)}</pre>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {list.hasMore && <LoadMoreButton onClick={list.more} loading={list.loading} />}
    </div>
  )
}
