import type { SourceType } from '@/types'

// ─── Source type support matrix ───────────────────────────────────────────────
// What a Telegram Mini App can *reliably* do per source type:
//  • supported   — opens the way users expect
//  • partial     — opens, but depends on the user's browser / app
//  • unverified  — cannot be guaranteed; shown with a clear warning
// Nothing here is access control: the link only exists after the Backend has
// re-checked access (GET /access/video/:id/source).

export type SourceSupport = 'supported' | 'partial' | 'unverified'

export interface SourceInfo {
  label: string
  icon: string
  support: SourceSupport
  /** Short note shown next to the Open button. */
  note: string
}

export const SOURCE_INFO: Record<SourceType, SourceInfo> = {
  telegram_bot:     { label: 'Telegram Bot',     icon: '✈️', support: 'supported',  note: 'Telegram-এ খুলবে — ভিডিও Bot/Chat-এ আসবে।' },
  telegram_channel: { label: 'Telegram Channel', icon: '✈️', support: 'supported',  note: 'Telegram Channel/Post-এ খুলবে।' },
  google_drive:     { label: 'Google Drive',     icon: '🟢', support: 'partial',    note: 'ব্রাউজার বা Drive অ্যাপে খুলবে। Download সেখান থেকে।' },
  dropbox:          { label: 'Dropbox',          icon: '🔷', support: 'partial',    note: 'ব্রাউজার বা Dropbox অ্যাপে খুলবে। Download সেখান থেকে।' },
  direct_mp4:       { label: 'Direct MP4',       icon: '🎞', support: 'partial',    note: 'ব্রাউজারে খুলবে। Telegram-এর ভেতরে সরাসরি Download নিশ্চিত নয় — ব্রাউজার থেকে সেভ করুন।' },
  custom_url:       { label: 'Custom Link',      icon: '🔗', support: 'unverified', note: 'এই লিংক নির্ভরযোগ্যভাবে সমর্থিত নয়; খুলবে কিনা নিশ্চিত নয়।' },
}

export function getSourceInfo(type: string | null | undefined): SourceInfo | null {
  return type && type in SOURCE_INFO ? SOURCE_INFO[type as SourceType] : null
}

// Only https links (and Telegram deep links) are ever opened — a `javascript:`
// or `data:` URL from a mis-configured record must not reach window.open.
function safeUrl(raw: string): URL | null {
  try {
    const u = new URL(raw)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u : null
  } catch {
    return null
  }
}

const isTelegramHost = (u: URL) => u.hostname === 't.me' || u.hostname === 'telegram.me'

/**
 * Opens a source link with the handler that suits its type.
 * Returns false when the link was rejected (unsafe / malformed) so the caller
 * can tell the user instead of failing silently.
 */
export function handleSourceRedirect(sourceType: SourceType, rawUrl: string): boolean {
  const url = safeUrl(rawUrl)
  if (!url) return false
  const tg = window.Telegram?.WebApp
  const href = url.toString()

  const openExternal = () => {
    // Inside Telegram, openLink hands the page to the system browser, which is
    // the only route that works for Drive / Dropbox / MP4 on every platform.
    if (tg?.initData && typeof tg.openLink === 'function') tg.openLink(href)
    else window.open(href, '_blank', 'noopener,noreferrer')
  }

  switch (sourceType) {
    case 'telegram_bot':
    case 'telegram_channel':
      if (isTelegramHost(url) && tg?.initData && typeof tg.openTelegramLink === 'function') {
        tg.openTelegramLink(href)
      } else {
        openExternal()
      }
      return true
    case 'google_drive':
    case 'dropbox':
    case 'direct_mp4':
    case 'custom_url':
    default:
      openExternal()
      return true
  }
}
