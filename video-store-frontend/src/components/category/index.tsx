import { useState } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import type { Category } from '@/types'
import { cx } from '@/utils'
import { Skeleton } from '@/components/ui'

// Decorative gradients only (no business meaning). The picture itself comes
// from the Backend (category.thumbnail_url); gradients are the fallback.
const TILE_GRADIENTS = [
  'from-[#0d1a35] to-[#1a0b2e]',
  'from-[#0d2a1a] to-[#122a18]',
  'from-[#1a0d2a] to-[#250b38]',
  'from-[#2a1a0d] to-[#321a08]',
  'from-[#1a1a3a] to-[#0d1230]',
  'from-[#0d2a2a] to-[#0a2525]',
]
const BUBBLE_TONES = [
  'bg-primary/12 border-primary/25',
  'bg-secondary/12 border-secondary/25',
  'bg-success/12 border-success/25',
  'bg-warning/10 border-warning/20',
  'bg-danger/10 border-danger/20',
]

function FolderIcon({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  )
}

interface CategoryCardProps {
  category: Category
  /** Position in the list — only used to rotate decorative colours. */
  index?: number
  /** 'tile' = 2-column grid card, 'bubble' = round icon for horizontal rows */
  variant?: 'tile' | 'bubble'
}

export function CategoryCard({ category, index = 0, variant = 'tile' }: CategoryCardProps) {
  const navigate = useNavigate()
  const [imgFailed, setImgFailed] = useState(false)
  const showImg = Boolean(category.thumbnail_url) && !imgFailed
  const open = () => navigate(`/categories/${category.id}`)
  const countLabel = `${category.video_count}টি ভিডিও`

  if (variant === 'bubble') {
    return (
      <motion.button
        whileTap={{ scale: 0.93 }}
        onClick={open}
        className="flex flex-col items-center gap-[6px] flex-shrink-0 cursor-pointer bg-transparent border-none p-0"
      >
        <div
          className={cx(
            'relative w-[52px] h-[52px] rounded-[14px] flex items-center justify-center border overflow-hidden',
            BUBBLE_TONES[index % BUBBLE_TONES.length],
          )}
        >
          {showImg
            ? <img src={category.thumbnail_url} alt="" loading="lazy" onError={() => setImgFailed(true)} className="w-full h-full object-cover" />
            : <FolderIcon />}
        </div>
        <span className="text-[10px] text-[#9CA3AF] font-medium text-center max-w-[60px] truncate">{category.name}</span>
        <span className="text-[9px] text-[#6B7280]">{countLabel}</span>
      </motion.button>
    )
  }

  return (
    <motion.button
      whileTap={{ scale: 0.96 }}
      onClick={open}
      className={cx(
        'relative h-[90px] w-full text-left rounded-[12px] border border-border overflow-hidden cursor-pointer bg-gradient-to-br p-0',
        TILE_GRADIENTS[index % TILE_GRADIENTS.length],
      )}
    >
      {showImg && (
        <img
          src={category.thumbnail_url}
          alt=""
          loading="lazy"
          onError={() => setImgFailed(true)}
          className="absolute inset-0 w-full h-full object-cover opacity-40"
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-navy/90 to-transparent" />
      <div className="absolute bottom-0 left-0 right-0 p-[10px]">
        <p className="text-[13px] font-bold text-white truncate">{category.name}</p>
        <p className="text-[10px] text-white/55">{countLabel}</p>
      </div>
    </motion.button>
  )
}

export function CategoryCardSkeleton({ variant = 'tile' }: { variant?: 'tile' | 'bubble' }) {
  if (variant === 'bubble') {
    return (
      <div className="flex flex-col items-center gap-[6px] flex-shrink-0">
        <Skeleton className="w-[52px] h-[52px] rounded-[14px]" />
        <Skeleton className="w-[44px] h-2 rounded" />
      </div>
    )
  }
  return <Skeleton className="h-[90px] rounded-[12px]" />
}

/** Horizontal scrolling row used on the Home page. */
export function CategoryRow({ categories, isLoading = false }: { categories: Category[]; isLoading?: boolean }) {
  return (
    <div className="flex gap-[12px] px-4 overflow-x-auto">
      {isLoading
        ? Array.from({ length: 5 }).map((_, i) => <CategoryCardSkeleton key={i} variant="bubble" />)
        : categories.map((c, i) => <CategoryCard key={c.id} category={c} index={i} variant="bubble" />)}
    </div>
  )
}
