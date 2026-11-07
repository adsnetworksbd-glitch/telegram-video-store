import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import type { Package } from '@/types'
import { formatBDT, formatAccessDuration, cx } from '@/utils'
import { Skeleton } from '@/components/ui'

// ─── Package Card ─────────────────────────────────────────────────────────────
interface PackageCardProps {
  pkg: Package
  variant?: 'grid' | 'horizontal'
}

export function PackageCard({ pkg, variant = 'grid' }: PackageCardProps) {
  const navigate = useNavigate()
  const hasDiscount = pkg.discount_percentage > 0

  if (variant === 'horizontal') {
    return (
      <motion.div
        whileTap={{ scale: 0.97 }}
        onClick={() => navigate(`/packages/${pkg.id}`)}
        className="w-[200px] flex-shrink-0 bg-card border border-border rounded-card overflow-hidden cursor-pointer"
      >
        <div className="relative h-[90px] flex items-center justify-center bg-gradient-navy">
          {pkg.thumbnail_url
            ? <img src={pkg.thumbnail_url} alt={pkg.name} onError={(e: { currentTarget: { style: { display: string } } }) => { e.currentTarget.style.display = 'none' }} className="w-full h-full object-cover absolute inset-0" />
            : <span className="text-3xl">📦</span>
          }
          <div className="absolute inset-0 bg-gradient-to-t from-navy/70 to-transparent" />
          {hasDiscount && (
            <div className="absolute top-2 right-2 bg-danger/90 text-white text-[9px] font-bold px-[6px] py-[2px] rounded-[4px]">
              {pkg.discount_percentage}% ছাড়
            </div>
          )}
        </div>
        <div className="p-[10px]">
          <div className="text-[12px] font-semibold text-white mb-[2px] line-clamp-1">{pkg.name}</div>
          <div className="text-[10px] text-[#6B7280] mb-[6px]">{pkg.video_count}টি ভিডিও</div>
          <div className="flex items-baseline gap-[5px]">
            <span className="text-[14px] font-bold text-primary">{formatBDT(pkg.price_bdt)}</span>
            {hasDiscount && (
              <span className="text-[10px] text-[#6B7280] line-through">{formatBDT(pkg.original_price_bdt)}</span>
            )}
          </div>
        </div>
      </motion.div>
    )
  }

  // Grid variant
  return (
    <motion.div
      whileTap={{ scale: 0.97 }}
      onClick={() => navigate(`/packages/${pkg.id}`)}
      className="bg-card border border-border rounded-card overflow-hidden cursor-pointer"
    >
      <div className="relative h-[80px] flex items-center justify-center bg-gradient-navy">
        {pkg.thumbnail_url
          ? <img src={pkg.thumbnail_url} alt={pkg.name} onError={(e: { currentTarget: { style: { display: string } } }) => { e.currentTarget.style.display = 'none' }} className="w-full h-full object-cover absolute inset-0" />
          : <span className="text-2xl">📦</span>
        }
        <div className="absolute inset-0 bg-gradient-to-t from-navy/70 to-transparent" />
        {hasDiscount && (
          <div className="absolute top-[6px] right-[6px] bg-danger/90 text-white text-[9px] font-bold px-[6px] py-[2px] rounded-[4px]">
            {pkg.discount_percentage}% ছাড়
          </div>
        )}
      </div>
      <div className="p-[9px]">
        <div className="text-[12px] font-semibold text-white mb-[2px] line-clamp-1">{pkg.name}</div>
        <div className="text-[10px] text-[#6B7280] mb-[6px]">{pkg.video_count}টি ভিডিও</div>
        <div className="flex items-baseline gap-[5px]">
          <span className="text-[14px] font-bold text-primary">{formatBDT(pkg.price_bdt)}</span>
          {hasDiscount && (
            <span className="text-[10px] text-[#6B7280] line-through">{formatBDT(pkg.original_price_bdt)}</span>
          )}
        </div>
        <div className="text-[9px] text-[#6B7280] mt-[2px]">
          {formatAccessDuration(pkg.duration_type === 'lifetime' ? 0 : pkg.duration_hours)}
        </div>
      </div>
    </motion.div>
  )
}

// ─── Package Card Skeleton ────────────────────────────────────────────────────
export function PackageCardSkeleton({ variant = 'grid' }: { variant?: 'grid' | 'horizontal' }) {
  const w = variant === 'horizontal' ? 'w-[200px] flex-shrink-0' : ''
  return (
    <div className={cx('bg-card border border-border rounded-card overflow-hidden', w)}>
      <Skeleton className={variant === 'horizontal' ? 'h-[90px] w-full' : 'h-[80px] w-full'} />
      <div className="p-[9px] space-y-2">
        <Skeleton className="h-3 w-3/4 rounded" />
        <Skeleton className="h-3 w-1/2 rounded" />
      </div>
    </div>
  )
}
