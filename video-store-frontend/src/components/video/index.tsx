import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import type { Video } from '@/types'
import { formatDuration, formatFileSize, cx } from '@/utils'
import { Skeleton, QualityBadge } from '@/components/ui'
import { useCategoryName } from '@/hooks/useCategories'

// NOTE: video cards never show Buy / Watch-Ads buttons — access options live
// on the Video Details page only (see components/access).

// ─── Thumbnail (falls back to a gradient if the image URL is missing/broken) ──
function Thumb({ src, alt, iconSize = 14 }: { src?: string | null; alt: string; iconSize?: number }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-gradient-navy">
        <PlayIcon size={iconSize} />
      </div>
    )
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      onError={() => setFailed(true)}
      className="w-full h-full object-cover"
    />
  )
}

// ─── Video Card ───────────────────────────────────────────────────────────────
interface VideoCardProps {
  video: Video
  /** 'grid' fills its column; 'compact' is a fixed-width card for horizontal rows */
  variant?: 'grid' | 'compact'
  className?: string
}

export function VideoCard({ video, variant = 'grid', className = '' }: VideoCardProps) {
  const navigate = useNavigate()
  const categoryName = useCategoryName(video.primary_category_id)
  const open = () => navigate(`/videos/${video.id}`)

  return (
    <motion.div
      role="button"
      tabIndex={0}
      whileTap={{ scale: 0.97 }}
      onClick={open}
      onKeyDown={(e: { key: string }) => { if (e.key === 'Enter') open() }}
      className={cx(
        'bg-card border border-border rounded-card overflow-hidden cursor-pointer',
        variant === 'compact' && 'w-[150px] flex-shrink-0',
        className,
      )}
    >
      <div className="relative w-full aspect-video overflow-hidden bg-surface">
        <Thumb src={video.thumbnail_url} alt={video.title} iconSize={variant === 'compact' ? 16 : 14} />
        <div className="absolute inset-0 bg-gradient-to-t from-navy/70 via-transparent to-transparent pointer-events-none" />

        <div className="absolute top-[5px] left-[5px]">
          <QualityBadge quality={video.quality} />
        </div>

        <div className="absolute bottom-[5px] right-[5px] text-[9px] text-white/90 bg-black/60 px-[5px] py-[2px] rounded-[4px]">
          {formatDuration(video.duration_seconds)}
        </div>

        {video.is_free && (
          <div className="absolute top-[5px] right-[5px] text-[8px] font-bold bg-success/85 text-white px-[5px] py-[2px] rounded-[4px]">
            বিনামূল্যে
          </div>
        )}
      </div>

      <div className="p-2">
        <div className="text-[12px] font-medium text-white leading-[1.35] mb-1 line-clamp-2">
          {video.title}
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-[#9CA3AF] truncate flex-1">
            {categoryName ? `📁 ${categoryName}` : ''}
          </span>
          <span className="text-[10px] text-[#6B7280] flex-shrink-0">{formatFileSize(video.file_size_mb)}</span>
        </div>
      </div>
    </motion.div>
  )
}

// ─── Video Card Skeleton ──────────────────────────────────────────────────────
export function VideoCardSkeleton() {
  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <Skeleton className="w-full aspect-video" />
      <div className="p-2 space-y-2">
        <Skeleton className="h-3 w-full rounded" />
        <Skeleton className="h-3 w-2/3 rounded" />
      </div>
    </div>
  )
}

// ─── Two-Column Video Grid ────────────────────────────────────────────────────
interface VideoGridProps {
  videos: Video[]
  isLoading?: boolean
  skeletonCount?: number
}

export function VideoGrid({ videos, isLoading = false, skeletonCount = 6 }: VideoGridProps) {
  return (
    <div className="grid grid-cols-2 gap-[10px] px-4">
      {isLoading
        ? Array.from({ length: skeletonCount }).map((_, i) => <VideoCardSkeleton key={i} />)
        : videos.map((v) => <VideoCard key={v.id} video={v} />)}
    </div>
  )
}

// ─── Horizontal Video Row ─────────────────────────────────────────────────────
interface HorizontalVideoRowProps {
  videos: Video[]
  isLoading?: boolean
}

