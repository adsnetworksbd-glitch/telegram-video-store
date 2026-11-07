import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { entitlementsApi, accessApi } from '@/api'
import type { Entitlement } from '@/types'
import { SubHeader, PageWrapper } from '@/components/layout'
import { Skeleton, EmptyState, ErrorState, FilterChip, LoadMoreButton } from '@/components/ui'
import { AccessSourceBadge } from '@/components/access'
import { usePaginatedList } from '@/hooks/usePaginatedList'
import { useContentLookup } from '@/hooks/useContentLookup'
import { useOpenSource } from '@/hooks/useOpenSource'
import { formatTimeLeft, formatDate, cx } from '@/utils'

// ─── My Purchases ─────────────────────────────────────────────────────────────
// Read-only history: there is intentionally no delete / remove action anywhere.
// Active vs Expired is decided by the Backend (`status`, derived from expiry).

type Tab = 'video' | 'package'
type SubTab = 'active' | 'expired'

export default function MyPurchasesPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('video')
  const [subTab, setSubTab] = useState<SubTab>('active')
  const list = usePaginatedList<Entitlement>(
    (page) => entitlementsApi.list({ type: tab, status: subTab, page, limit: 20 }).then((r) => r.data),
    [tab, subTab],
  )
  // If the Backend refuses to open a source (the access just expired), reload
  // the list so Active / Expired reflect the Backend again.
  const { openingId, open } = useOpenSource(list.reload)

  const lookup = useContentLookup(list.items)

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="📋 আমার Purchases" />
      <div className="px-4 pt-3">
        {/* Purchased videos / purchased packages */}
        <div className="flex bg-card border border-border rounded-[10px] p-[3px] mb-3" role="tablist">
          {(['video', 'package'] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cx(
                'flex-1 py-[7px] rounded-[7px] text-[11px] font-semibold transition-all border',
                tab === t ? 'bg-primary/15 text-primary border-primary/30' : 'text-[#6B7280] border-transparent',
              )}
            >{t === 'video' ? 'ভিডিও' : 'প্যাকেজ'}</button>
          ))}
        </div>

        {/* Active / expired */}
        <div className="flex gap-2 mb-3">
          <FilterChip active={subTab === 'active'} onClick={() => setSubTab('active')}>✅ Active</FilterChip>
          <FilterChip active={subTab === 'expired'} onClick={() => setSubTab('expired')}>❌ Expired</FilterChip>
        </div>
      </div>

      {list.error && list.items.length === 0 ? (
        <ErrorState message={list.errorMessage ?? undefined} onRetry={list.reload} />
      ) : list.loading ? (
        <div className="px-4 space-y-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[58px] w-full rounded-[11px]" />)}
        </div>
      ) : list.items.length === 0 ? (
        <EmptyState
          icon={subTab === 'active' ? '🎬' : '📂'}
          title={subTab === 'active' ? 'কোনো Active Access নেই' : 'কোনো Expired Item নেই'}
          description={tab === 'video' ? 'ভিডিও কিনলে বা বিজ্ঞাপন দেখে Unlock করলে এখানে দেখা যাবে।' : 'Package কিনলে বা Unlock করলে এখানে দেখা যাবে।'}
        />
      ) : (
        <>
          <div className="px-4 space-y-2">
            {list.items.map((item) => {
              const info = lookup(item.content_type, item.content_id)
              return (
                <PurchaseRow
                  key={item.id}
                  item={item}
                  title={info?.title}
                  thumb={info?.thumbnail_url}
                  opening={openingId === item.content_id}
                  onOpen={() => void open(item.content_id)}
                  onGo={() => navigate(`/${item.content_type === 'video' ? 'videos' : 'packages'}/${item.content_id}`)}
                />
              )
            })}
          </div>
          {list.error && <p className="text-center text-[11px] text-[#FCA5A5] mt-3">আরও লোড করা যায়নি।</p>}
          {list.hasMore && <LoadMoreButton onClick={list.loadMore} loading={list.loadingMore} />}
        </>
      )}
    </PageWrapper>
  )
}

