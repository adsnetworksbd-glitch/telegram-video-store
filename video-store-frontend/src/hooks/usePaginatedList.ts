import { useState, useEffect, useCallback, useRef } from 'react'
import { connectionMessage } from '@/api/client'

interface Page<T> { items: T[]; has_more: boolean }

/**
 * Paginated list loader shared by All Videos, Category Detail and Packages.
 *  • resets and reloads when `deps` change
 *  • ignores stale responses (fast filter switching can't overwrite newer data)
 *  • clears the error flag on retry
 *  • `errorMessage` is set only when the cause is the connection itself
 *    (offline / timeout / unexpected response / ended session), so pages can
 *    show that instead of a generic "could not load" text
 *  • de-duplicates items by id when appending
 */
export function usePaginatedList<T extends { id: string }>(
  fetchPage: (page: number) => Promise<Page<T>>,
  deps: unknown[],
) {
  const [items, setItems] = useState<T[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)

  const pageRef = useRef(1)
  const reqRef = useRef(0)
  const fetchRef = useRef(fetchPage)
  fetchRef.current = fetchPage

  const load = useCallback(async (reset: boolean) => {
    const req = ++reqRef.current
    const page = reset ? 1 : pageRef.current + 1
    if (reset) setLoading(true)
    else setLoadingMore(true)
    setError(false)
    setErrorMessage(null)
    try {
      const res = await fetchRef.current(page)
      if (req !== reqRef.current) return
      setItems((prev) => {
        if (reset) return res.items
        const seen = new Set(prev.map((i) => i.id))
        return [...prev, ...res.items.filter((i) => !seen.has(i.id))]
      })
      setHasMore(res.has_more)
      pageRef.current = page
    } catch (e) {
      if (req === reqRef.current) {
        setError(true)
        setErrorMessage(connectionMessage(e))
      }
    } finally {
      if (req === reqRef.current) {
        setLoading(false)
        setLoadingMore(false)
      }
    }
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(true) }, deps)

  return {
    items,
    loading,
    loadingMore,
    error,
    errorMessage,
    hasMore,
    loadMore: () => load(false),
    reload: () => load(true),
  }
}