export function HorizontalVideoRow({ videos, isLoading = false }: HorizontalVideoRowProps) {
  return (
    <div className="flex gap-[10px] px-4 overflow-x-auto">
      {isLoading
        ? Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="w-[150px] flex-shrink-0">
              <VideoCardSkeleton />
            </div>
          ))
        : videos.map((v) => <VideoCard key={v.id} video={v} variant="compact" />)}
    </div>
  )
}

// ─── Featured Banner ──────────────────────────────────────────────────────────
interface FeaturedBannerProps {
  videos: Video[]
  /** Auto-advance interval in ms (0 disables). */
  intervalMs?: number
}

export function FeaturedBanner({ videos, intervalMs = 4000 }: FeaturedBannerProps) {
  const [current, setCurrent] = useState(0)
  const navigate = useNavigate()

  useEffect(() => {
    if (videos.length <= 1 || intervalMs <= 0) return
    const t = setInterval(() => setCurrent((c) => (c + 1) % videos.length), intervalMs)
    return () => clearInterval(t)
  }, [videos.length, intervalMs])

  // Keep the index valid if the list shrinks (e.g. after a refresh)
  const index = videos.length ? Math.min(current, videos.length - 1) : 0
  const v = videos[index]
  const categoryName = useCategoryName(v?.primary_category_id)

  if (!v) return null

  return (
    <div className="px-4">
      <motion.div
        key={v.id}
        initial={{ opacity: 0.8 }}
        animate={{ opacity: 1 }}
        role="button"
        tabIndex={0}
        onClick={() => navigate(`/videos/${v.id}`)}
        onKeyDown={(e: { key: string }) => { if (e.key === 'Enter') navigate(`/videos/${v.id}`) }}
        className="relative w-full aspect-video rounded-[14px] overflow-hidden cursor-pointer bg-surface"
      >
        {v.thumbnail_url
          ? <img src={v.thumbnail_url} alt={v.title} onError={(e: { currentTarget: { style: { display: string } } }) => { e.currentTarget.style.display = 'none' }} className="w-full h-full object-cover" />
          : <div className="w-full h-full bg-gradient-to-br from-[#0d1a35] to-[#1a0b2e]" />
        }

        <div className="absolute inset-0 bg-gradient-to-t from-navy/95 via-navy/30 to-transparent pointer-events-none" />

        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-[44px] h-[44px] rounded-full bg-primary/25 border-2 border-primary/50 flex items-center justify-center">
            <PlayIcon size={18} />
          </div>
        </div>

        <div className="absolute bottom-0 left-0 right-0 p-4">
          <div className="inline-flex items-center gap-1 bg-secondary/25 border border-secondary/50 rounded-[6px] px-2 py-1 mb-2">
            <span className="text-[10px] font-bold text-secondary-light tracking-wide">★ ফিচার্ড</span>
          </div>
          <div className="text-[15px] font-bold text-white leading-[1.3] mb-2 line-clamp-2">{v.title}</div>
          <div className="flex items-center gap-2">
            {categoryName && (
              <span className="text-[10px] text-[#9CA3AF] bg-white/10 px-2 py-[2px] rounded-[4px] truncate max-w-[120px]">
                {categoryName}
              </span>
            )}
            <QualityBadge quality={v.quality} />
            <span className="text-[10px] text-[#9CA3AF]">⏱ {formatDuration(v.duration_seconds)}</span>
          </div>

          {videos.length > 1 && (
            <div className="flex gap-[5px] mt-2">
              {videos.map((item, i) => (
                <div
                  key={item.id}
                  className={cx(
                    'h-[5px] rounded-[3px] transition-all duration-300',
                    i === index ? 'w-[14px] bg-primary' : 'w-[5px] bg-white/25',
                  )}
                />
              ))}
            </div>
          )}
        </div>
      </motion.div>
    </div>
  )
}

// ─── Private helpers ──────────────────────────────────────────────────────────
function PlayIcon({ size = 14, className = '' }: { size?: number; className?: string }) {
  return (
    <div className={cx('flex items-center justify-center', className)}>
      <svg width={size} height={size} viewBox="0 0 24 24" fill="rgba(255,255,255,0.7)">
        <polygon points="5,3 19,12 5,21" />
      </svg>
    </div>
  )
}
