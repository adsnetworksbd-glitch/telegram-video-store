import type { AccessStatus, AvailableMethods } from '@/types'

// ─── Access display logic (pure — no React, no network) ──────────────────────
// The Backend decides access. These functions only TRANSLATE its answer
// (AccessStatus + AvailableMethods) into a display state, and say WHEN it is
// worth asking the Backend again. Nothing here grants, extends or revokes
// access, and nothing here decides that an access has expired: when the clock
// says an access may have run out, the page re-asks the Backend.

export type AccessStateKey =
  | 'free'                // free video
  | 'active'              // valid temporary access (Ads Unlock / purchase with an expiry)
  | 'lifetime'            // valid access that never expires — "Already Unlocked"
  | 'expired'             // had temporary access, it ran out, nothing else is valid
  | 'ads_available'       // no access; unlockable by watching ads
  | 'purchase_available'  // no access; unlockable by buying
  | 'unlock_available'    // no access; both ads and purchase are enabled
  | 'locked'              // no access and no way to unlock it right now

export function getAccessDisplay(access: AccessStatus, methods?: AvailableMethods | null): AccessStateKey {
  if (access.granted) {
    if (access.source === 'free') return 'free'
    return access.is_lifetime ? 'lifetime' : 'active'
  }
  if (access.expired) return 'expired'
  const ads = Boolean(methods?.ads_unlock)
  const buy = Boolean(methods?.purchase)
  if (ads && buy) return 'unlock_available'
  if (ads) return 'ads_available'
  if (buy) return 'purchase_available'
  return 'locked'
}

/** setTimeout cannot take more than a signed 32-bit number of ms (≈ 24.8 days). */
export const MAX_TIMER_MS = 2 ** 31 - 1

/**
 * How long to wait before asking the Backend whether a temporary access has
 * run out. Null = nothing to schedule (no / unreadable expiry). A margin of one
 * second avoids asking a moment too early.
 */
export function msUntilAccessRecheck(expiresAt: string | null | undefined, nowMs: number): number | null {
  if (!expiresAt) return null
  const t = Date.parse(expiresAt)
  if (Number.isNaN(t)) return null
  return Math.min(Math.max(t - nowMs + 1000, 1000), MAX_TIMER_MS)
}
