import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Badge, ErrorState, Skeleton } from '@/components/ui'
import { adminConfigApi, type AdminDashboard, type AdminRecord } from '../configApi'
import { Card, Thumb } from '../ui'
import { bool, errorText, fmtCount, fmtDateTime, fmtMoney, num, str } from '../util'

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[12px] border border-border bg-card2 px-3 py-2.5">
      <div className="text-[11px] text-[#9CA3AF]">{label}</div>
      <div className="mt-0.5 text-[18px] font-bold text-white">{value}</div>
      {hint && <div className="text-[10.5px] text-[#6B7280]">{hint}</div>}
    </div>
  )
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{children}</div>
}

const STATUS_LABEL: Record<string, string> = {
  awaiting_payment: 'পেমেন্টের অপেক্ষায়', payment_submitted: 'পেমেন্ট জমা', under_review: 'রিভিউতে',
  completed: 'সম্পন্ন', failed: 'ব্যর্থ', expired: 'মেয়াদোত্তীর্ণ', refunded: 'রিফান্ড',
}

function statusVariant(s: string): 'green' | 'orange' | 'red' | 'gray' {
  if (s === 'completed') return 'green'
  if (s === 'payment_submitted' || s === 'under_review' || s === 'awaiting_payment') return 'orange'
  if (s === 'failed') return 'red'
  return 'gray'
}

export default function Dashboard() {
  const [data, setData] = useState<AdminDashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    adminConfigApi.dashboard()
      .then((d) => setData(d))
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !data) {
    return <div className="flex flex-col gap-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[110px] rounded-[12px]" />)}</div>
  }
  if (error && !data) return <ErrorState message={error} onRetry={load} />
  if (!data) return null

  const { orders, users, catalog, support } = data
  const rev = orders.revenue_bdt

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-[16px] font-bold text-white">ড্যাশবোর্ড</h1>
        <button className="btn-ghost !w-auto px-4 !py-2" onClick={load} disabled={loading}>{loading ? '…' : 'রিফ্রেশ'}</button>
      </div>
      {error && <p className="text-[12px] text-[#FCA5A5]">{error}</p>}

      <Card title="ইউজার">
        <Grid>
          <Stat label="মোট ইউজার" value={fmtCount(users.total)} />
          <Stat label="নতুন (৭ দিন)" value={fmtCount(users.new_last_7_days)} />
          <Stat label="ব্যান করা" value={fmtCount(users.banned)} />
        </Grid>
      </Card>

      <Card title="ভিডিও">
        <Grid>
          <Stat label="মোট ভিডিও" value={fmtCount(catalog.videos_total)} />
          <Stat label="Published" value={fmtCount(catalog.videos_published)} />
          <Stat label="Hidden" value={fmtCount(catalog.videos_hidden)} />
          <Stat label="Featured" value={fmtCount(catalog.videos_featured)} />
          <Stat label="Trending" value={fmtCount(catalog.videos_trending)} />
          <Stat label="ক্যাটাগরি" value={`${fmtCount(catalog.categories_visible)} / ${fmtCount(catalog.categories_total)}`} hint="দৃশ্যমান / মোট" />
        </Grid>
      </Card>

      <Card title={`পারচেজ (গত ${orders.window_days} দিন)`}>
        <Grid>
          <Stat label="আজকের অর্ডার" value={fmtCount(orders.orders_today)} />
          <Stat label="রিভিউয়ের অপেক্ষায়" value={fmtCount(orders.awaiting_review)} />
          <Stat label="মোট অর্ডার" value={fmtCount(orders.orders_in_window)} />
          <Stat label="আজকের আয়" value={fmtMoney(rev.today)} />
          <Stat label="৭ দিনের আয়" value={fmtMoney(rev.last_7_days)} />
          <Stat label="৩০ দিনের আয়" value={fmtMoney(rev.last_30_days)} />
        </Grid>
        {orders.truncated && (
          <p className="text-[11px] text-[#FCD34D]">অর্ডার বেশি হওয়ায় আয়ের সংখ্যা প্রকৃত সংখ্যার চেয়ে কম হতে পারে।</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(orders.by_status as Record<string, number>).filter(([, n]) => n > 0).map(([s, n]) => (
            <Badge key={s} variant={statusVariant(s)}>{STATUS_LABEL[s] ?? s}: {n}</Badge>
          ))}
        </div>
      </Card>

      <Card title="প্যাকেজ ও সাপোর্ট">
        <Grid>
          <Stat label="প্যাকেজ (Published)" value={`${fmtCount(catalog.packages_published)} / ${fmtCount(catalog.packages_total)}`} />
          <Stat label="খোলা টিকেট" value={fmtCount(support.open_tickets)} />
        </Grid>
      </Card>

      {data.top_videos && data.top_videos.length > 0 && (
        <Card title="সর্বাধিক বিক্রিত ভিডিও">
          <ul className="flex flex-col gap-2">
            {data.top_videos.map((v) => (
              <li key={v.id}>
                <Link to={`/admin/videos/${encodeURIComponent(v.id)}`} className="flex items-center gap-3">
                  <Thumb url={str(v.thumbnail_url)} className="h-[38px] w-[64px] shrink-0 rounded-[6px]" />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-white">{str(v.title) || v.id}</span>
                  <span className="shrink-0 text-[11px] text-[#9CA3AF]">
                    {fmtCount(num(v.purchase_count))} বিক্রি · {fmtCount(num(v.view_count))} ভিউ
                  </span>
                  {!bool(v.is_published) && <Badge variant="gray">Hidden</Badge>}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.recent_orders && data.recent_orders.length > 0 && (
        <Card title="সাম্প্রতিক অর্ডার">
          <ul className="flex flex-col gap-2">
            {data.recent_orders.map((o) => <OrderRow key={o.id} o={o} />)}
          </ul>
        </Card>
      )}

      {data.recent_activity && data.recent_activity.length > 0 && (
        <Card title="সাম্প্রতিক কার্যক্রম">
          <ul className="flex flex-col gap-2">
            {data.recent_activity.map((a) => (
              <li key={a.id} className="flex items-start justify-between gap-3 text-[12px]">
                <span className="min-w-0">
                  <span className="font-medium text-white">{str(a.action)}</span>
                  <span className="text-[#9CA3AF]"> · {str(a.target_type)}{str(a.target_id) ? ` ${str(a.target_id)}` : ''}</span>
                  <span className="block text-[11px] text-[#6B7280]">{str(a.performed_by) || 'system'}</span>
                </span>
                <span className="shrink-0 text-[11px] text-[#6B7280]">{fmtDateTime(a.created_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <p className="text-center text-[11px] text-[#6B7280]">আপডেট: {fmtDateTime(data.generated_at)}</p>
    </div>
  )
}

function OrderRow({ o }: { o: AdminRecord }) {
  const status = str(o.status)
  return (
    <li className="flex items-center justify-between gap-3 text-[12px]">
      <span className="min-w-0">
        <span className="font-medium text-white">{str(o.content_type) || 'order'} · {str(o.content_id) || o.id}</span>
        <span className="block text-[11px] text-[#6B7280]">{fmtDateTime(o.created_at)}</span>
      </span>
      <span className="flex shrink-0 items-center gap-2">
        <span className="text-white">{fmtMoney(num(o.final_bdt))}</span>
        <Badge variant={statusVariant(status)}>{STATUS_LABEL[status] ?? (status || '—')}</Badge>
      </span>
    </li>
  )
}
