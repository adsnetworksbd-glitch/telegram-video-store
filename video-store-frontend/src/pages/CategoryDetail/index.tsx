import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { categoriesApi } from '@/api'
import { getErrorStatus } from '@/api/client'
import type { Category, Video } from '@/types'
import { useConfigStore } from '@/store'
import { usePaginatedList } from '@/hooks/usePaginatedList'
import { SubHeader, PageWrapper } from '@/components/layout'
import { VideoGrid } from '@/components/video'
import { ErrorState, EmptyState, FilterChip, LoadMoreButton } from '@/components/ui'

const SORTS = [
  { key: 'latest',   label: 'সর্বশেষ' },
  { key: 'popular',  label: 'জনপ্রিয়' },
  { key: 'trending', label: 'ট্রেন্ডিং' },
]

export default function CategoryDetailPage() {
  const { id } = useParams<{ id: string }>()
  const cached = useConfigStore((s) => s.categories.find((c) => c.id === id) ?? null)
  const [fetched, setFetched] = useState<Category | null>(null)
  const [notFound, setNotFound] = useState(false)
  const category: Category | null = cached ?? fetched
  const [sort, setSort]         = useState('latest')

  // The name normally comes from the shared category list (already loaded by the
  // app shell); only fetch it when it is not cached. A 404 means the category
  // does not exist (deleted / hidden / bad link) — say so instead of "no videos".
  useEffect(() => {
    setFetched(null)
    setNotFound(false)
    if (!id || cached) return
    let alive = true
    categoriesApi.detail(id)
      .then((r) => { if (alive) setFetched(r.data.category) })
      .catch((e) => { if (alive && getErrorStatus(e) === 404) setNotFound(true) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const { items: videos, loading, loadingMore, error, errorMessage, hasMore, loadMore, reload } =
    usePaginatedList<Video>(
      async (page) => {
        if (!id) return { items: [], has_more: false }
        const res = await categoriesApi.videos(id, { sort, page, limit: 20 })
        return res.data
      },
      [id, sort],
    )

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={category?.name ?? 'ক্যাটাগরি'} />

      <div className="flex gap-2 px-4 pt-3 pb-2 overflow-x-auto">
        {SORTS.map((s) => (
          <FilterChip key={s.key} active={sort === s.key} onClick={() => setSort(s.key)}>
            {s.label}
          </FilterChip>
        ))}
      </div>

      {notFound ? <EmptyState icon="📁" title="ক্যাটাগরিটি পাওয়া যায়নি" /> : error ? <ErrorState message={errorMessage ?? 'ভিডিও লোড হয়নি।'} onRetry={reload} /> : (
        <>
          <VideoGrid videos={videos} isLoading={loading} />
          {!loading && videos.length === 0 && (
            <EmptyState icon="🎬" title="এই ক্যাটাগরিতে কোনো ভিডিও নেই" />
          )}
          {hasMore && !loading && <LoadMoreButton onClick={loadMore} loading={loadingMore} />}
        </>
      )}
    </PageWrapper>
  )
}
