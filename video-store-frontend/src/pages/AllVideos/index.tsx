import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { videosApi, categoriesApi } from '@/api'
import type { Category, Video } from '@/types'
import { usePaginatedList } from '@/hooks/usePaginatedList'
import { AppHeader, PageWrapper } from '@/components/layout'
import { VideoGrid } from '@/components/video'
import { EmptyState, ErrorState, FilterChip, LoadMoreButton } from '@/components/ui'

// Sort keys understood by GET /videos (see backend videos.py). Labels are UI text only.
const SORTS = [
  { key: 'latest',   label: 'সর্বশেষ' },
  { key: 'popular',  label: 'জনপ্রিয়' },
  { key: 'trending', label: 'ট্রেন্ডিং' },
  { key: 'featured', label: 'ফিচার্ড' },
]

export default function AllVideosPage() {
  const [searchParams] = useSearchParams()

  const [cats, setCats]          = useState<Category[]>([])
  const [sort, setSort]          = useState(searchParams.get('sort') ?? 'latest')
  const [catFilter, setCatFilter] = useState(searchParams.get('category') ?? '')

  useEffect(() => {
    categoriesApi.list().then((r) => setCats(r.data.categories)).catch(() => {})
  }, [])

  const { items: videos, loading, loadingMore, error, errorMessage, hasMore, loadMore, reload } =
    usePaginatedList<Video>(
      async (page) => {
        const res = await videosApi.list({ sort, category_id: catFilter || undefined, page, limit: 20 })
        return res.data
      },
      [sort, catFilter],
    )

  return (
    <PageWrapper>
      <AppHeader showSearch showNotif={false} showProfile={false} />

      <div className="px-4 pt-3">
        <div className="flex gap-2 overflow-x-auto pb-1 mb-2">
          {SORTS.map((s) => (
            <FilterChip key={s.key} active={sort === s.key} onClick={() => setSort(s.key)}>
              {s.label}
            </FilterChip>
          ))}
          {cats.map((c) => (
            <FilterChip
              key={c.id}
              active={catFilter === c.id}
              onClick={() => setCatFilter(catFilter === c.id ? '' : c.id)}
            >
              📁 {c.name}
            </FilterChip>
          ))}
        </div>
      </div>

      {error ? <ErrorState message={errorMessage ?? 'ভিডিও লোড হয়নি।'} onRetry={reload} /> : (
        <>
          <VideoGrid videos={videos} isLoading={loading} />
          {!loading && videos.length === 0 && <EmptyState icon="🎬" title="কোনো ভিডিও পাওয়া যায়নি" />}
          {hasMore && !loading && <LoadMoreButton onClick={loadMore} loading={loadingMore} />}
        </>
      )}
    </PageWrapper>
  )
}
