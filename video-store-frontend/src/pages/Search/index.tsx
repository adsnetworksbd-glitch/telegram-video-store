import { useState, useCallback, useRef, useEffect } from 'react'
import { searchApi } from '@/api'
import { connectionMessage } from '@/api/client'
import type { Video, Package } from '@/types'
import { SubHeader, PageWrapper } from '@/components/layout'
import { VideoGrid } from '@/components/video'
import { PackageCard } from '@/components/package'
import { Spinner, EmptyState, ErrorState } from '@/components/ui'

const DEBOUNCE_MS = 500

export default function SearchPage() {
  const [query, setQuery]       = useState('')
  const [videos, setVideos]     = useState<Video[]>([])
  const [packages, setPackages] = useState<Package[]>([])
  const [loading, setLoading]   = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reqRef = useRef(0)

  const doSearch = useCallback(async (q: string) => {
    const term = q.trim()
    const req = ++reqRef.current
    if (!term) {
      setVideos([]); setPackages([]); setSearched(false); setError(null); setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await searchApi.search(term)
      if (req !== reqRef.current) return // a newer search superseded this one
      setVideos(res.data.videos)
      setPackages(res.data.packages)
      setSearched(true)
    } catch (e) {
      if (req === reqRef.current) setError(connectionMessage(e) ?? 'খুঁজে পাওয়া যায়নি, সংযোগ পরীক্ষা করুন।')
    } finally {
      if (req === reqRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current) }, [])

  function handleInput(val: string) {
    setQuery(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { void doSearch(val) }, DEBOUNCE_MS)
  }

  const hasResults = videos.length > 0 || packages.length > 0

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="খুঁজুন" />
      <div className="px-4 pt-3 pb-3">
        <div className="flex items-center gap-3 bg-card border border-border rounded-[12px] px-3 py-[10px]">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="1.8" strokeLinecap="round">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          <input
            autoFocus
            value={query}
            onChange={(e: { target: { value: string } }) => handleInput(e.target.value)}
            placeholder="ভিডিও বা Package খুঁজুন..."
            enterKeyHint="search"
            className="flex-1 bg-transparent text-[13px] text-white outline-none placeholder:text-[#6B7280]"
          />
          {loading && <Spinner size={16} />}
        </div>
      </div>

      {error && (
        <ErrorState message={error} onRetry={() => doSearch(query)} />
      )}

      {!error && !searched && !loading && (
        <EmptyState icon="🔍" title="কিছু লিখুন" description="ভিডিও বা Package-এর নাম লিখুন" />
      )}

      {!error && searched && !loading && !hasResults && (
        <EmptyState icon="😕" title="কিছু পাওয়া যায়নি" description={`"${query.trim()}" এর জন্য কোনো ফলাফল নেই`} />
      )}

      {!error && videos.length > 0 && (
        <section className="mb-4">
          <p className="text-[12px] font-semibold text-[#9CA3AF] px-4 mb-2">ভিডিও ({videos.length}টি)</p>
          <VideoGrid videos={videos} />
        </section>
      )}

      {!error && packages.length > 0 && (
        <section className="px-4">
          <p className="text-[12px] font-semibold text-[#9CA3AF] mb-2">প্যাকেজ ({packages.length}টি)</p>
          <div className="grid grid-cols-2 gap-[10px]">
            {packages.map((p) => <PackageCard key={p.id} pkg={p} />)}
          </div>
        </section>
      )}
    </PageWrapper>
  )
}
