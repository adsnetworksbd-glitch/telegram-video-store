import type { AdNetworkConfig } from '@/types'

// ─── Rewarded ad adapters (one per provider) ──────────────────────────────────
// This module only SHOWS an ad. It never decides that an ad was "verified":
// access is granted solely by the Backend after the ad network's server-to-
// server callback, and the UI learns about it by polling the session.
// No secret key ever lives here: only the public zone id and (optional) https
// SDK url that the Backend returns in `network_config`.
//
// To add a network: write an adapter below and register it in ADAPTERS
// (the matching Backend module goes in app/services/ad_providers/).
//
// Monetag (docs.monetag.com): `show_<zone>({ ymid })` returns a Promise that ALSO
// resolves when the user closes the ad early, so it is never proof of anything.
// `ymid` must be unique per ad event and is echoed in Monetag's server postback;
// we send "<session_id>.<nonce>" so the Backend can bind the ad to the session
// and count each ad event exactly once. Only the postback (Backend) counts.
// Not verified on a live Monetag zone from this build environment.

export type RewardedAdOutcome =
  | 'shown'        // SDK reports the ad flow finished (NOT proof of verification)
  | 'unavailable'  // SDK missing / unsupported network type
  | 'failed'       // SDK present but the ad could not be shown

export interface AdAdapter {
  /** Show one rewarded ad for this session. Must never claim verification. */
  show(network: AdNetworkConfig, sessionId: string, onStart?: () => void): Promise<RewardedAdOutcome>
}

const ENV_SDK_URL = import.meta.env.VITE_AD_SDK_URL

function safeSdkUrl(network: AdNetworkConfig): string | undefined {
  const url = network.sdk_url || ENV_SDK_URL
  return typeof url === 'string' && url.startsWith('https://') ? url : undefined
}

// ─── Monetag ──────────────────────────────────────────────────────────────────
type ShowFn = (opts?: { ymid?: string }) => Promise<unknown>
const loading = new Map<string, Promise<boolean>>()

function getShowFn(zone: string): ShowFn | undefined {
  const fn = (window as unknown as Record<string, unknown>)[`show_${zone}`]
  return typeof fn === 'function' ? (fn as ShowFn) : undefined
}

function ensureSdk(zone: string, sdkUrl: string | undefined): Promise<boolean> {
  if (getShowFn(zone)) return Promise.resolve(true)
  if (!sdkUrl) return Promise.resolve(false)
  let p = loading.get(zone)
  if (!p) {
    p = new Promise<boolean>((resolve) => {
      const s = document.createElement('script')
      s.src = sdkUrl
      s.async = true
      s.dataset.zone = zone
      s.dataset.sdk = `show_${zone}`
      s.onload = () => resolve(Boolean(getShowFn(zone)))
      s.onerror = () => { s.remove(); resolve(false) }
      document.head.appendChild(s)
    }).finally(() => { loading.delete(zone) })
    loading.set(zone, p)
  }
  return p
}

/** Unique per ad event: "<session_id>.<nonce>" (nonce is not a secret, just distinct). */
export function makeYmid(sessionId: string): string {
  let nonce = ''
  try {
    const a = new Uint8Array(6)
    crypto.getRandomValues(a)
    nonce = Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('')
  } catch {
    nonce = Math.random().toString(16).slice(2, 14).padEnd(12, '0')
  }
  return `${sessionId}.${nonce}`
}

const monetag: AdAdapter = {
  async show(network, sessionId, onStart) {
    if (!network.zone_id) return 'unavailable'
    if (!(await ensureSdk(network.zone_id, safeSdkUrl(network)))) return 'unavailable'
    const show = getShowFn(network.zone_id)
    if (!show) return 'unavailable'
    try {
      onStart?.()
      await show({ ymid: makeYmid(sessionId) })
      return 'shown'
    } catch {
      return 'failed'
    }
  },
}

const ADAPTERS: Record<string, AdAdapter> = { monetag }

export function hasAdAdapter(type: string | undefined | null): boolean {
  return Boolean(type && ADAPTERS[type])
}

export async function showRewardedAd(
  network: AdNetworkConfig,
  sessionId: string,
  onStart?: () => void,
): Promise<RewardedAdOutcome> {
  const adapter = ADAPTERS[network.provider_id || network.type]
  if (!adapter) return 'unavailable'
  return adapter.show(network, sessionId, onStart)
}
