import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { packagesApi, accessApi } from '@/api'
import { connectionMessage, getErrorStatus } from '@/api/client'
import type { PackageDetail } from '@/types'
import { useConfigStore } from '@/store'
import { useAccessRevalidation } from '@/hooks/useAccessRevalidation'
import { SubHeader, PageWrapper } from '@/components/layout'
import { AccessButton } from '@/components/access'
import { VideoCard } from '@/components/video'
import { Skeleton, ErrorState } from '@/components/ui'
import { formatBDT, formatAccessDuration, bdtToUsdt } from '@/utils'

export default function PackageDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { appConfig } = useConfigStore()
  const [pkg, setPkg]         = useState<PackageDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [descExpanded, setDescExpanded] = useState(false)

  const load = useCallback(async (pkgId: string) => {
    try {
      setLoading(true)
      setError(null)
      setNotFound(false)
      const res = await packagesApi.detail(pkgId)
      setPkg(res.data)
    } catch (e) {
      setPkg(null)
      if (getErrorStatus(e) === 404) setNotFound(true)
      else setError(connectionMessage(e) ?? 'Package লোড হয়নি।')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!id) return
    setDescExpanded(false)
    void load(id)
  }, [id, load])

  // Re-ask the Backend when the package access may have run out. Only `access`
  // is replaced, only with the Backend's answer.
  const refreshAccess = useCallback(() => {
    if (!id) return
    accessApi.checkPackage(id)
      .then((r) => setPkg((p) => (p && p.id === id ? { ...p, access: r.data } : p)))
      .catch(() => { /* keep what is shown */ })
  }, [id])
  useAccessRevalidation(pkg?.access, refreshAccess)

  if (loading) return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="Package" />
      <Skeleton className="w-full h-[120px]" />
      <div className="px-4 pt-4 space-y-3">
        <Skeleton className="h-5 w-2/3 rounded" />
        <Skeleton className="h-4 w-full rounded" />
        <Skeleton className="h-16 w-full rounded-[12px]" />
        <Skeleton className="h-12 w-full rounded-[14px]" />
      </div>
    </PageWrapper>
  )
  if (notFound) return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="Package" />
      <ErrorState message="Package টি পাওয়া যায়নি বা আর উপলব্ধ নেই।" />
    </PageWrapper>
  )
  if (error || !pkg) return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="Package" />
      <ErrorState message={error ?? 'Package লোড হয়নি।'} onRetry={() => id && load(id)} />
    </PageWrapper>
  )

  // USDT estimate only when the admin-set rate is available (never a guessed rate).
  const rate = appConfig?.usdt_to_bdt_rate
  const usdtLabel = rate ? `${bdtToUsdt(pkg.price_bdt, rate).toFixed(2)} USDT` : undefined
  const savings = pkg.original_price_bdt - pkg.price_bdt
  const durationHours = pkg.duration_type === 'lifetime' ? 0 : pkg.duration_hours
  const description = pkg.description ?? ''
  const included = pkg.included_videos ?? []

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="Package Details" />

      {/* Hero */}
      <div className="w-full h-[120px] bg-gradient-to-br from-[#0d1a35] to-[#1a0b2e] relative flex items-center justify-center overflow-hidden">
        {pkg.thumbnail_url
          ? <img src={pkg.thumbnail_url} onError={(e: { currentTarget: { style: { display: string } } }) => { e.currentTarget.style.display = 'none' }} className="w-full h-full object-cover absolute inset-0" alt="" />
          : <span className="text-[48px]">📦</span>
        }
        <div className="absolute inset-0 bg-gradient-to-t from-navy/80 to-transparent" />
        {pkg.discount_percentage > 0 && (
          <div className="absolute top-[10px] right-[10px] bg-danger/90 text-white text-[10px] font-bold px-[8px] py-[3px] rounded-[5px]">
            {pkg.discount_percentage}% ছাড়
          </div>
        )}
      </div>

      <div className="px-4 py-4 space-y-4">
        <div>
          <h1 className="text-[17px] font-bold text-white mb-2">{pkg.name}</h1>
          {description && (
            <>
              <p className={`text-[12px] text-[#9CA3AF] leading-[1.5] ${!descExpanded ? 'line-clamp-2' : ''}`}>{description}</p>
              {description.length > 80 && (
                <button onClick={() => setDescExpanded((v) => !v)} className="text-[12px] text-primary mt-1">
                  {descExpanded ? 'কম দেখুন ▴' : 'আরও ▾'}
                </button>
              )}
            </>
          )}
        </div>

        {/* Price block */}
        <div className="bg-primary/6 border border-primary/15 rounded-[12px] px-3 py-3 flex justify-between items-center">
          <div>
            <p className="text-[22px] font-extrabold text-primary">{formatBDT(pkg.price_bdt)}</p>
            {savings > 0 && <p className="text-[11px] text-[#6B7280] line-through">{formatBDT(pkg.original_price_bdt)}</p>}
          </div>
          <div className="text-right">
            {savings > 0 && (
              <p className="text-[11px] font-bold text-[#FCA5A5] bg-danger/12 px-[10px] py-1 rounded-[6px]">
                {formatBDT(savings)} সাশ্রয়
              </p>
            )}
            <p className="text-[10px] text-[#6B7280] mt-1">{formatAccessDuration(durationHours)}</p>
          </div>
        </div>

        {/* Access options — admin controlled via available_methods */}
        <AccessButton
          contentType="package"
          contentId={pkg.id}
          access={pkg.access}
          methods={pkg.available_methods}
          priceBdt={pkg.price_bdt}
          priceLabelSuffix={usdtLabel}
          adsRequired={pkg.ads_required}
          purchaseDurationHours={durationHours}
        />

        <div className="h-px bg-border" />

        {/* Included videos */}
        <div id="package-videos" style={{ scrollMarginTop: 'calc(var(--app-safe-top) + 64px)' }}>
          <p className="text-[11px] text-[#6B7280] font-semibold uppercase tracking-[0.4px] mb-3">
            অন্তর্ভুক্ত ভিডিও ({pkg.video_count}টি)
          </p>
          {included.length === 0 ? (
            <p className="text-[12px] text-[#6B7280]">এই Package-এ এখনো কোনো ভিডিও দেখানো যাচ্ছে না।</p>
          ) : (
            <div className="grid grid-cols-2 gap-[10px]">
              {included.map((v) => <VideoCard key={v.id} video={v} />)}
            </div>
          )}
        </div>
      </div>
    </PageWrapper>
  )
}
