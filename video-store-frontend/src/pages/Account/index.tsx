import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { userApi, entitlementsApi, ordersApi } from '@/api'
import { useUserStore, useConfigStore } from '@/store'
import { AppHeader, PageWrapper } from '@/components/layout'
import { getTelegram } from '@/hooks/useTelegram'
import { toast } from '@/components/ui'
import { formatBDT, formatDate, isHapticEnabled, setHapticEnabled, cx } from '@/utils'

// ─── My Account ───────────────────────────────────────────────────────────────
// Everything shown here comes from the Backend profile / counts. Balance is shown
// only when BOTH the app config and the user's profile say the wallet is on.

export default function AccountPage() {
  const navigate = useNavigate()
  const { profile, setProfile, unreadCount } = useUserStore()
  const appConfig = useConfigStore((s) => s.appConfig)

  const [activeCount, setActiveCount] = useState<number | null>(null)
  const [paidOrders, setPaidOrders]   = useState<number | null>(null)
  const [haptic, setHaptic] = useState(isHapticEnabled)

  // Fresh profile + counts; failures are non-fatal (cached profile stays visible)
  useEffect(() => {
    let alive = true
    userApi.profile().then((r) => { if (alive) setProfile(r.data) }).catch(() => {})
    entitlementsApi.list({ status: 'active', limit: 1 })
      .then((r) => { if (alive) setActiveCount(r.data.total) }).catch(() => {})
    ordersApi.history({ status: 'completed', limit: 1 })
      .then((r) => { if (alive) setPaidOrders(r.data.total) }).catch(() => {})
    return () => { alive = false }
  }, [setProfile])

  const tg = getTelegram()
  const tgUser = tg?.initDataUnsafe?.user
  const firstName = profile?.first_name || tgUser?.first_name || ''
  const lastName  = profile?.last_name  || tgUser?.last_name  || ''
  const username  = profile?.username   || tgUser?.username   || ''
  const photo     = profile?.photo_url  || tgUser?.photo_url  || ''
  const displayName = `${firstName} ${lastName}`.trim() || 'ব্যবহারকারী'
  const initial = (firstName || username || '?').slice(0, 1).toUpperCase()

  const walletOn = Boolean(appConfig?.wallet_enabled && profile?.wallet_enabled)
  const referralOn = appConfig?.referral_enabled !== false && Boolean(profile?.referral_code)

  const MENU = [
    { icon: '📋', label: 'Purchase History', sub: 'কেনা ভিডিও, Package ও Access', color: 'bg-primary/10', action: () => navigate('/my-purchases') },
    { icon: '💰', label: walletOn ? 'Balance ও Transactions' : 'Transactions', sub: 'লেনদেন ও Payment-এর ইতিহাস', color: 'bg-secondary/10', action: () => navigate('/transactions') },
    { icon: '🔔', label: 'Notifications', sub: unreadCount > 0 ? `${unreadCount}টি অপঠিত` : 'Payment, Access ও Reward-এর খবর', color: 'bg-primary/10', action: () => navigate('/notifications') },
    ...(referralOn ? [{ icon: '🎯', label: 'Referral ইতিহাস', sub: 'কোড শেয়ার ও Reward দেখুন', color: 'bg-success/10', action: () => navigate('/referral') }] : []),
    { icon: '❓', label: 'Support', sub: 'FAQ, যোগাযোগ ও সমস্যা জানান', color: 'bg-warning/10', action: () => navigate('/support') },
  ]

  async function copyReferral() {
    if (!profile?.referral_code) return
    try {
      await navigator.clipboard.writeText(profile.referral_code)
      toast('Referral Code কপি হয়েছে!', 'success')
    } catch {
      toast('কপি করা যায়নি।', 'error')
    }
  }

  function toggleHaptic() {
    const next = !haptic
    setHaptic(next)
    setHapticEnabled(next)
  }

  return (
    <PageWrapper>
      <AppHeader showSearch={false} showNotif={true} showProfile={false} />

      {/* Telegram profile */}
      <div className="flex flex-col items-center text-center px-4 py-6 border-b border-border">
        <div className="w-16 h-16 rounded-full bg-gradient-blue flex items-center justify-center text-[26px] font-bold text-white mb-3 border-2 border-primary/30 overflow-hidden">
          {photo
            ? <img src={photo} className="w-full h-full object-cover" alt="" referrerPolicy="no-referrer" />
            : initial}
        </div>
        <h1 className="text-[15px] font-bold text-white">{displayName}</h1>
        {username && <p className="text-[11px] text-[#6B7280]">@{username}</p>}
      </div>

      {/* Stats */}
      <div className="flex gap-2 px-4 py-3 border-b border-border">
        <Stat value={activeCount === null ? '—' : String(activeCount)} label="Active Access" />
        <Stat value={profile ? formatBDT(profile.total_spent_bdt) : '—'} label="মোট খরচ" />
        <Stat value={paidOrders === null ? '—' : String(paidOrders)} label="সফল Order" />
      </div>

      {/* Balance (only when the Backend wallet is on) */}
      {walletOn && profile && (
        <button
          onClick={() => navigate('/transactions')}
          className="mx-4 mt-3 w-[calc(100%-32px)] text-left bg-secondary/8 border border-secondary/25 rounded-[11px] p-3 flex items-center justify-between"
        >
          <div>
            <p className="text-[10px] text-[#6B7280] font-semibold">💳 Balance</p>
            <p className="text-[18px] font-extrabold text-[#C4B5FD]">{formatBDT(profile.wallet_balance)}</p>
          </div>
          <span className="text-[11px] text-[#A78BFA] font-medium">বিস্তারিত →</span>
        </button>
      )}

      {/* User information */}
      <div className="mx-4 mt-3 bg-card border border-border rounded-[11px] px-3 py-1">
        <InfoRow label="Telegram ID" value={profile?.telegram_id ?? (tgUser ? String(tgUser.id) : '—')} />
        <InfoRow label="ইউজারনেম" value={username ? `@${username}` : '—'} />
        <InfoRow label="যোগ দিয়েছেন" value={profile?.created_at ? formatDate(profile.created_at) : '—'} last />
      </div>

      {/* Referral */}
      {referralOn && profile && (
        <div className="mx-4 mt-3 bg-primary/6 border border-primary/20 rounded-[11px] p-3">
          <p className="text-[11px] text-[#6B7280] font-semibold mb-2">🎯 আমার Referral Code</p>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[13px] font-bold text-primary font-mono flex-1">{profile.referral_code}</span>
            <button onClick={() => void copyReferral()} className="px-[10px] py-1 rounded-[6px] border border-primary/30 bg-primary/10 text-primary text-[10px] font-semibold">Copy</button>
          </div>
          <div className="flex gap-3 text-[10px] text-[#9CA3AF]">
            <span>Refer করা: <strong className="text-white">{profile.referral_count} জন</strong></span>
            <span>Reward: <strong className="text-white">{formatBDT(profile.referral_reward_total_bdt)}</strong></span>
          </div>
        </div>
      )}

      {/* Menu */}
      <div className="px-4 mt-3">
        {MENU.map((item, i) => (
          <motion.button
            key={item.label}
            whileTap={{ scale: 0.98 }}
            onClick={item.action}
            className={cx('w-full text-left flex items-center gap-3 py-[11px] cursor-pointer', i < MENU.length - 1 && 'border-b border-border')}
          >
            <div className={`w-8 h-8 rounded-[8px] ${item.color} flex items-center justify-center text-[16px]`}>{item.icon}</div>
            <div className="flex-1">
              <p className="text-[12px] font-medium text-white">{item.label}</p>
              <p className="text-[10px] text-[#6B7280] mt-[1px]">{item.sub}</p>
            </div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="2" strokeLinecap="round"><polyline points="9 18 15 12 9 6" /></svg>
          </motion.button>
        ))}
      </div>

      {/* Settings (per-device preferences — stored on this device only) */}
      <div className="px-4 mt-4">
        <p className="text-[11px] text-[#6B7280] font-semibold uppercase tracking-[0.4px] mb-2">সেটিংস</p>
        <div className="bg-card border border-border rounded-[11px] px-3 py-1">
          <div className="flex items-center justify-between py-[10px] border-b border-border">
            <div>
              <p className="text-[12px] font-medium text-white">Haptic Feedback</p>
              <p className="text-[10px] text-[#6B7280] mt-[1px]">ট্যাপে হালকা কম্পন (এই ডিভাইসে)</p>
            </div>
            <button
              role="switch"
              aria-checked={haptic}
              aria-label="Haptic Feedback"
              onClick={toggleHaptic}
              className={cx('w-[42px] h-[24px] rounded-full border relative transition-colors flex-shrink-0', haptic ? 'bg-primary border-primary' : 'bg-surface border-border')}
            >
              <span className={cx('absolute top-[2px] w-[18px] h-[18px] rounded-full bg-white transition-all', haptic ? 'left-[21px]' : 'left-[2px]')} />
            </button>
          </div>
          <InfoRow label="Telegram সংস্করণ" value={tg?.version ?? '—'} />
          <InfoRow label="প্ল্যাটফর্ম" value={tg?.platform ?? 'Browser'} last />
        </div>
      </div>
    </PageWrapper>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex-1 min-w-0 bg-card border border-border rounded-[9px] py-[9px] text-center">
      <p className="text-[14px] font-extrabold text-primary truncate px-1">{value}</p>
      <p className="text-[9px] text-[#6B7280] mt-[2px]">{label}</p>
    </div>
  )
}

function InfoRow({ label, value, last = false }: { label: string; value: ReactNode; last?: boolean }) {
  return (
    <div className={cx('flex items-center justify-between gap-3 py-[10px]', !last && 'border-b border-border')}>
      <span className="text-[11px] text-[#6B7280]">{label}</span>
      <span className="text-[12px] text-white font-medium text-right truncate">{value}</span>
    </div>
  )
}
