import { useEffect, useState, useCallback, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { videosApi, categoriesApi, accessApi } from '@/api'
import { connectionMessage, getErrorStatus } from '@/api/client'
import type { Video, VideoDetail } from '@/types'
import { useConfigStore } from '@/store'
import { hasNativeBack } from '@/hooks/useTelegram'
import { useCategoryName } from '@/hooks/useCategories'
import { useAccessRevalidation } from '@/hooks/useAccessRevalidation'
import { SubHeader, PageWrapper } from '@/components/layout'
import { AccessButton, SourceNote } from '@/components/access'
import { HorizontalVideoRow } from '@/components/video'
import { Skeleton, ErrorState } from '@/components/ui'
import { formatDurationLong, formatFileSize, formatAccessDuration, bdtToUsdt } from '@/utils'

export default function VideoDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { appConfig } = useConfigStore()

  const [video, setVideo]     = useState<VideoDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [descExpanded, setDescExpanded] = useState(false)

  const categoryName = useCategoryName(video?.primary_category_id)

  const loadVideo = useCallback(async (videoId: string) => {
    try {
      setLoading(true)
      setError(null)
      setNotFound(false)
      const res = await videosApi.detail(videoId)
      setVideo(res.data)
    } catch (e) {
      setVideo(null)
      // 404 = deleted / unpublished / bad link: retrying cannot help.
      if (getErrorStatus(e) === 404) setNotFound(true)
      else setError(connectionMessage(e) ?? 'ভিডিও লোড হয়নি।')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!id) return
    setDescExpanded(false)
    void loadVideo(id)
  }, [id, loadVideo])

  // Ask the Backend again what access is valid NOW (after an expiry, or after
  // it refused to open the source). Only `access` is replaced — and only with
  // the Backend's answer. A failed re-check leaves the page as it was.
  const refreshAccess = useCallback(() => {
    if (!id) return
    accessApi.checkVideo(id)
      .then((r) => setVideo((v) => (v && v.id === id ? { ...v, access: r.data } : v)))
      .catch(() => { /* keep what is shown; the Backend still guards the source */ })
  }, [id])
  useAccessRevalidation(video?.access, refreshAccess)

  if (loading) return <VideoDetailSkeleton />
  if (notFound) return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="ভিডিও" />
      <ErrorState message="ভিডিওটি পাওয়া যায়নি বা আর উপলব্ধ নেই।" />
    </PageWrapper>
  )
  if (error || !video) return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="ভিডিও" />
      <ErrorState message={error ?? 'ভিডিও লোড হয়নি।'} onRetry={() => id && loadVideo(id)} />
    </PageWrapper>
  )

  // USDT estimate is shown only when the admin-set rate is available.
  const rate = appConfig?.usdt_to_bdt_rate
  const usdtLabel = rate ? `${bdtToUsdt(video.price_bdt, rate).toFixed(2)} USDT` : undefined

  const methods = video.available_methods
  const showNativeBack = hasNativeBack()

  // Access-length facts only for the unlock methods the admin enabled.
  const accessFacts: { label: string; value: string }[] = []
  if (methods.purchase) accessFacts.push({ label: 'Purchase Access', value: formatAccessDuration(video.purchase_duration_hours) })
  if (methods.ads_unlock) accessFacts.push({ label: 'Ads Access', value: formatAccessDuration(video.ads_unlock_duration_hours) })

  return (
    <PageWrapper hasBottomNav={false}>
      {/* Hero */}
      <div className="relative">
        <div className="w-full aspect-video bg-surface relative overflow-hidden">
          {video.thumbnail_url
            ? <img src={video.thumbnail_url} alt={video.title} onError={(e: { currentTarget: { style: { display: string } } }) => { e.currentTarget.style.display = 'none' }} className="w-full h-full object-cover" />
            : <div className="w-full h-full bg-gradient-to-br from-[#0d1a35] to-[#1a0b2e]" />
          }
          <div className="absolute inset-0 bg-gradient-to-t from-navy/50 via-transparent to-navy/60" />

          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="w-14 h-14 rounded-full bg-primary/20 border-2 border-primary/50 flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="#60A5FA" style={{ marginLeft: 3 }}>
                <polygon points="5,3 19,12 5,21" />
              </svg>
            </div>
          </div>
        </div>

        {/* In-app back button — hidden inside Telegram (native BackButton is used) */}
        {!showNativeBack && (
          <div className="absolute top-0 left-0 right-0 flex items-center justify-between px-4 py-3">
            <button
              onClick={() => navigate(-1)}
              className="flex items-center gap-[6px] bg-[rgba(17,24,39,0.7)] border border-white/10 rounded-[20px] px-3 py-[6px]"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round">
                <polyline points="15 18 9 12 15 6" />
              </svg>
              <span className="text-[13px] text-white font-medium">ফিরে যান</span>
            </button>
          </div>
        )}
      </div>

      <div className="px-4">
        {/* Info chips */}
        <div className="flex gap-2 flex-wrap py-[14px]">
          <InfoChip
            icon={<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#60A5FA" strokeWidth="1.8" strokeLinecap="round"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>}
            label={video.quality}
            color="text-[#93C5FD]"
            bg="bg-primary/10 border-primary/25"
          />
          <InfoChip
            icon={<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>}
            label={formatDurationLong(video.duration_seconds)}
            color="text-[#FCD34D]"
            bg="bg-warning/10 border-warning/20"
          />
          <InfoChip
            icon={<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" strokeWidth="1.8" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>}
            label={formatFileSize(video.file_size_mb)}
            color="text-[#C4B5FD]"
            bg="bg-secondary/10 border-secondary/20"
          />
          {categoryName && (
            <InfoChip
              icon={<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="1.8" strokeLinecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>}
              label={categoryName}
              color="text-[#6EE7B7]"
              bg="bg-success/10 border-success/20"
            />
          )}
        </div>

        <h1 className="text-[18px] font-bold text-white leading-[1.35] mb-3">{video.title}</h1>

        {video.description && (
          <div className="mb-4">
            <p className={`text-[13px] text-[#9CA3AF] leading-[1.6] ${!descExpanded ? 'line-clamp-3' : ''}`}>
              {video.description}
            </p>
            {video.description.length > 120 && (
              <button
                onClick={() => setDescExpanded((v) => !v)}
                className="text-[12px] text-primary mt-1 font-medium"
              >
                {descExpanded ? 'কম দেখুন ▴' : 'আরও দেখুন ▾'}
              </button>
            )}
          </div>
        )}

        <div className="h-px bg-border mb-4" />

        {/* Access options — which ones appear is decided by the admin
            (available_methods) and every label comes from the video record. */}
        <div className="mb-2">
          <p className="text-[11px] text-[#6B7280] font-semibold tracking-[0.5px] uppercase mb-3">
            Access পদ্ধতি
          </p>
          <AccessButton
            contentType="video"
            contentId={video.id}
            access={video.access}
            methods={methods}
            priceBdt={video.price_bdt}
            priceLabelSuffix={usdtLabel}
            adsRequired={video.ads_required}
            adsDurationHours={video.ads_unlock_duration_hours}
            purchaseDurationHours={video.purchase_duration_hours}
            onAccessInvalid={refreshAccess}
          />
          {(video.access.granted || methods.is_free) && (
            <SourceNote sourceType={video.source_type} className="mt-3" />
          )}
        </div>

        {accessFacts.length > 0 && !video.access.granted && (
          <div className="grid grid-cols-2 gap-2 mt-4">
            {accessFacts.map((item) => (
              <div key={item.label} className="bg-card border border-border rounded-[10px] px-3 py-[10px]">
                <p className="text-[10px] text-[#6B7280] font-medium uppercase tracking-[0.3px] mb-[3px]">{item.label}</p>
                <p className="text-[13px] font-semibold text-white">{item.value}</p>
              </div>
            ))}
          </div>
        )}

        <div className="h-px bg-border my-4" />
      </div>

      <RelatedVideos categoryId={video.primary_category_id} excludeId={video.id} />
    </PageWrapper>
  )
}

// ─── Related Videos (same category; hidden when there are none) ───────────────
function RelatedVideos({ categoryId, excludeId }: { categoryId: string; excludeId: string }) {
  const [videos, setVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    categoriesApi.videos(categoryId, { limit: 7 })
      .then((r) => { if (!cancelled) setVideos(r.data.items.filter((v) => v.id !== excludeId).slice(0, 6)) })
      .catch(() => { if (!cancelled) setVideos([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [categoryId, excludeId])

  if (!loading && videos.length === 0) return null

  return (
    <div className="mb-6">
      <h2 className="text-[15px] font-semibold text-white px-4 mb-3">সম্পর্কিত ভিডিও</h2>
      <HorizontalVideoRow videos={videos} isLoading={loading} />
    </div>
  )
}

// ─── Info Chip ────────────────────────────────────────────────────────────────
function InfoChip({ icon, label, color, bg }: { icon: ReactNode; label: string; color: string; bg: string }) {
  return (
    <div className={`flex items-center gap-[5px] border rounded-[8px] px-[10px] py-[5px] ${bg}`}>
      {icon}
      <span className={`text-[11px] font-medium ${color}`}>{label}</span>
    </div>
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────
function VideoDetailSkeleton() {
  return (
    <PageWrapper hasBottomNav={false}>
      <Skeleton className="w-full aspect-video" />
      <div className="px-4 pt-4 space-y-3">
        <div className="flex gap-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-7 w-16 rounded-[8px]" />)}
        </div>
        <Skeleton className="h-5 w-full rounded" />
        <Skeleton className="h-5 w-3/4 rounded" />
        <Skeleton className="h-4 w-full rounded mt-2" />
        <Skeleton className="h-4 w-5/6 rounded" />
        <Skeleton className="h-12 w-full rounded-[14px] mt-4" />
        <Skeleton className="h-12 w-full rounded-[14px]" />
      </div>
    </PageWrapper>
  )
}
