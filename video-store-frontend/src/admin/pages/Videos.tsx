import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, ConfirmSheet, EmptyState, ErrorState, FilterChip, LoadMoreButton, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord } from '../configApi'
import { can, useAdminStore } from '../store'
import { Thumb, inputCls } from '../ui'
import { bool, errorText, fmtCount, fmtDuration, num, str } from '../util'

const LIMIT = 20
type Filter = 'all' | 'published' | 'hidden'

export default function Videos() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'videos.manage')

  const [items, setItems] = useState<AdminRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [target, setTarget] = useState<AdminRecord | null>(null)   // video awaiting hide/publish confirmation
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 400)
    return () => clearTimeout(t)
  }, [query])

  const load = useCallback((p: number, replace: boolean) => {
    const my = ++seq.current
    setLoading(true)
    setError(null)
    adminConfigApi.list('/admin/videos', {
      q: debounced || undefined,
      published: filter === 'all' ? undefined : filter === 'published',
      page: p, limit: LIMIT,
    })
      .then((r) => {
        if (my !== seq.current) return           // a newer request superseded this one
        setItems((prev) => (replace ? r.items : [...prev, ...r.items]))
        setTotal(r.total)
        setHasMore(r.has_more)
        setPage(p)
      })
      .catch((e) => { if (my === seq.current) setError(errorText(e)) })
      .finally(() => { if (my === seq.current) setLoading(false) })
  }, [debounced, filter])

  useEffect(() => { load(1, true) }, [load])

  async function confirmToggle() {
    if (!target) return
    const next = !bool(target.is_published)
    setBusy(true)
    try {
      const updated = await adminConfigApi.setPublished('/admin/videos', target.id, next)
      setItems((prev) => prev.map((v) => (v.id === target.id ? { ...v, ...updated } : v)))
      toast(next ? 'ভিডিও Publish হয়েছে।' : 'ভিডিও Hide করা হয়েছে।', 'success')
      setTarget(null)
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  const publishing = target ? !bool(target.is_published) : false

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[16px] font-bold text-white">ভিডিও {!loading || items.length ? <span className="text-[12px] font-normal text-[#9CA3AF]">({fmtCount(total)})</span> : null}</h1>
        {canManage && <Link to="/admin/videos/new" className="btn-primary !w-auto px-4 !py-2.5 !text-[13px]">+ নতুন ভিডিও</Link>}
      </div>

      <input
        className={inputCls}
        type="search"
        placeholder="টাইটেল বা ID দিয়ে খুঁজুন"
        value={query}
        maxLength={100}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="flex gap-2">
        <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>সব</FilterChip>
        <FilterChip active={filter === 'published'} onClick={() => setFilter('published')}>Published</FilterChip>
        <FilterChip active={filter === 'hidden'} onClick={() => setFilter('hidden')}>Hidden</FilterChip>
      </div>

      {error && items.length === 0 ? (
        <ErrorState message={error} onRetry={() => load(1, true)} />
      ) : loading && items.length === 0 ? (
        <div className="flex flex-col gap-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[76px] rounded-[12px]" />)}</div>
      ) : items.length === 0 ? (
        <EmptyState icon="🎬" title="কোনো ভিডিও পাওয়া যায়নি" description={debounced || filter !== 'all' ? 'ফিল্টার বদলে দেখুন।' : 'প্রথম ভিডিও যোগ করুন।'} />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((v) => {
            const published = bool(v.is_published)
            return (
              <li key={v.id} className="card-base flex items-center gap-3 p-2.5">
                <Link to={`/admin/videos/${encodeURIComponent(v.id)}`} className="flex min-w-0 flex-1 items-center gap-3">
                  <Thumb url={str(v.thumbnail_url)} className="h-[52px] w-[88px] shrink-0 rounded-[8px]" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold text-white">{str(v.title) || v.id}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1">
                      <Badge variant={published ? 'green' : 'gray'}>{published ? 'Published' : 'Hidden'}</Badge>
                      {str(v.quality) && <Badge variant="blue">{str(v.quality)}</Badge>}
                      {bool(v.is_free) && <Badge variant="purple">Free</Badge>}
                      {bool(v.is_featured) && <Badge variant="orange">Featured</Badge>}
                      {bool(v.is_trending) && <Badge variant="orange">Trending</Badge>}
                      {!bool(v.has_source) && <Badge variant="red">Source নেই</Badge>}
                    </span>
                    <span className="mt-1 block text-[11px] text-[#6B7280]">
                      {bool(v.is_free) ? 'ফ্রি' : `৳${fmtCount(num(v.price_bdt))}`} · {fmtDuration(num(v.duration_seconds))} · {fmtCount(num(v.view_count))} ভিউ · {fmtCount(num(v.purchase_count))} বিক্রি
                    </span>
                  </span>
                </Link>
                {canManage && (
                  <button className="btn-ghost !w-auto shrink-0 px-3 !py-2 !text-[12px]" onClick={() => setTarget(v)}>
                    {published ? 'Hide' : 'Publish'}
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {hasMore && <LoadMoreButton onClick={() => load(page + 1, false)} loading={loading} />}

      <ConfirmSheet
        open={target !== null}
        title={publishing ? 'ভিডিও Publish করবেন?' : 'ভিডিও Hide (Archive) করবেন?'}
        confirmLabel={publishing ? 'Publish' : 'Hide'}
        loading={busy}
        onConfirm={confirmToggle}
        onCancel={() => setTarget(null)}
      >
        <p className="text-[13px] text-[#9CA3AF]">
          {publishing
            ? 'ভিডিওটি অ্যাপে দেখা যাবে। Source লিংক না থাকলে Publish হবে না।'
            : 'ভিডিওটি অ্যাপে আর দেখা যাবে না। কোনো ডেটা মুছবে না — পরে আবার Publish করা যাবে।'}
        </p>
      </ConfirmSheet>
    </div>
  )
}
