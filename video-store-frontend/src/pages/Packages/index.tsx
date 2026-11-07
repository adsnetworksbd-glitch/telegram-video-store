import { packagesApi } from '@/api'
import type { Package } from '@/types'
import { usePaginatedList } from '@/hooks/usePaginatedList'
import { AppHeader, PageWrapper } from '@/components/layout'
import { PackageCard, PackageCardSkeleton } from '@/components/package'
import { ErrorState, EmptyState, LoadMoreButton } from '@/components/ui'

export default function PackagesPage() {
  const { items: packages, loading, loadingMore, error, errorMessage, hasMore, loadMore, reload } =
    usePaginatedList<Package>(
      async (page) => {
        const res = await packagesApi.list({ page, limit: 20 })
        return res.data
      },
      [],
    )

  return (
    <PageWrapper>
      <AppHeader showSearch={false} />
      <div className="px-4 pt-4 pb-2">
        <h1 className="text-[17px] font-bold text-white">📦 ভিডিও প্যাকেজ</h1>
        <p className="text-[12px] text-[#6B7280] mt-1">একসাথে কিনুন, বেশি সাশ্রয় করুন</p>
      </div>

      {error ? <ErrorState message={errorMessage ?? 'Package লোড হয়নি।'} onRetry={reload} /> : (
        <>
          <div className="grid grid-cols-2 gap-[10px] px-4 mt-3">
            {loading
              ? Array.from({ length: 6 }).map((_, i) => <PackageCardSkeleton key={i} />)
              : packages.length === 0
              ? <div className="col-span-2"><EmptyState icon="📦" title="কোনো Package নেই" /></div>
              : packages.map((p) => <PackageCard key={p.id} pkg={p} />)
            }
          </div>
          {hasMore && !loading && <LoadMoreButton onClick={loadMore} loading={loadingMore} />}
        </>
      )}
    </PageWrapper>
  )
}
