import { useCallback, useEffect, useRef, useState } from 'react'
import type { Page } from './configApi'
import { errorText } from './util'

/**
 * Paginated admin list: page 1 reloads whenever `deps` (filters / search) change, "load more" appends.
 * A response that arrives after the filters changed again is ignored (sequence guard).
 */
export function useAdminList<T>(fetcher: (page: number) => Promise<Page<T>>, deps: ReadonlyArray<unknown>, enabled = true) {
  const [items, setItems] = useState<T[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher

  const load = useCallback((p: number, replace: boolean) => {
    const my = ++seq.current
    setLoading(true)
    setError(null)
    fetchRef.current(p)
      .then((r) => {
        if (my !== seq.current) return
        setItems((prev) => (replace ? r.items : [...prev, ...r.items]))
        setTotal(r.total)
        setHasMore(r.has_more)
        setPage(p)
      })
      .catch((e) => { if (my === seq.current) setError(errorText(e)) })
      .finally(() => { if (my === seq.current) setLoading(false) })
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (enabled) load(1, true) }, [enabled, load, ...deps])

  return { items, total, hasMore, loading, error, reload: () => load(1, true), more: () => load(page + 1, false) }
}
