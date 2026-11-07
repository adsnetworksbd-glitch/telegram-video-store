import type { SourceType } from '@/types'
import { getSourceInfo, type SourceSupport } from '@/utils'
import { cx } from '@/utils'

// Tells the user which kind of source a video is stored on and how reliably the
// Mini App can open it. Unsupported / unverified types are flagged explicitly.

const TONE: Record<SourceSupport, { badge: string; text: string; label: string }> = {
  supported:  { badge: 'bg-success/10 text-[#6EE7B7] border-success/25',  text: 'text-[#6B7280]', label: 'সমর্থিত' },
  partial:    { badge: 'bg-warning/10 text-[#FCD34D] border-warning/25',  text: 'text-[#9CA3AF]', label: 'আংশিক সমর্থিত' },
  unverified: { badge: 'bg-danger/10 text-[#FCA5A5] border-danger/25',    text: 'text-[#FCA5A5]', label: 'নির্ভরযোগ্য নয়' },
}

export function SourceNote({ sourceType, className }: { sourceType: SourceType | null | undefined; className?: string }) {
  const info = getSourceInfo(sourceType)
  if (!info) return null
  const tone = TONE[info.support]
  return (
    <div className={cx('flex items-start gap-2', className)}>
      <span className={cx('flex-shrink-0 inline-flex items-center gap-1 text-[9px] font-bold px-[7px] py-[3px] rounded-[5px] border', tone.badge)}>
        {info.icon} {info.label} · {tone.label}
      </span>
      <p className={cx('text-[10px] leading-[1.5]', tone.text)}>{info.note}</p>
    </div>
  )
}
