import type { AccessStatus, AccessSource, AvailableMethods } from '@/types'
import { formatTimeLeft, formatDate, cx } from '@/utils'
import { getAccessDisplay, type AccessStateKey } from './accessDisplay'

// ─── Access states ────────────────────────────────────────────────────────────
// The Backend decides access (AccessStatus). This file only TRANSLATES that
// response into display states (see accessDisplay.ts). Nothing here grants or
// revokes access.

export type { AccessStateKey }

type Tone = 'green' | 'blue' | 'purple' | 'orange' | 'red' | 'gray'

interface StateMeta { title: string; description: string; tone: Tone; icon: string }

const META: Record<AccessStateKey, StateMeta> = {
  free:               { title: 'Free',                         description: 'এই ভিডিওটি সবার জন্য বিনামূল্যে।',                    tone: 'green',  icon: '🎁' },
  active:             { title: 'Active Access',                description: 'আপনার Access এখন সক্রিয়।',                            tone: 'green',  icon: '✅' },
  lifetime:           { title: 'Already Unlocked',             description: 'Lifetime Access — কোনো মেয়াদ নেই, আবার কিনতে হবে না।', tone: 'blue',   icon: '♾' },
  expired:            { title: 'Expired Access',               description: 'আগের Access-এর মেয়াদ শেষ হয়েছে।',                     tone: 'red',    icon: '⌛' },
  ads_available:      { title: 'Ads Unlock Available',         description: 'বিজ্ঞাপন দেখে বিনামূল্যে Unlock করতে পারবেন।',          tone: 'blue',   icon: '📺' },
  purchase_available: { title: 'Purchase Available',           description: 'কিনে Access পেতে পারবেন।',                              tone: 'purple', icon: '🛒' },
  unlock_available:   { title: 'Ads Unlock / Purchase Available', description: 'বিজ্ঞাপন দেখে অথবা কিনে Access পেতে পারবেন।',        tone: 'blue',   icon: '🔓' },
  locked:             { title: 'Locked',                       description: 'এই মুহূর্তে Unlock করার কোনো উপায় চালু নেই।',           tone: 'gray',   icon: '🔒' },
}

const SOURCE_LABEL: Record<AccessSource, string> = {
  free: 'Free',
  ads_unlock: 'Ads Unlock',
  individual_purchase: 'Individual Purchase',
  package_purchase: 'Package Purchase',
  admin_grant: 'Admin Access',
}

export function accessSourceLabel(source: AccessSource | null | undefined): string {
  return source ? SOURCE_LABEL[source] ?? 'Access' : ''
}

/** Map a Backend AccessStatus (+ the admin-enabled unlock methods) to one display state. */
export function getAccessState(access: AccessStatus, methods?: AvailableMethods | null): AccessStateKey {
  return getAccessDisplay(access, methods)
}

const TONE: Record<Tone, string> = {
  green:  'bg-success/8 border-success/25 text-[#6EE7B7]',
  blue:   'bg-primary/10 border-primary/25 text-[#93C5FD]',
  purple: 'bg-secondary/10 border-secondary/30 text-[#C4B5FD]',
  orange: 'bg-warning/8 border-warning/20 text-[#FCD34D]',
  red:    'bg-danger/8 border-danger/20 text-[#FCA5A5]',
  gray:   'bg-card border-border text-[#9CA3AF]',
}

// ─── Source badge (Ads Unlock / Individual / Package …) ──────────────────────
export function AccessSourceBadge({ source, className = '' }: { source: AccessSource | null | undefined; className?: string }) {
  if (!source) return null
  const tone: Tone = source === 'ads_unlock' ? 'blue' : source === 'free' ? 'green' : source === 'admin_grant' ? 'gray' : 'purple'
  return (
    <span className={cx('inline-flex items-center text-[9px] font-bold px-[7px] py-[3px] rounded-[5px] border', TONE[tone], className)}>
      {accessSourceLabel(source)}
    </span>
  )
}

// ─── Validity badge (Lifetime / time left / Expired) ─────────────────────────
export function AccessValidityBadge({ access, className = '' }: { access: AccessStatus; className?: string }) {
  const state = getAccessState(access)
  if (state === 'free' || !(access.granted || state === 'expired')) return null
  let text: string
  let tone: Tone
  if (state === 'expired') { text = '✗ Expired'; tone = 'red' }
  else if (access.is_lifetime) { text = '♾ Lifetime'; tone = 'blue' }
  else if (access.expires_at) { text = `⏰ ${formatTimeLeft(access.expires_at)}`; tone = 'green' }
  else return null
  return (
    <span className={cx('inline-flex items-center text-[9px] font-bold px-[7px] py-[3px] rounded-[5px] border', TONE[tone], className)}>
      {text}
    </span>
  )
}

// ─── Access state card ────────────────────────────────────────────────────────
// `methods` (optional) lets the card say whether Ads Unlock / Purchase is
// available when there is no access. Several valid sources are shown as
// separate badges — each is its own record on the Backend.
export function AccessStateCard({ access, methods, className = '' }: { access: AccessStatus; methods?: AvailableMethods | null; className?: string }) {
  const state = getAccessState(access, methods)
  const meta = META[state]
  const sources: AccessSource[] = access.granted && state !== 'free'
    ? (access.active_sources && access.active_sources.length > 0 ? access.active_sources : access.source ? [access.source] : [])
    : []
  return (
    <div className={cx('flex items-start gap-3 border rounded-[12px] px-3 py-[11px]', TONE[meta.tone], className)}>
      <span className="text-[20px] leading-none mt-[1px]" aria-hidden>{meta.icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[13px] font-bold">{meta.title}</span>
          {sources.map((src) => <AccessSourceBadge key={src} source={src} />)}
        </div>
        <p className="text-[11px] opacity-80 mt-[2px] leading-[1.5]">{meta.description}</p>
        {access.granted && !access.is_lifetime && access.expires_at && (
          <p className="text-[11px] mt-1 font-medium">
            {formatTimeLeft(access.expires_at)} · {formatDate(access.expires_at)} পর্যন্ত
          </p>
        )}
        {sources.length > 1 && (
          <p className="text-[10px] opacity-70 mt-1">একাধিক Access সক্রিয় — প্রতিটি আলাদা রেকর্ড।</p>
        )}
      </div>
    </div>
  )
}
