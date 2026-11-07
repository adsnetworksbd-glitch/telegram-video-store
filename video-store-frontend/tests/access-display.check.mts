/**
 * Phase 8 Part 2 (B-1) — behaviour check for the access DISPLAY logic.
 *
 * Run:   npx tsx tests/access-display.check.mts      (or: node tests/access-display.check.mts)
 *
 * Executes the REAL src/components/access/accessDisplay.ts (pure: no React, no
 * network). It checks how a Backend answer is translated into a display state and
 * when a re-check is scheduled. It does NOT render React, does NOT run the
 * useAccessRevalidation / useOpenSource hooks and does NOT call a Backend.
 */
import assert from 'node:assert/strict'
import { getAccessDisplay, msUntilAccessRecheck, MAX_TIMER_MS } from '../src/components/access/accessDisplay.ts'

type S = 'free' | 'ads_unlock' | 'individual_purchase' | 'package_purchase' | 'admin_grant' | null
const acc = (o: Partial<{ granted: boolean; source: S; expires_at: string | null; is_lifetime: boolean; expired: boolean }>) =>
  ({ granted: false, source: null as S, expires_at: null, is_lifetime: false, ...o })
const M = (ads: boolean, purchase: boolean, is_free = false) => ({ ads_unlock: ads, purchase, is_free })

let n = 0
const t = (name: string, fn: () => void) => { fn(); n++; console.log(`  ok  ${name}`) }

// ── the seven required states ────────────────────────────────────────────────
t('Locked: no access, no unlock method enabled', () =>
  assert.equal(getAccessDisplay(acc({}), M(false, false)), 'locked'))
t('Locked: no methods info at all (older callers)', () =>
  assert.equal(getAccessDisplay(acc({})), 'locked'))
t('Free', () =>
  assert.equal(getAccessDisplay(acc({ granted: true, source: 'free', is_lifetime: true }), M(false, false, true)), 'free'))
t('Ads Unlock Available', () =>
  assert.equal(getAccessDisplay(acc({}), M(true, false)), 'ads_available'))
t('Purchase Available', () =>
  assert.equal(getAccessDisplay(acc({}), M(false, true)), 'purchase_available'))
t('Ads + Purchase both enabled', () =>
  assert.equal(getAccessDisplay(acc({}), M(true, true)), 'unlock_available'))
t('Already Unlocked (lifetime purchase)', () =>
  assert.equal(getAccessDisplay(acc({ granted: true, source: 'individual_purchase', is_lifetime: true }), M(true, true)), 'lifetime'))
t('Already Unlocked (lifetime package)', () =>
  assert.equal(getAccessDisplay(acc({ granted: true, source: 'package_purchase', is_lifetime: true })), 'lifetime'))
t('Active Access (ads unlock with expiry)', () =>
  assert.equal(getAccessDisplay(acc({ granted: true, source: 'ads_unlock', expires_at: '2030-01-01T00:00:00Z' }), M(true, true)), 'active'))
t('Active Access (custom-duration purchase)', () =>
  assert.equal(getAccessDisplay(acc({ granted: true, source: 'individual_purchase', expires_at: '2030-01-01T00:00:00Z' })), 'active'))
t('Expired Access (even though unlock methods are enabled)', () =>
  assert.equal(getAccessDisplay(acc({ expired: true }), M(true, true)), 'expired'))

// ── the Backend answer always wins ───────────────────────────────────────────
t('granted:true is never shown as locked/expired, whatever the methods say', () => {
  for (const m of [M(false, false), M(true, true), undefined])
    assert.ok(['free', 'lifetime', 'active'].includes(getAccessDisplay(acc({ granted: true, source: 'ads_unlock', expires_at: 'x' }), m)))
})
t('granted:true wins even if a stray expired:true is present', () =>
  assert.equal(getAccessDisplay(acc({ granted: true, expired: true, source: 'ads_unlock', expires_at: '2030-01-01T00:00:00Z' }), M(true, true)), 'active'))
t('granted:false + expired:true is never shown as unlocked', () => {
  for (const m of [M(false, false), M(true, true), undefined])
    assert.equal(getAccessDisplay(acc({ expired: true, source: 'ads_unlock', is_lifetime: true }), m), 'expired')
})
t('granted:false is never "active"/"lifetime"/"free" even if other fields look valid', () => {
  const x = getAccessDisplay(acc({ granted: false, source: 'free', is_lifetime: true, expires_at: '2099-01-01T00:00:00Z' }), M(false, false))
  assert.equal(x, 'locked')
})
t('admin_grant with expiry is Active; lifetime admin_grant is Already Unlocked', () => {
  assert.equal(getAccessDisplay(acc({ granted: true, source: 'admin_grant', expires_at: '2030-01-01T00:00:00Z' })), 'active')
  assert.equal(getAccessDisplay(acc({ granted: true, source: 'admin_grant', is_lifetime: true })), 'lifetime')
})

// ── re-check scheduling ──────────────────────────────────────────────────────
const NOW = Date.parse('2026-11-05T12:00:00Z')
t('recheck: nothing to schedule without a usable expiry', () => {
  for (const v of [null, undefined, '', 'not-a-date']) assert.equal(msUntilAccessRecheck(v as string, NOW), null)
})
t('recheck: fires 1s after expiry', () =>
  assert.equal(msUntilAccessRecheck('2026-11-05T12:00:10Z', NOW), 11_000))
t('recheck: already-past expiry → 1s (never 0 / negative → no tight loop)', () => {
  assert.equal(msUntilAccessRecheck('2026-11-05T11:00:00Z', NOW), 1000)
  assert.equal(msUntilAccessRecheck('2026-11-05T12:00:00Z', NOW), 1000)
})
t('recheck: far-future expiry is capped below the 32-bit setTimeout limit', () => {
  const w = msUntilAccessRecheck('2099-01-01T00:00:00Z', NOW)!
  assert.equal(w, MAX_TIMER_MS)
  assert.ok(w <= 2 ** 31 - 1)
})
t('recheck: 24h access is scheduled, not capped', () =>
  assert.equal(msUntilAccessRecheck('2026-11-06T12:00:00Z', NOW), 86_400_000 + 1000))

console.log(`\n${n} checks passed`)