// ─── Row ──────────────────────────────────────────────────────────────────────
interface RowProps {
  item: Entitlement
  title?: string
  thumb?: string
  opening: boolean
  onOpen: () => void
  onGo: () => void
}

function PurchaseRow({ item, title, thumb, opening, onOpen, onGo }: RowProps) {
  const isVideo = item.content_type === 'video'
  const active = item.status === 'active'

  // An expired entry can still be usable through ANOTHER valid source
  // (e.g. a Lifetime purchase). The Backend decides — we only ask.
  const [otherAccess, setOtherAccess] = useState<boolean | null>(null)
  useEffect(() => {
    if (active) return
    let alive = true
    const check = isVideo ? accessApi.checkVideo(item.content_id) : accessApi.checkPackage(item.content_id)
    check.then((r) => { if (alive) setOtherAccess(r.data.granted) }).catch(() => { if (alive) setOtherAccess(null) })
    return () => { alive = false }
  }, [active, isVideo, item.content_id])

  const canOpenNow = active || otherAccess === true

  return (
    <div className="flex items-center gap-3 bg-card border border-border rounded-[11px] p-[10px]">
      <div className="w-[58px] h-[36px] rounded-[7px] bg-surface flex-shrink-0 flex items-center justify-center overflow-hidden">
        {thumb
          ? <img src={thumb} className="w-full h-full object-cover" alt="" />
          : <span className="text-[14px]">{isVideo ? '🎬' : '📦'}</span>}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-[11px] font-semibold text-white truncate mb-[2px]">
          {title ?? (isVideo ? 'ভিডিও' : 'Package')}
        </p>
        <p className="text-[9px] text-[#6B7280] mb-[4px]">
          {formatDate(item.created_at)}
          {!isVideo && item.included_video_ids.length > 0 && ` · ${item.included_video_ids.length}টি ভিডিও`}
        </p>
        <div className="flex items-center gap-[5px] flex-wrap">
          <AccessSourceBadge source={item.access_source} />
          {active ? (
            <span className={cx(
              'inline-flex items-center text-[9px] font-bold px-[7px] py-[3px] rounded-[5px] border',
              item.is_lifetime
                ? 'bg-primary/10 text-[#93C5FD] border-primary/25'
                : 'bg-success/10 text-[#6EE7B7] border-success/25',
            )}>
              {item.is_lifetime ? '♾ Lifetime' : item.expires_at ? `⏰ ${formatTimeLeft(item.expires_at)}` : 'Active'}
            </span>
          ) : (
            <span className="inline-flex items-center text-[9px] font-bold px-[7px] py-[3px] rounded-[5px] border bg-danger/10 text-[#FCA5A5] border-danger/20">
              ✗ Expired{item.expires_at ? ` · ${formatDate(item.expires_at)}` : ''}
            </span>
          )}
        </div>
        {!active && otherAccess === true && (
          <p className="text-[9px] text-[#6EE7B7] mt-1">অন্য Access-এর মাধ্যমে এখনো দেখা যাবে</p>
        )}
      </div>

      {/* Open / Download source — videos only; packages open their video list */}
      {canOpenNow && isVideo && (
        <button
          onClick={onOpen}
          disabled={opening}
          className="px-[10px] py-[6px] rounded-[7px] bg-success/15 border border-success/25 text-[#6EE7B7] text-[10px] font-semibold flex-shrink-0 disabled:opacity-60"
        >
          {opening ? '...' : '▶ Open'}
        </button>
      )}
      {canOpenNow && !isVideo && (
        <button
          onClick={onGo}
          className="px-[10px] py-[6px] rounded-[7px] bg-success/15 border border-success/25 text-[#6EE7B7] text-[10px] font-semibold flex-shrink-0"
        >
          ভিডিও দেখুন
        </button>
      )}
      {!canOpenNow && (
        <button
          onClick={onGo}
          className="px-[10px] py-[6px] rounded-[7px] bg-primary/12 border border-primary/25 text-[#93C5FD] text-[10px] font-semibold flex-shrink-0"
        >
          Renew
        </button>
      )}
    </div>
  )
}
