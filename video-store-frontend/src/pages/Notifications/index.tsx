import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { userApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import type { Notification } from '@/types'
import { useUserStore } from '@/store'
import { SubHeader, PageWrapper } from '@/components/layout'
import { Skeleton, EmptyState, ErrorState, LoadMoreButton, FilterChip, toast } from '@/components/ui'
import { formatDate } from '@/utils'

// Notifications (Backend: GET /user/notifications, POST /user/notifications/read).
// The Backend page size is 30 and it sends no `has_more`, so a full page is the
// signal that another page may exist.
const PAGE_SIZE = 30

// action_type values the Backend actually creates: open_video, open_package,
// open_order. Anything else is shown as plain text, not as a dead link.
function targetOf(n: Notification): string | null {
  if (!n.action_type || !n.action_id) return null
  const id = encodeURIComponent(n.action_id)
  switch (n.action_type) {
    case 'open_video':   return `/videos/${id}`
    case 'open_package': return `/packages/${id}`
    case 'open_order':   return `/payment/${id}`   // Payment page routes by real order status
    default:             return null
  }
}

const ICON: Record<string, string> = {
  purchase_success: '✅', payment_rejected: '❌', referral_reward: '🎁',
}

export default function NotificationsPage() {
  const navigate = useNavigate()
  const { setNotifications } = useUserStore()
  const [items, setItems] = useState<Notification[]>([])
  const [unread, setUnread] = useState(0)
  const [onlyUnread, setOnlyUnread] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const pageRef = useRef(1)
  const reqRef = useRef(0)

  const load = useCallback(async (reset: boolean) => {
    const req = ++reqRef.current
    const page = reset ? 1 : pageRef.current + 1
    reset ? setLoading(true) : setLoadingMore(true)
    setError(null)
    try {
      const res = await userApi.notifications({ page, unread_only: onlyUnread || undefined })
      if (req !== reqRef.current) return
      const batch = res.data.notifications
      setItems((prev) => {
        if (reset) return batch
        const seen = new Set(prev.map((i) => i.id))
        return [...prev, ...batch.filter((i) => !seen.has(i.id))]
      })
      setUnread(res.data.unread_count)
      setHasMore(batch.length >= PAGE_SIZE)
      pageRef.current = page
    } catch (e) {
      if (req === reqRef.current) setError(getErrorMessage(e, 'Notification লোড করা যায়নি।'))
    } finally {
      if (req === reqRef.current) { setLoading(false); setLoadingMore(false) }
    }
  }, [onlyUnread])

  useEffect(() => { void load(true) }, [load])

  // Keep the header badge in sync with what this page knows.
  useEffect(() => { setNotifications([], unread) }, [unread, setNotifications])

  async function markRead(ids: string[] | 'all') {
    try {
      await userApi.markRead(ids)
      setItems((prev) => prev.map((n) => (ids === 'all' || ids.includes(n.id) ? { ...n, is_read: true } : n)))
      setUnread((u) => (ids === 'all' ? 0 : Math.max(0, u - ids.filter((id) => items.find((n) => n.id === id && !n.is_read)).length)))
    } catch (e) {
      toast(getErrorMessage(e, 'পড়া হিসেবে চিহ্নিত করা যায়নি।'), 'error')
    }
  }

  function onTap(n: Notification) {
    if (!n.is_read) void markRead([n.id])
    const to = targetOf(n)
    if (to) navigate(to)
  }

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader
        title="Notifications"
        right={unread > 0 ? (
          <button onClick={() => void markRead('all')} className="text-[11px] text-primary font-semibold">সব পড়া হয়েছে</button>
        ) : undefined}
      />
      <div className="px-4 pt-3 flex gap-2">
        <FilterChip active={!onlyUnread} onClick={() => setOnlyUnread(false)}>সব</FilterChip>
        <FilterChip active={onlyUnread} onClick={() => setOnlyUnread(true)}>অপঠিত{unread > 0 ? ` (${unread})` : ''}</FilterChip>
      </div>

      <div className="px-4 py-3 space-y-2">
        {loading && Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[72px] w-full rounded-[12px]" />)}

        {!loading && error && items.length === 0 && <ErrorState message={error} onRetry={() => void load(true)} />}

        {!loading && !error && items.length === 0 && (
          <EmptyState icon="🔔" title={onlyUnread ? 'কোনো অপঠিত Notification নেই' : 'এখনো কোনো Notification নেই'} description="Payment, Access ও Reward-এর খবর এখানে আসবে।" />
        )}

        {!loading && items.map((n) => {
          const to = targetOf(n)
          return (
            <button
              key={n.id}
              onClick={() => onTap(n)}
              className={`w-full text-left flex gap-3 rounded-[12px] border px-3 py-[11px] ${n.is_read ? 'bg-card border-border' : 'bg-primary/8 border-primary/25'}`}
            >
              <span className="text-[18px] leading-none mt-[2px]" aria-hidden>{ICON[n.type] ?? '🔔'}</span>
              <span className="flex-1 min-w-0">
                <span className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold text-white truncate">{n.title}</span>
                  {!n.is_read && <span className="w-[7px] h-[7px] rounded-full bg-primary flex-shrink-0" aria-label="অপঠিত" />}
                </span>
                <span className="block text-[11px] text-[#9CA3AF] leading-[1.5] mt-[2px] break-words">{n.body}</span>
                <span className="block text-[10px] text-[#6B7280] mt-1">{formatDate(n.created_at)}{to ? ' · খুলতে ট্যাপ করুন' : ''}</span>
              </span>
            </button>
          )
        })}

        {!loading && hasMore && <LoadMoreButton onClick={() => void load(false)} loading={loadingMore} />}
        {!loading && error && items.length > 0 && <p className="text-[11px] text-[#FCA5A5] text-center">{error}</p>}
      </div>
    </PageWrapper>
  )
}
