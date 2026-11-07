import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import type { AccessStatus, AvailableMethods } from '@/types'
import { formatBDT, formatAccessDuration, formatTimeLeft } from '@/utils'
import { Spinner } from '@/components/ui'
import { useOpenSource } from '@/hooks/useOpenSource'
import { AccessStateCard } from './AccessState'

// ─── Smart Access Button ──────────────────────────────────────────────────────
// Renders the correct button(s) based on access status & available methods.
// Admin controls which methods are visible — no hardcoding.

interface AccessButtonProps {
  contentType: 'video' | 'package'
  contentId: string
  access: AccessStatus
  methods: AvailableMethods
  priceBdt: number
  priceLabelSuffix?: string  // e.g. "5.00 USDT" (omit when the rate is unknown)
  /** Ads required to unlock — from the content record (admin controlled). */
  adsRequired?: number
  /** Ads-unlock access length in hours, 0 = lifetime (admin controlled). */
  adsDurationHours?: number
  /** Purchase access length in hours, 0 = lifetime (admin controlled). */
  purchaseDurationHours?: number
  /** Called when the Backend refuses to open the source (access no longer valid) — re-check access. */
  onAccessInvalid?: () => void
}

export function AccessButton({
  contentType,
  contentId,
  access,
  methods,
  priceBdt,
  priceLabelSuffix,
  adsRequired,
  adsDurationHours,
  purchaseDurationHours,
  onAccessInvalid,
}: AccessButtonProps) {
  const navigate = useNavigate()
  // Same source-opening path as My Purchases: the Backend re-checks access on
  // every open; a refusal (e.g. expired) re-asks the Backend what is valid now.
  const { openingId, open } = useOpenSource(onAccessInvalid)
  const loadingSource = openingId === contentId

  // Every label below is built from admin-controlled values — nothing is
  // hardcoded here. Parts whose value is unknown are simply left out.
  const adsSubtitle = [
    adsRequired !== undefined ? `${adsRequired}টি বিজ্ঞাপন` : null,
    adsDurationHours !== undefined ? `${formatAccessDuration(adsDurationHours)} Access` : null,
  ].filter(Boolean).join(' · ')
  const purchaseDurationLabel =
    purchaseDurationHours !== undefined ? `${formatAccessDuration(purchaseDurationHours)} Access` : ''
  const isPackage = contentType === 'package'

  // ── Case 1: Already has valid access ─────────────────────────────────────
  if (access.granted) {
    return (
      <div className="space-y-2">
        <AccessStateCard access={access} methods={methods} />

        {/* Open / Download button */}
        <motion.button
          whileTap={{ scale: 0.98 }}
          disabled={loadingSource}
          onClick={() => isPackage ? scrollToPackageVideos() : void open(contentId)}
          className="w-full py-[14px] px-4 rounded-btn border border-success/40 bg-success/8
                     flex items-center justify-between cursor-pointer"
        >
          <div className="flex items-center gap-3">
            <div className="w-[38px] h-[38px] rounded-[10px] bg-success/15 flex items-center justify-center">
              {loadingSource
                ? <Spinner size={18} />
                : (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="1.8" strokeLinecap="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                )
              }
            </div>
            <div className="text-left">
              <span className="text-[14px] font-bold text-[#6EE7B7] block">
                {isPackage ? 'ভিডিওগুলো দেখুন' : 'Open / Download করুন'}
              </span>
              <span className="text-[11px] text-[#6EE7B7]/70 block mt-[1px]">
                {isPackage ? 'Package Access আছে' : 'Access আছে · Source-এ Redirect হবে'}
              </span>
            </div>
          </div>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6EE7B7" strokeWidth="2" strokeLinecap="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </motion.button>
      </div>
    )
  }

  // ── Case 2: Free video ────────────────────────────────────────────────────
  if (methods.is_free) {
    return (
      <motion.button
        whileTap={{ scale: 0.98 }}
        disabled={loadingSource}
        onClick={() => void open(contentId)}
        className="w-full py-[14px] px-4 rounded-btn border border-success/40 bg-success/8
                   flex items-center justify-between cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <div className="w-[38px] h-[38px] rounded-[10px] bg-success/15 flex items-center justify-center">
            {loadingSource ? <Spinner size={18} /> : <span className="text-[18px]">▶</span>}
          </div>
          <div className="text-left">
            <span className="text-[14px] font-bold text-[#6EE7B7] block">বিনামূল্যে দেখুন / Download করুন</span>
            <span className="text-[11px] text-[#6EE7B7]/70 block mt-[1px]">এই ভিডিওটি সম্পূর্ণ বিনামূল্যে</span>
          </div>
        </div>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6EE7B7" strokeWidth="2" strokeLinecap="round">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </motion.button>
    )
  }

  // ── Case 3: No access — show unlock options ───────────────────────────────
  const hasAds      = methods.ads_unlock
  const hasPurchase = methods.purchase
  const bothEnabled = hasAds && hasPurchase

  if (!hasAds && !hasPurchase) {
    return (
      <div className="space-y-[10px]">
        <AccessStateCard access={access} methods={methods} />
        <div className="bg-card border border-border rounded-[12px] py-4 px-4 text-center">
          <p className="text-[13px] text-[#6B7280]">এই মুহূর্তে উপলব্ধ নয়</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-[10px]">
      <AccessStateCard access={access} methods={methods} />

      {/* Watch Ads button */}
      {hasAds && (
        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={() => navigate(`/${contentType === 'video' ? 'videos' : 'packages'}/${contentId}/watch-ads`)}
          className="w-full py-[14px] px-4 rounded-btn border-none bg-gradient-blue
                     flex items-center justify-between relative overflow-hidden cursor-pointer"
        >
          {/* decorative circle */}
          <div className="absolute top-[-20px] right-[-20px] w-[80px] h-[80px] rounded-full bg-white/6" />

          <div className="flex items-center gap-3 relative">
            <div className="w-[38px] h-[38px] rounded-[10px] bg-white/15 flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round">
                <polygon points="23 7 16 12 23 17 23 7" />
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
              </svg>
            </div>
            <div className="text-left">
              <span className="text-[14px] font-bold text-white block">বিজ্ঞাপন দেখে Unlock করুন</span>
              {adsSubtitle && (
                <span className="text-[11px] text-white/70 block mt-[1px]">{adsSubtitle}</span>
              )}
            </div>
          </div>
          <div className="bg-white/20 rounded-[8px] px-[10px] py-1 relative">
            <span className="text-[12px] font-bold text-white">বিনামূল্যে</span>
          </div>
        </motion.button>
      )}

      {/* OR divider */}
      {bothEnabled && (
        <div className="flex items-center gap-3">
          <div className="flex-1 h-px bg-border" />
          <span className="text-[11px] text-[#6B7280]">অথবা</span>
          <div className="flex-1 h-px bg-border" />
        </div>
      )}

      {/* Buy Now button */}
      {hasPurchase && (
        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={() => navigate(`/${contentType === 'video' ? 'videos' : 'packages'}/${contentId}/purchase`)}
          className="w-full py-[14px] px-4 rounded-btn border border-secondary/50 bg-secondary/10
                     flex items-center justify-between cursor-pointer"
        >
          <div className="flex items-center gap-3">
            <div className="w-[38px] h-[38px] rounded-[10px] bg-secondary/20 flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" strokeWidth="1.8" strokeLinecap="round">
                <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
                <line x1="1" y1="10" x2="23" y2="10" />
              </svg>
            </div>
            <div className="text-left">
              <span className="text-[14px] font-bold text-[#C4B5FD] block">এখনই কিনুন</span>
              {purchaseDurationLabel && (
                <span className="text-[11px] text-[#A78BFA]/70 block mt-[1px]">{purchaseDurationLabel}</span>
              )}
            </div>
          </div>
          <div className="text-right">
            <span className="text-[16px] font-extrabold text-[#A78BFA] block">{formatBDT(priceBdt)}</span>
            {priceLabelSuffix && (
              <span className="text-[10px] text-[#A78BFA]/60 block">≈ {priceLabelSuffix}</span>
            )}
          </div>
        </motion.button>
      )}
    </div>
  )
}

// ─── Helper: jump to the included-videos list on Package Details ──────────────
function scrollToPackageVideos() {
  document.getElementById('package-videos')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ─── Access Status Badge ──────────────────────────────────────────────────────
export function AccessStatusBadge({ access }: { access: AccessStatus }) {
  if (!access.granted) {
    if (access.expired) {
      return (
        <span className="inline-flex items-center gap-1 text-[9px] font-bold px-[7px] py-[3px] rounded-[5px] bg-danger/10 text-[#FCA5A5] border border-danger/20">
          ✗ Expired
        </span>
      )
    }
    return null
  }

  if (access.is_lifetime) {
    return (
      <span className="inline-flex items-center gap-1 text-[9px] font-bold px-[7px] py-[3px] rounded-[5px] bg-primary/10 text-[#93C5FD] border border-primary/25">
        ♾ Lifetime
      </span>
    )
  }

  if (access.expires_at) {
    return (
      <span className="inline-flex items-center gap-1 text-[9px] font-bold px-[7px] py-[3px] rounded-[5px] bg-success/10 text-[#6EE7B7] border border-success/25">
        ⏰ {formatTimeLeft(access.expires_at)}
      </span>
    )
  }

  return null
}

export * from './AccessState'
export * from './SourceNote'
