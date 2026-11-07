import { useCallback, useEffect, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { videosApi, packagesApi } from '@/api'
import type { VideoDetail, PackageDetail } from '@/types'
import { SubHeader, PageWrapper } from '@/components/layout'
import { AccessStateCard } from '@/components/access'
import { Button, ErrorState, Skeleton } from '@/components/ui'
import { useCategoryName } from '@/hooks/useCategories'
import { useOpenSource } from '@/hooks/useOpenSource'
import { formatDuration } from '@/utils'

// Success is never assumed from the URL: the page asks the Backend for the
// current access status and only celebrates when access is really granted.

export default function AdsSuccessPage() {
  const { id } = useParams<{ id: string }>()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const contentType: 'video' | 'package' = pathname.startsWith('/packages') ? 'package' : 'video'
  const basePath = contentType === 'video' ? '/videos' : '/packages'

  const [video, setVideo] = useState<VideoDetail | null>(null)
  const [pkg, setPkg]     = useState<PackageDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const { openingId, open } = useOpenSource()
  const categoryName = useCategoryName(video?.primary_category_id)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true); setError(false)
    try {
      if (contentType === 'video') setVideo((await videosApi.detail(id)).data)
      else setPkg((await packagesApi.detail(id)).data)
    } catch { setError(true) }
    finally { setLoading(false) }
  }, [id, contentType])

  useEffect(() => { void load() }, [load])

  const header = <SubHeader title="Unlock সফল" onBack={() => navigate(id ? `${basePath}/${id}` : '/', { replace: true })} />

  if (loading) return (
    <PageWrapper hasBottomNav={false}>
      {header}
      <div className="px-4 pt-10 space-y-3">
        <Skeleton className="w-20 h-20 rounded-full mx-auto" />
        <Skeleton className="h-5 w-1/2 mx-auto rounded" />
        <Skeleton className="h-16 w-full rounded-[14px]" />
      </div>
    </PageWrapper>
  )

  const content = contentType === 'video' ? video : pkg
  if (error || !content) return (
    <PageWrapper hasBottomNav={false}>
      {header}
      <ErrorState message="তথ্য লোড করা যায়নি।" onRetry={() => void load()} />
    </PageWrapper>
  )

  const access = content.access
  const title = contentType === 'video' ? (content as VideoDetail).title : (content as PackageDetail).name
  const thumb = content.thumbnail_url

  // Visited directly / access not (yet) active → no fake success
  if (!access.granted) return (
    <PageWrapper hasBottomNav={false}>
      {header}
      <div className="px-4 pt-10 space-y-4 text-center">
        <div className="text-4xl">🔒</div>
        <p className="text-[14px] font-semibold text-white">Access এখনো সক্রিয় হয়নি</p>
        <p className="text-[12px] text-[#9CA3AF] leading-[1.6]">
          বিজ্ঞাপনের যাচাই সম্পন্ন হলে Access চালু হবে। কিছুক্ষণ পর আবার দেখুন।
        </p>
        <AccessStateCard access={access} />
        <Button onClick={() => void load()}>আবার দেখুন</Button>
        <Button variant="ghost" onClick={() => id && navigate(`${basePath}/${id}`, { replace: true })}>
          {contentType === 'video' ? 'ভিডিওতে যান' : 'Package-এ যান'}
        </Button>
      </div>
    </PageWrapper>
  )

  return (
    <PageWrapper hasBottomNav={false}>
      {header}

      {/* Success message */}
      <motion.div
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: 'spring', stiffness: 200, damping: 20 }}
        className="flex flex-col items-center text-center px-4 pt-8 pb-6"
      >
        <div className="w-20 h-20 rounded-full bg-success/10 border-2 border-success/30 flex items-center justify-center mb-4">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
        <h1 className="text-[20px] font-bold text-white mb-2">সফলভাবে Unlock হয়েছে!</h1>
        <p className="text-[13px] text-[#9CA3AF] leading-[1.5]">
          বিজ্ঞাপন যাচাই সম্পন্ন হয়েছে।<br />নিচের {contentType === 'video' ? 'ভিডিওতে' : 'Package-এ'} এখন Access আছে।
        </p>
      </motion.div>

      {/* Video / package information */}
      <div className="mx-4 bg-card border border-border rounded-[14px] p-[14px] flex gap-3 items-center mb-3">
        <div className="w-[72px] h-[44px] rounded-[8px] bg-surface flex-shrink-0 overflow-hidden flex items-center justify-center">
          {thumb
            ? <img src={thumb} alt={title} className="w-full h-full object-cover" />
            : <svg width="18" height="18" viewBox="0 0 24 24" fill="rgba(255,255,255,0.4)"><polygon points="5,3 19,12 5,21" /></svg>}
        </div>
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-white leading-[1.3] mb-1">{title}</p>
          <p className="text-[11px] text-[#6B7280]">
            {contentType === 'video'
              ? `${categoryName ? `📁 ${categoryName} · ` : ''}${video!.quality} · ${formatDuration(video!.duration_seconds)}`
              : `${pkg!.video_count}টি ভিডিও`}
          </p>
        </div>
      </div>

      {/* Real access status from the Backend (source + actual expiry) */}
      <AccessStateCard access={access} className="mx-4 mb-6" />

      <div className="px-4 space-y-3">
        <Button onClick={() => id && navigate(`${basePath}/${id}`, { replace: true })}>
          {contentType === 'video' ? '▶ ভিডিওতে যান' : '📦 Package-এ যান'}
        </Button>
        {contentType === 'video' && (
          <Button variant="success" loading={openingId === id} onClick={() => id && void open(id)}>
            Open / Download করুন
          </Button>
        )}
        <button onClick={() => navigate('/', { replace: true })} className="btn-ghost">← হোমে ফিরে যান</button>
      </div>
    </PageWrapper>
  )
}
