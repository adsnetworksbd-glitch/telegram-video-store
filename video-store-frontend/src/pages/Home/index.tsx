import { useEffect, useState, useCallback, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { videosApi, categoriesApi, packagesApi, configApi } from '@/api'
import type { Video, Category, Package } from '@/types'
import { connectionMessage } from '@/api/client'
import { useConfigStore } from '@/store'
import { AppHeader, AnnouncementBar, PageWrapper } from '@/components/layout'
import { FeaturedBanner, HorizontalVideoRow, VideoGrid } from '@/components/video'
import { CategoryRow } from '@/components/category'
import { PackageCard, PackageCardSkeleton } from '@/components/package'
import { SectionHeader, ErrorState, InlineError } from '@/components/ui'

// NOTE: no wallet / balance is shown on the Home page (design rule).
// Which sections appear, and in what order, is decided by the admin through
// GET /config/homepage. The ids below are only the keys this page knows how
// to render; unknown ids from the Backend are ignored.

type LoadKey = 'featured' | 'trending' | 'latest' | 'categories' | 'packages' | 'all'

export default function HomePage() {
  const navigate = useNavigate()
  const { homepageSections, setHomepageSections } = useConfigStore()

  const [featured, setFeatured]     = useState<Video[]>([])
  const [trending, setTrending]     = useState<Video[]>([])
  const [latest, setLatest]         = useState<Video[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [packages, setPackages]     = useState<Package[]>([])
  const [allVideos, setAllVideos]   = useState<Video[]>([])
  const [configLoaded, setConfigLoaded] = useState(false)
  const [failed, setFailed]         = useState<Set<LoadKey>>(new Set())
  const [loadError, setLoadError]   = useState<string | null>(null)
  const [loading, setLoading]       = useState(true)

  const loadAll = useCallback(async () => {
    setLoading(true)
    // Each request is independent: one failing section must not blank the page.
    const [cfg, feat, trend, lat, cat, pkg, all] = await Promise.allSettled([
      configApi.getHomepageConfig(),
      videosApi.featured(),
      videosApi.trending(),
      videosApi.latest(),
      categoriesApi.list(),
      packagesApi.featured(),
      videosApi.list({ limit: 10 }),
    ])

    const nextFailed = new Set<LoadKey>()
    if (cfg.status === 'fulfilled') {
      setHomepageSections(cfg.value.data.sections)
      setConfigLoaded(true)
    } // config failure → render every known section in the default order

    if (feat.status === 'fulfilled') setFeatured(feat.value.data.videos); else nextFailed.add('featured')
    if (trend.status === 'fulfilled') setTrending(trend.value.data.videos); else nextFailed.add('trending')
    if (lat.status === 'fulfilled') setLatest(lat.value.data.videos); else nextFailed.add('latest')
    if (cat.status === 'fulfilled') setCategories(cat.value.data.categories); else nextFailed.add('categories')
    if (pkg.status === 'fulfilled') setPackages(pkg.value.data.packages); else nextFailed.add('packages')
    if (all.status === 'fulfilled') setAllVideos(all.value.data.items); else nextFailed.add('all')

    setFailed(nextFailed)
    // When the cause is the connection itself, say so (offline / timeout / bad response).
    const firstRejected = [cfg, feat, trend, lat, cat, pkg, all].find((r) => r.status === 'rejected')
    setLoadError(firstRejected && firstRejected.status === 'rejected' ? connectionMessage(firstRejected.reason) : null)
    setLoading(false)
  }, [setHomepageSections])

  useEffect(() => { void loadAll() }, [loadAll])

  // Every content request failed → the Backend is unreachable: full-page error.
  if (!loading && failed.size === 6) {
    return (
      <PageWrapper>
        <AppHeader />
        <ErrorState message={loadError ?? 'Data লোড হয়নি।'} onRetry={loadAll} />
      </PageWrapper>
    )
  }

  // A section is rendered while loading, when it failed (with a retry notice),
  // or when it actually has content — empty sections are hidden entirely.
  function section(
    key: LoadKey, id: string, title: string, count: number,
    body: ReactNode, onSeeAll?: () => void,
  ) {
    if (!loading && !failed.has(key) && count === 0) return null
    return (
      <section key={id} className="mt-6">
        <SectionHeader title={title} onAction={onSeeAll} />
        {!loading && failed.has(key) ? <InlineError onRetry={loadAll} /> : body}
      </section>
    )
  }

  const sectionMap: Record<string, ReactNode> = {
    featured_banner:
      !loading && failed.has('featured') ? null :
      (!loading && featured.length === 0) ? null : (
        <div key="featured_banner" className="mt-4">
          {loading ? <div className="mx-4 aspect-video rounded-[14px] skeleton" /> : <FeaturedBanner videos={featured} />}
        </div>
      ),
    featured_videos: section('featured', 'featured_videos', '⭐ ফিচার্ড', featured.length,
      <HorizontalVideoRow videos={featured} isLoading={loading} />,
      () => navigate('/videos?sort=featured')),
    trending_videos: section('trending', 'trending_videos', '🔥 ট্রেন্ডিং', trending.length,
      <HorizontalVideoRow videos={trending} isLoading={loading} />,
      () => navigate('/videos?sort=trending')),
    latest_videos: section('latest', 'latest_videos', '🕐 সর্বশেষ', latest.length,
      <HorizontalVideoRow videos={latest} isLoading={loading} />,
      () => navigate('/videos?sort=latest')),
    popular_categories: section('categories', 'popular_categories', '📁 ক্যাটাগরি', categories.length,
      <CategoryRow categories={categories} isLoading={loading} />,
      () => navigate('/categories')),
    featured_packages: section('packages', 'featured_packages', '📦 ফিচার্ড প্যাকেজ', packages.length,
      <div className="flex gap-[10px] px-4 overflow-x-auto">
        {loading
          ? Array.from({ length: 3 }).map((_, i) => <PackageCardSkeleton key={i} variant="horizontal" />)
          : packages.map((p) => <PackageCard key={p.id} pkg={p} variant="horizontal" />)}
      </div>,
      () => navigate('/packages')),
    all_videos: section('all', 'all_videos', '🎬 সব ভিডিও', allVideos.length,
      <VideoGrid videos={allVideos} isLoading={loading} />,
      () => navigate('/videos')),
  }

  // Admin-defined order. Until the config has loaded (or if it failed) show the
  // default order. Once loaded, ONLY enabled sections are shown — even if the
  // admin disabled all of them.
  const DEFAULT_ORDER = [
    'featured_banner', 'featured_videos', 'trending_videos',
    'latest_videos', 'popular_categories', 'featured_packages',
  ]
  const configured = configLoaded && homepageSections.length > 0
  const orderedIds: string[] = configured
    ? [...homepageSections].filter((s) => s.enabled).sort((a, b) => a.order - b.order).map((s) => s.id)
    : [...DEFAULT_ORDER]
  // "All videos" stays a fixed last block unless the admin config positions it.
  const adminControlsAllVideos = configured && homepageSections.some((s) => s.id === 'all_videos')
  if (!adminControlsAllVideos) orderedIds.push('all_videos')

  return (
    <PageWrapper>
      <AppHeader />
      <AnnouncementBar />
      {orderedIds.map((id) => sectionMap[id] ?? null)}
    </PageWrapper>
  )
}
