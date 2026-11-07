import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, ConfirmSheet, EmptyState, ErrorState, FilterChip, LoadMoreButton, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord } from '../configApi'
import { can, useAdminStore } from '../store'
import { Thumb } from '../ui'
import { bool, errorText, fmtCount, num, str } from '../util'

const LIMIT = 20
type Filter = 'all' | 'published' | 'hidden'

function durationLabel(p: AdminRecord): string {
  if (str(p.duration_type) !== 'custom') return 'Lifetime'
  const h = num(p.duration_hours) ?? 0
  return h % 24 === 0 && h > 0 ? `${h / 24} দিন` : `${h} ঘণ্টা`
}

export default function Packages() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'videos.manage')

  const [items, setItems] = useState<AdminRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [target, setTarget] = useState<AdminRecord | null>(null)
  const [busy, setBusy] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const seq = useRef(0)

  const load = useCallback((p: number, replace: boolean) => {
    const my = ++seq.current
    setLoading(true)
    setError(null)
    adminConfigApi.list('/admin/packages', { published: filter === 'all' ? undefined : filter === 'published', page: p, limit: LIMIT })
      .then((r) => {
        if (my !== seq.current) return
        setItems((prev) => (replace ? r.items : [...prev, ...r.items]))
        setTotal(r.total)
        setHasMore(r.has_more)
        setPage(p)
      })
      .catch((e) => { if (my === seq.current) setError(errorText(e)) })
      .finally(() => { if (my === seq.current) setLoading(false) })
  }, [filter])

  useEffect(() => { load(1, true) }, [load])

  async function confirmToggle() {
    if (!target) return
    const next = !bool(target.is_published)
    setBusy(true)
    try {
      const updated = await adminConfigApi.setPublished('/admin/packages', target.id, next)
      setItems((prev) => prev.map((p) => (p.id === target.id ? { ...p, ...updated } : p)))
      toast(next ? 'প্যাকেজ Publish হয়েছে।' : 'প্যাকেজ Hide করা হয়েছে।', 'success')
      setTarget(null)
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  // Featured toggle: PUT with only the changed field (server merges and re-validates the whole package).
  async function toggleFeatured(p: AdminRecord) {
    setBusyId(p.id)
    try {
      const updated = await adminConfigApi.update('/admin/packages', p.id, { is_featured: !bool(p.is_featured) })
      setItems((prev) => prev.map((x) => (x.id === p.id ? { ...x, ...updated } : x)))
      toast(bool(updated.is_featured) ? 'Featured করা হয়েছে।' : 'Featured বন্ধ হয়েছে।', 'success')
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusyId(null)
    }
  }

  const publishing = target ? !bool(target.is_published) : false

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[16px] font-bold text-white">প্যাকেজ {!loading || items.length ? <span className="text-[12px] font-normal text-[#9CA3AF]">({fmtCount(total)})</span> : null}</h1>
        {canManage && <Link to="/admin/packages/new" className="btn-primary !w-auto px-4 !py-2.5 !text-[13px]">+ নতুন প্যাকেজ</Link>}
      </div>
      <div className="flex gap-2">
        <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>সব</FilterChip>
        <FilterChip active={filter === 'published'} onClick={() => setFilter('published')}>Published</FilterChip>
        <FilterChip active={filter === 'hidden'} onClick={() => setFilter('hidden')}>Hidden</FilterChip>
      </div>

      {error && items.length === 0 ? (
        <ErrorState message={error} onRetry={() => load(1, true)} />
      ) : loading && items.length === 0 ? (
        <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[84px] rounded-[12px]" />)}</div>
      ) : items.length === 0 ? (
        <EmptyState icon="📦" title="কোনো প্যাকেজ নেই" description={filter !== 'all' ? 'ফিল্টার বদলে দেখুন।' : 'প্রথম প্যাকেজ তৈরি করুন।'} />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((p) => {
            const published = bool(p.is_published)
            const discount = num(p.discount_percentage) ?? 0
            return (
              <li key={p.id} className="card-base flex flex-col gap-2 p-2.5">
                <Link to={`/admin/packages/${encodeURIComponent(p.id)}`} className="flex min-w-0 items-center gap-3">
                  <Thumb url={str(p.thumbnail_url)} className="h-[52px] w-[88px] shrink-0 rounded-[8px]" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold text-white">{str(p.name) || p.id}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1">
                      <Badge variant={published ? 'green' : 'gray'}>{published ? 'Published' : 'Hidden'}</Badge>
                      {bool(p.is_featured) && <Badge variant="orange">Featured</Badge>}
                      <Badge variant="blue">{fmtCount(num(p.video_count))} ভিডিও</Badge>
                      <Badge variant="purple">{durationLabel(p)}</Badge>
                      {!bool(p.purchase_enabled) && <Badge variant="red">Purchase বন্ধ</Badge>}
                      {!bool(p.ads_unlock_enabled) && <Badge variant="gray">Ads Unlock বন্ধ</Badge>}
                    </span>
                    <span className="mt-1 block text-[11px] text-[#6B7280]">
                      ৳{fmtCount(num(p.price_bdt))}
                      {discount > 0 ? ` · ${discount}% ছাড় (আগে ৳${fmtCount(num(p.original_price_bdt))})` : ''}
                      {` · ${fmtCount(num(p.purchase_count))} বিক্রি`}
                    </span>
                  </span>
                </Link>
                {canManage && (
                  <div className="flex gap-2">
                    <button className="btn-ghost !py-2 !text-[12px]" disabled={busyId === p.id} onClick={() => void toggleFeatured(p)}>
                      {bool(p.is_featured) ? 'Featured বন্ধ' : 'Featured করুন'}
                    </button>
                    <button className="btn-ghost !py-2 !text-[12px]" onClick={() => setTarget(p)}>{published ? 'Hide' : 'Publish'}</button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {hasMore && <LoadMoreButton onClick={() => load(page + 1, false)} loading={loading} />}

      <ConfirmSheet
        open={target !== null}
        title={publishing ? 'প্যাকেজ Publish করবেন?' : 'প্যাকেজ Hide করবেন?'}
        confirmLabel={publishing ? 'Publish' : 'Hide'}
        loading={busy}
        onConfirm={confirmToggle}
        onCancel={() => setTarget(null)}
      >
        <p className="text-[13px] text-[#9CA3AF]">
          {publishing
            ? 'প্যাকেজটি অ্যাপে দেখা যাবে। খালি প্যাকেজ Publish হবে না।'
            : 'প্যাকেজটি অ্যাপে আর দেখা যাবে না। আগে যারা কিনেছে তাদের Access অপরিবর্তিত থাকবে।'}
        </p>
      </ConfirmSheet>
    </div>
  )
}
