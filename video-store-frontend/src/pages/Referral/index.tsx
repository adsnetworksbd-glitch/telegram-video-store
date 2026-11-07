import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { referralApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import type { Referral, ReferralInfo } from '@/types'
import { useConfigStore } from '@/store'
import { usePaginatedList } from '@/hooks/usePaginatedList'
import { getTelegram } from '@/hooks/useTelegram'
import { SubHeader, PageWrapper } from '@/components/layout'
import { Skeleton, EmptyState, ErrorState, InlineError, LoadMoreButton, toast } from '@/components/ui'
import { formatBDT, formatDate } from '@/utils'

// Referral page. Whether the programme is on is an admin switch
// (AppConfig.referral_enabled); the code, link, counts and rewards all come from
// the Backend — no reward amount is hardcoded here.

export default function ReferralPage() {
  const navigate = useNavigate()
  const { appConfig } = useConfigStore()
  const enabled = appConfig?.referral_enabled !== false

  const [info, setInfo] = useState<ReferralInfo | null>(null)
  const [infoError, setInfoError] = useState<string | null>(null)
  const [infoLoading, setInfoLoading] = useState(true)

  const history = usePaginatedList<Referral>(
    (page) => referralApi.history({ page }).then((r) => r.data),
    [enabled],
  )

  async function loadInfo() {
    setInfoLoading(true); setInfoError(null)
    try { setInfo((await referralApi.info()).data) }
    catch (e) { setInfoError(getErrorMessage(e, 'Referral তথ্য লোড করা যায়নি।')) }
    finally { setInfoLoading(false) }
  }
  useEffect(() => { if (enabled) void loadInfo() }, [enabled])

  const copy = (text: string, label: string) =>
    navigator.clipboard?.writeText(text).then(() => toast(`${label} কপি হয়েছে`, 'success')).catch(() => toast('কপি করা যায়নি।', 'error'))

  function share() {
    if (!info?.referral_link) return
    const url = `https://t.me/share/url?url=${encodeURIComponent(info.referral_link)}`
    const tg = getTelegram()
    if (tg?.initData && typeof tg.openTelegramLink === 'function') tg.openTelegramLink(url)
    else window.open(url, '_blank', 'noopener,noreferrer')
  }

  if (!enabled) {
    return (
      <PageWrapper hasBottomNav={false}>
        <SubHeader title="Referral" />
        <EmptyState icon="🎯" title="Referral প্রোগ্রাম এখন বন্ধ আছে" description="চালু হলে এখানে আপনার Referral Code ও Reward দেখতে পাবেন।" />
        <div className="px-4"><button onClick={() => navigate('/account')} className="btn-ghost">← অ্যাকাউন্টে ফিরুন</button></div>
      </PageWrapper>
    )
  }

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="Referral" />
      <div className="px-4 py-4 space-y-4">
        {infoLoading && <Skeleton className="h-[150px] w-full rounded-[12px]" />}
        {!infoLoading && infoError && !info && <ErrorState message={infoError} onRetry={() => void loadInfo()} />}

        {info && (
          <div className="bg-card border border-border rounded-[12px] p-4 space-y-3">
            <p className="text-[11px] text-[#6B7280] font-semibold">🎯 আমার Referral Code</p>
            <div className="flex items-center gap-2 bg-surface border border-border rounded-[9px] px-3 py-2">
              <span className="text-[14px] font-bold text-primary font-mono flex-1 break-all">{info.referral_code}</span>
              <button onClick={() => void copy(info.referral_code, 'Code')} className="px-[10px] py-1 rounded-[6px] border border-primary/30 bg-primary/10 text-primary text-[10px] font-semibold">Copy</button>
            </div>
            {info.referral_link && (
              <div className="flex items-center gap-2">
                <p className="text-[10px] text-[#9CA3AF] font-mono flex-1 break-all">{info.referral_link}</p>
                <button onClick={() => void copy(info.referral_link, 'লিংক')} className="px-[10px] py-1 rounded-[6px] border border-border text-[#9CA3AF] text-[10px] font-semibold">Copy</button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-surface border border-border rounded-[10px] px-3 py-2">
                <p className="text-[10px] text-[#6B7280]">Refer করা</p>
                <p className="text-[15px] font-bold text-white">{info.referral_count} জন</p>
              </div>
              <div className="bg-surface border border-border rounded-[10px] px-3 py-2">
                <p className="text-[10px] text-[#6B7280]">মোট Reward</p>
                <p className="text-[15px] font-bold text-white">{formatBDT(info.reward_total_bdt)}</p>
              </div>
            </div>
            {info.referral_link && <button onClick={share} className="btn-primary">✈️ Telegram-এ শেয়ার করুন</button>}
          </div>
        )}

        <div>
          <p className="text-[11px] text-[#6B7280] font-semibold uppercase tracking-[0.4px] mb-2">Referral ইতিহাস</p>
          {history.loading && <Skeleton className="h-[60px] w-full rounded-[12px]" />}
          {!history.loading && history.error && history.items.length === 0 && <InlineError onRetry={() => void history.reload()} />}
          {!history.loading && !history.error && history.items.length === 0 && (
            <p className="text-[12px] text-[#6B7280] bg-card border border-border rounded-[12px] px-3 py-4 text-center">এখনো কেউ আপনার কোডে যোগ দেয়নি।</p>
          )}
          <div className="space-y-2">
            {history.items.map((r) => (
              <div key={r.id} className="bg-card border border-border rounded-[12px] px-3 py-[10px] flex justify-between items-center">
                <div>
                  <p className="text-[12px] text-white font-semibold">নতুন সদস্য</p>
                  <p className="text-[10px] text-[#6B7280]">{formatDate(r.created_at)} · {r.status}</p>
                </div>
                <span className="text-[12px] font-bold text-[#6EE7B7]">
                  {r.reward_amount_bdt != null ? `+${formatBDT(r.reward_amount_bdt)}` : '—'}
                </span>
              </div>
            ))}
          </div>
          {history.hasMore && <div className="mt-3"><LoadMoreButton onClick={() => void history.loadMore()} loading={history.loadingMore} /></div>}
        </div>
      </div>
    </PageWrapper>
  )
}
