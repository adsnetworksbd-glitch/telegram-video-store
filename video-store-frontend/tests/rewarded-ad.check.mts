// Run via tests/run-rewarded-ad-check.sh (replaces import.meta.env, then node --experimental-strip-types)
import assert from 'node:assert/strict'

const g = globalThis as any
g.__VITE_ENV__ = {}
let appended: any[] = []
g.window = g
g.document = {
  createElement: () => ({ dataset: {}, remove() {} }),
  head: { appendChild(el: any) { appended.push(el); setTimeout(() => el.onload?.(), 0) } },
}
const mod = await import('../src/utils/rewardedAd.ts')
let n = 0
const check = (name: string, ok: boolean | (() => void)) => { if (typeof ok === 'function') ok(); else assert.ok(ok, name); console.log('  ok ', name); n++ }

// unknown provider -> unavailable, no script injected
check('unknown provider is unavailable', (await mod.showRewardedAd({ network_id: 'x', zone_id: '1', type: 'nope' }, 's1')) === 'unavailable')
check('no script for unknown provider', appended.length === 0)
check('hasAdAdapter monetag / other', mod.hasAdAdapter('monetag') && !mod.hasAdAdapter('x') && !mod.hasAdAdapter(null))

// no zone -> unavailable
check('monetag without zone unavailable', (await mod.showRewardedAd({ network_id: 'm', zone_id: null, type: 'monetag' }, 's1')) === 'unavailable')

// non-https sdk_url is never loaded
check('http sdk_url refused', (await mod.showRewardedAd({ network_id: 'm', zone_id: 'z1', type: 'monetag', sdk_url: 'http://evil.test/a.js' }, 's1')) === 'unavailable')
check('no script appended for http url', appended.length === 0)

// https sdk_url loads, but SDK never defines show_z2 -> unavailable (never "shown")
check('https url loaded but SDK missing -> unavailable', (await mod.showRewardedAd({ network_id: 'm', zone_id: 'z2', type: 'monetag', sdk_url: 'https://sdk.example/a.js' }, 's1')) === 'unavailable')
check('script appended for https url', appended.length === 1)

// SDK present: forwards session id, reports 'shown' only (not verified)
let got: any
g.show_z3 = async (o: any) => { got = o }
let started = false
check('present SDK -> shown', (await mod.showRewardedAd({ network_id: 'm', zone_id: 'z3', type: 'monetag' }, 'sess-9', () => { started = true })) === 'shown')
check('ymid = session id + unique nonce', /^sess-9\.[0-9a-f]{12}$/.test(got?.ymid))
const y1 = mod.makeYmid('s'), y2 = mod.makeYmid('s')
check('ymid unique per ad event', y1 !== y2)
check('onStart called', started)

// SDK rejects -> failed
g.show_z4 = async () => { throw new Error('x') }
check('SDK rejection -> failed', (await mod.showRewardedAd({ network_id: 'm', zone_id: 'z4', type: 'monetag' }, 's')) === 'failed')

// provider_id takes precedence over type
g.show_z5 = async () => {}
check('provider_id used', (await mod.showRewardedAd({ network_id: 'm', zone_id: 'z5', type: 'whatever', provider_id: 'monetag' }, 's')) === 'shown')

console.log(`\n${n} checks passed`)
