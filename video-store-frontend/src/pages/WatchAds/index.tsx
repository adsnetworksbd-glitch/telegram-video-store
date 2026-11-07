import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { adsApi, videosApi, packagesApi, accessApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import type { AdSession, VideoDetail, PackageDetail } from '@/types'
import { SubHeader, PageWrapper } from '@/components/layout'
import { ProgressBar, Spinner, ErrorState, Button, Countdown, Badge } from '@/components/ui'
import { AccessStateCard } from '@/components/access'
import { showRewardedAd } from '@/utils/rewardedAd'
import { useAdNavigationLock } from '@/hooks/useAdNavigationLock'
import { hasNativeBack } from '@/hooks/useTelegram'
import { formatDuration, formatAccessDuration } from '@/utils'

// ─── Watch Ads Page ───────────────────────────────────────────────────────────
// Security model: an ad counts ONLY when the Backend says so (S2S callback from
// the ad network). This page shows ads and polls the session; the ad SDK
// finishing is displayed as "waiting for verification", never as an unlock.

type Screen = 'loading' | 'error' | 'has_access' | 'unavailable' | 'busy' | 'ready' | 'expired' | 'unlocked'
type AdPhase = 'idle' | 'loading' | 'showing' | 'reported' | 'unavailable' | 'failed'
type Content = VideoDetail | PackageDetail

const POLL_MS = 5000          // UI polling cadence only
const VERIFY_WAIT_MS = 20000  // how long "next ad" stays locked after an ad finishes

// Dedupe session creation: React StrictMode (dev) mounts effects twice and a
// second /session/start would hit the "active session exists" 409.
const inflightStarts = new Map<string, Promise<AdSession>>()
function startSessionOnce(type: 'video' | 'package', id: string): Promise<AdSession> {
  const k = `${type}:${id}`
  let p = inflightStarts.get(k)
  if (!p) {
    p = adsApi.startSession({ content_type: type, content_id: id }).then((r) => r.data)
    inflightStarts.set(k, p)
    void p.then(() => inflightStarts.delete(k), () => inflightStarts.delete(k))
  }
  return p
}

export default function WatchAdsPage() {
  const { id } = useParams<{ id: string }>()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  // Route decides the type (/videos/:id/watch-ads vs /packages/:id/watch-ads)
  const contentType: 'video' | 'package' = pathname.startsWith('/packages') ? 'package' : 'video'
  const basePath = contentType === 'video' ? '/videos' : '/packages'

  const [screen, setScreen]   = useState<Screen>('loading')
  const [error, setError]     = useState<string | null>(null)
  const [content, setContent] = useState<Content | null>(null)
  const [session, setSession] = useState<AdSession | null>(null)
  const [adPhase, setAdPhase] = useState<AdPhase>('idle')
  const [pollFailures, setPollFailures] = useState(0)
  const [awaiting, setAwaiting] = useState<{ base: number; until: number } | null>(null)
  // An ad finished (SDK) but the Backend never confirmed it within the wait window
  const [unverified, setUnverified] = useState(false)

  const runRef = useRef(0)
  const pollRef = useRef<number | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) { window.clearTimeout(pollRef.current); pollRef.current = null }
  }, [])

  // ── Session end handling ────────────────────────────────────────────────
  // When the Backend refuses a poll (expired / forbidden) the unlock may still
  // have happened just before — ask the Backend, don't assume.
  const resolveEnded = useCallback(async (message: string) => {
    stopPolling()
    if (!id) return
    try {
      const r = contentType === 'video' ? await accessApi.checkVideo(id) : await accessApi.checkPackage(id)
      if (r.data.granted) { setScreen('unlocked'); return }
    } catch { /* fall through to expired */ }
    setError(message)
    setScreen('expired')
  }, [id, contentType, stopPolling])

  const handleCountdownExpire = useCallback(() => {
    void resolveEnded('Session-এর সময় শেষ হয়েছে।')
  }, [resolveEnded])

  // ── Init: load content, then (only if needed) start a session ───────────
  const init = useCallback(async () => {
    if (!id) return
    const run = ++runRef.current
    stopPolling()
    setScreen('loading'); setError(null); setSession(null)
    setAdPhase('idle'); setPollFailures(0); setAwaiting(null); setUnverified(false)
    try {
      const detail = contentType === 'video'
        ? (await videosApi.detail(id)).data
        : (await packagesApi.detail(id)).data
      if (run !== runRef.current) return
      setContent(detail)
      if (detail.access.granted) { setScreen('has_access'); return }
      if (!detail.available_methods.ads_unlock) { setScreen('unavailable'); return }

      const s = await startSessionOnce(contentType, id)
      if (run !== runRef.current) return
      setSession(s)
      setScreen('ready')
    } catch (e) {
      if (run !== runRef.current) return
      const status = (e as { status?: number })?.status
      const msg = getErrorMessage(e, 'Session শুরু করা যায়নি।')
      if (status === 409) {
        // Backend uses 409 for both "already has access" and "session already active"
        if (/access/i.test(msg)) { setScreen('has_access'); return }
        setScreen('busy'); setError(msg); return
      }
      setError(msg)
      setScreen('error')
    }
  }, [id, contentType, stopPolling])

  useEffect(() => {
    void init()
    // runRef is a plain run counter (not a DOM ref): bumping its CURRENT value invalidates in-flight runs
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { runRef.current++; stopPolling() }
  }, [init, stopPolling])

  // ── Poll the Backend for S2S-verified progress ──────────────────────────
  const sessionId = session?.session_id
  const serverToken = session?.server_token
  useEffect(() => {
    if (screen !== 'ready' || !sessionId || !serverToken) return
    let cancelled = false
    let failures = 0
    const tick = async () => {
      try {
        const r = await adsApi.checkSession(sessionId, serverToken)
        if (cancelled) return
        failures = 0
        setPollFailures(0)
        setSession(r.data)
        if (r.data.is_complete) { setScreen('unlocked'); return }
      } catch (e) {
        if (cancelled) return
        const status = (e as { status?: number })?.status
        if (status === 400 || status === 403 || status === 404) {
          void resolveEnded(getErrorMessage(e, 'Session শেষ হয়ে গেছে।'))
          return
        }
        failures += 1
        setPollFailures(failures)
      }
      pollRef.current = window.setTimeout(tick, POLL_MS)
    }
    pollRef.current = window.setTimeout(tick, POLL_MS)
    return () => { cancelled = true; stopPolling() }
  }, [screen, sessionId, serverToken, resolveEnded, stopPolling])

  // Unlock confirmation → success page (replace: Back must not return here)
  useEffect(() => {
    if (screen !== 'unlocked' || !id) return
    const t = window.setTimeout(() => navigate(`${basePath}/${id}/ads-success`, { replace: true }), 1500)
    return () => window.clearTimeout(t)
  }, [screen, id, basePath, navigate])

  const verified = session ? (session.s2s_verified_count ?? session.ads_completed) : 0
  const required = session?.ads_required ?? 0

  // "Next ad" stays locked briefly after an ad finishes, until the Backend confirms it
  useEffect(() => {
    if (!awaiting) return
    if (verified > awaiting.base) { setAwaiting(null); setUnverified(false); return }
    const t = window.setTimeout(() => { setAwaiting(null); setUnverified(true) }, Math.max(0, awaiting.until - Date.now()))
    return () => window.clearTimeout(t)
  }, [awaiting, verified])

  async function onWatchAd() {
    if (!session || adPhase === 'loading' || adPhase === 'showing' || awaiting) return
    setAdPhase('loading')
    setUnverified(false)
    const outcome = await showRewardedAd(session.network_config, session.session_id, () => setAdPhase('showing'))
    if (outcome === 'shown') {
      setAdPhase('reported')
      setAwaiting({ base: verified, until: Date.now() + VERIFY_WAIT_MS })
    } else {
      setAdPhase(outcome)
    }
  }

  // Block accidental Back / close only while an ad is actually loading or playing
  useAdNavigationLock(adPhase === 'loading' || adPhase === 'showing')

  const title = 'বিজ্ঞাপন দেখে Unlock করুন'

  // ── Non-ready screens ───────────────────────────────────────────────────
  if (screen === 'loading') return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <div className="flex items-center justify-center py-20"><Spinner size={32} /></div>
    </PageWrapper>
  )

  if (screen === 'error') return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <ErrorState message={error ?? 'Session শুরু করা যায়নি।'} onRetry={() => void init()} />
    </PageWrapper>
  )

  if (screen === 'has_access') return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <div className="px-4 py-6 space-y-4">
        {content && <ContentStrip content={content} contentType={contentType} />}
        {content && content.access.granted
          ? <AccessStateCard access={content.access} />
          : <p className="text-[13px] text-[#9CA3AF] text-center">এই কনটেন্টে আগে থেকেই Access আছে।</p>}
        <Button onClick={() => id && navigate(`${basePath}/${id}`, { replace: true })}>
          {contentType === 'video' ? 'ভিডিওতে যান' : 'Package-এ যান'}
        </Button>
      </div>
    </PageWrapper>
  )

  if (screen === 'unavailable') return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <div className="px-4 py-10 text-center space-y-4">
        <div className="text-4xl">🚫</div>
        <p className="text-[13px] text-[#9CA3AF]">এই কনটেন্টে বিজ্ঞাপন দেখে Unlock এখন চালু নেই।</p>
        <Button variant="ghost" onClick={() => navigate(-1)}>← ফিরে যান</Button>
      </div>
    </PageWrapper>
  )

  if (screen === 'busy') return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <div className="px-4 py-10 text-center space-y-4">
        <div className="text-4xl">⏳</div>
        <p className="text-[13px] text-white font-semibold">আগের একটি Ads Session এখনো চলমান</p>
        <p className="text-[12px] text-[#9CA3AF] leading-[1.6]">
          {error ?? ''}<br />কিছুক্ষণ পর আবার চেষ্টা করুন।
        </p>
        <Button onClick={() => void init()}>আবার চেষ্টা করুন</Button>
        <Button variant="ghost" onClick={() => navigate(-1)}>← ফিরে যান</Button>
      </div>
    </PageWrapper>
  )

  if (screen === 'expired') return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <div className="px-4 py-10 text-center space-y-4">
        <div className="text-4xl">⌛</div>
        <p className="text-[13px] text-white font-semibold">Session শেষ হয়ে গেছে</p>
        <p className="text-[12px] text-[#9CA3AF] leading-[1.6]">{error ?? 'নতুন করে শুরু করতে হবে।'}</p>
        <Button onClick={() => void init()}>নতুন Session শুরু করুন</Button>
        <Button variant="ghost" onClick={() => navigate(-1)}>← ফিরে যান</Button>
      </div>
    </PageWrapper>
  )

  if (screen === 'unlocked') return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} />
      <div className="px-4 py-12 text-center space-y-4">
        <div className="w-20 h-20 mx-auto rounded-full bg-success/10 border-2 border-success/30 flex items-center justify-center">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
        </div>
        <h1 className="text-[18px] font-bold text-white">Unlock নিশ্চিত হয়েছে</h1>
        <p className="text-[12px] text-[#9CA3AF]">Server সব বিজ্ঞাপন যাচাই করেছে।</p>
        <Button variant="success" onClick={() => id && navigate(`${basePath}/${id}/ads-success`, { replace: true })}>চালিয়ে যান →</Button>
      </div>
    </PageWrapper>
  )

  if (!session || !content) return null

  // ── Ready ────────────────────────────────────────────────────────────────
  const safeRequired = Math.max(required, 1)
  const completedAll = verified >= required
  const adBusy = adPhase === 'loading' || adPhase === 'showing'
  const nextLocked = adBusy || Boolean(awaiting)

  const adStatus = ADS_STATUS[adPhase]
  const verifyLabel = completedAll
    ? 'Server যাচাই সম্পন্ন হচ্ছে...'
    : awaiting
    ? 'Server-এর যাচাইয়ের অপেক্ষায়...'
    : verified > 0
    ? `${verified}টি বিজ্ঞাপন যাচাই হয়েছে`
    : 'এখনো কোনো বিজ্ঞাপন যাচাই হয়নি'

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={title} onBack={adBusy && !hasNativeBack() ? () => {} : undefined} />
      <div className="px-4 py-4 space-y-4">

        <ContentStrip content={content} contentType={contentType} />

        {/* Completion status */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[12px] text-[#9CA3AF]">সম্পন্ন (Server যাচাইকৃত)</span>
            <span className="text-[13px] font-bold text-primary">{verified} / {required}</span>
          </div>
          <ProgressBar value={Math.min(verified, safeRequired)} max={safeRequired} className="mb-3" />
          <div className="flex gap-[6px] justify-center flex-wrap">
            {Array.from({ length: required }).map((_, i) => (
              <div
                key={i}
                className={[
                  'w-[10px] h-[10px] rounded-full border-2 transition-all',
                  i < verified
                    ? 'bg-primary border-primary'
                    : i === verified
                    ? 'bg-transparent border-primary shadow-[0_0_0_2px_rgba(59,130,246,0.2)]'
                    : 'bg-card border-border',
                ].join(' ')}
              />
            ))}
          </div>
        </div>

        {/* Rewarded ad placement */}
        <div className="bg-card border border-border rounded-[14px] overflow-hidden">
          <div className="px-3 py-[10px] border-b border-border flex items-center justify-between">
            <span className="text-[10px] text-[#6B7280] font-semibold tracking-[0.5px]">
              বিজ্ঞাপন {Math.min(verified + 1, safeRequired)} / {required}
            </span>
            <span className="text-[11px] text-[#9CA3AF] flex items-center gap-1">
              Session: <Countdown expiresAt={session.expires_at} onExpire={handleCountdownExpire} className="text-warning" />
            </span>
          </div>
          <div className="h-[140px] flex flex-col items-center justify-center gap-3 bg-gradient-to-b from-[#0d1220] to-surface px-4 text-center">
            <div className="w-12 h-12 rounded-[12px] bg-primary/12 border border-primary/25 flex items-center justify-center">
              {adBusy
                ? <Spinner size={22} />
                : (
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#60A5FA" strokeWidth="1.8" strokeLinecap="round">
                    <polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                  </svg>
                )}
            </div>
            <span className="text-[12px] text-[#9CA3AF]">{adStatus.text}</span>
          </div>
          {/* Ad status + verification status */}
          <div className="px-3 py-[10px] space-y-[6px] border-t border-border">
            <div className="flex items-center gap-2">
              <div className={`w-[7px] h-[7px] rounded-full ${adStatus.dot}`} />
              <span className="text-[11px] text-[#9CA3AF]">বিজ্ঞাপন: <strong className="text-white font-semibold">{adStatus.label}</strong></span>
            </div>
            <div className="flex items-center gap-2">
              {(awaiting || completedAll) ? <Spinner size={10} /> : <div className={`w-[7px] h-[7px] rounded-full ${verified > 0 ? 'bg-success' : 'bg-border'}`} />}
              <span className="text-[11px] text-[#9CA3AF]">যাচাই: <strong className="text-white font-semibold">{verifyLabel}</strong></span>
            </div>
          </div>
        </div>

        {pollFailures >= 2 && (
          <div className="flex items-center gap-2 bg-warning/8 border border-warning/20 rounded-[10px] px-3 py-2">
            <span className="text-[11px] text-[#FCD34D]">সংযোগে সমস্যা — Server-এর সাথে যোগাযোগের আবার চেষ্টা চলছে।</span>
          </div>
        )}

        {(adPhase === 'unavailable' || adPhase === 'failed') && (
          <div className="flex items-center gap-2 bg-danger/8 border border-danger/20 rounded-[10px] px-3 py-2">
            <span className="text-[11px] text-[#FCA5A5]">
              {adPhase === 'unavailable'
                ? 'এই ডিভাইসে বিজ্ঞাপন চালু করা যায়নি। পরে আবার চেষ্টা করুন।'
                : 'বিজ্ঞাপন দেখানো যায়নি। আবার চেষ্টা করুন।'}
            </span>
          </div>
        )}

        {unverified && adPhase === 'reported' && !completedAll && (
          <div className="flex items-center gap-2 bg-danger/8 border border-danger/20 rounded-[10px] px-3 py-2">
            <span className="text-[11px] text-[#FCA5A5] leading-[1.5]">
              বিজ্ঞাপনটি Server যাচাই করেনি (সম্পূর্ণ না দেখলে বা বিজ্ঞাপন বন্ধ করে দিলে গণনা হয় না)। আবার চেষ্টা করুন।
            </span>
          </div>
        )}

        {/* Notice */}
        <div className="flex gap-2 bg-warning/8 border border-warning/20 rounded-[10px] p-3">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" strokeWidth="1.8" strokeLinecap="round" className="flex-shrink-0 mt-[1px]">
            <path d="m10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <span className="text-[11px] text-[#FCD34D] leading-[1.5]">
            Server যাচাই না হওয়া পর্যন্ত বিজ্ঞাপন গণনা হয় না। Session শেষ হওয়ার আগে সব বিজ্ঞাপন সম্পন্ন করুন।
          </span>
        </div>

        {!completedAll && (
          <Button onClick={onWatchAd} disabled={nextLocked} loading={adBusy}>
            {adBusy
              ? 'বিজ্ঞাপন চলছে...'
              : awaiting
              ? 'যাচাইয়ের অপেক্ষা...'
              : adPhase === 'unavailable' || adPhase === 'failed' || unverified
              ? 'আবার চেষ্টা করুন'
              : verified === 0 ? 'প্রথম বিজ্ঞাপন শুরু করুন' : 'পরবর্তী বিজ্ঞাপন'}
          </Button>
        )}
      </div>
    </PageWrapper>
  )
}

const ADS_STATUS: Record<AdPhase, { label: string; text: string; dot: string }> = {
  idle:        { label: 'প্রস্তুত',               text: 'বিজ্ঞাপন দেখতে নিচের বোতাম চাপুন',          dot: 'bg-border' },
  loading:     { label: 'লোড হচ্ছে',             text: 'বিজ্ঞাপন লোড হচ্ছে...',                    dot: 'bg-warning' },
  showing:     { label: 'চলছে',                  text: 'বিজ্ঞাপন চলছে — বন্ধ করবেন না',            dot: 'bg-warning' },
  reported:    { label: 'শেষ হয়েছে',            text: 'বিজ্ঞাপন শেষ। Server যাচাইয়ের অপেক্ষা...',  dot: 'bg-success' },
  unavailable: { label: 'চালু করা যায়নি',        text: 'বিজ্ঞাপন এখন উপলব্ধ নয়',                  dot: 'bg-danger' },
  failed:      { label: 'দেখানো যায়নি',          text: 'বিজ্ঞাপন দেখানো যায়নি',                    dot: 'bg-danger' },
}

// ─── Content Info Strip ───────────────────────────────────────────────────────
function ContentStrip({ content, contentType }: { content: Content; contentType: 'video' | 'package' }) {
  const isVideo = contentType === 'video'
  const v = content as VideoDetail
  const p = content as PackageDetail
  const thumb = isVideo ? v.thumbnail_url : p.thumbnail_url

  return (
    <div className="flex gap-[10px] bg-card border border-border rounded-[12px] p-[10px] items-center">
      <div className="w-16 h-10 rounded-[8px] bg-surface flex-shrink-0 flex items-center justify-center overflow-hidden">
        {thumb
          ? <img src={thumb} className="w-full h-full object-cover" alt="" />
          : <svg width="14" height="14" viewBox="0 0 24 24" fill="rgba(255,255,255,0.4)"><polygon points="5,3 19,12 5,21" /></svg>}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[12px] font-semibold text-white leading-[1.3] line-clamp-2">{isVideo ? v.title : p.name}</p>
        <div className="flex items-center gap-2 mt-[3px] flex-wrap">
          <span className="text-[10px] text-[#6B7280]">
            {isVideo ? `${v.quality} · ${formatDuration(v.duration_seconds)}` : `${p.video_count}টি ভিডিও`}
          </span>
          {isVideo && (
            <Badge variant="green">Unlock হলে {formatAccessDuration(v.ads_unlock_duration_hours)}</Badge>
          )}
        </div>
      </div>
    </div>
  )
}
