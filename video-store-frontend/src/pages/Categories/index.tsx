import { useEffect, useState, useCallback } from 'react'
import { categoriesApi } from '@/api'
import { connectionMessage } from '@/api/client'
import type { Category } from '@/types'
import { useConfigStore } from '@/store'
import { AppHeader, PageWrapper } from '@/components/layout'
import { CategoryCard, CategoryCardSkeleton } from '@/components/category'
import { ErrorState, EmptyState } from '@/components/ui'

export default function CategoriesPage() {
  const setCategoriesCache = useConfigStore((s) => s.setCategories)
  const [cats, setCats]       = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await categoriesApi.list()
      setCats(res.data.categories)
      setCategoriesCache(res.data.categories) // keeps card labels in sync
    } catch (e) {
      setError(connectionMessage(e) ?? 'ক্যাটাগরি লোড হয়নি।')
    } finally {
      setLoading(false)
    }
  }, [setCategoriesCache])

  useEffect(() => { void load() }, [load])

  return (
    <PageWrapper>
      <AppHeader showSearch={false} />
      <div className="px-4 pt-4 pb-2">
        <h1 className="text-[17px] font-bold text-white">📁 ক্যাটাগরি</h1>
      </div>

      {error ? <ErrorState message={error} onRetry={load} /> : (
        <div className="grid grid-cols-2 gap-[10px] px-4 mt-3">
          {loading
            ? Array.from({ length: 8 }).map((_, i) => <CategoryCardSkeleton key={i} />)
            : cats.length === 0
            ? <div className="col-span-2"><EmptyState icon="📁" title="কোনো ক্যাটাগরি নেই" /></div>
            : cats.map((cat, i) => <CategoryCard key={cat.id} category={cat} index={i} />)
          }
        </div>
      )}
    </PageWrapper>
  )
}
