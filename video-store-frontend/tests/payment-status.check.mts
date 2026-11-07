// Run via tests/run-payment-status-check.sh (node --experimental-strip-types). Offline, no React.
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const stage = await import('../src/utils/orderStage.ts')
const ps = await import('../src/utils/paymentStatus.ts')

let n = 0
const check = (name: string, ok: unknown) => { assert.ok(ok, name); console.log('  ok ', name); n++ }
const eq = (name: string, a: unknown, b: unknown) => { assert.deepEqual(a, b, name); console.log('  ok ', name); n++ }

// ── Order status → screen (the Backend status decides; success only for `completed`) ──
const st = (status: string) => stage.stageOf({ status } as any)
eq('completed → success', st('completed'), 'success')
for (const s of ['failed', 'expired', 'refunded']) eq(`${s} → failed screen`, st(s), 'failed')
for (const s of ['under_review', 'payment_submitted']) eq(`${s} → pending screen`, st(s), 'pending')
for (const s of ['awaiting_payment', 'pending', 'weird_new_status']) eq(`${s} → pay screen`, st(s), 'pay')
check('only `completed` can reach success', ['pending', 'awaiting_payment', 'payment_submitted', 'under_review', 'failed', 'expired', 'refunded', 'x'].every((s) => st(s) !== 'success'))
eq('paths', [stage.stagePath('o1', 'pay'), stage.stagePath('o1', 'pending'), stage.stagePath('o1', 'failed')], ['/payment/o1', '/payment/o1/pending', '/payment/o1/failed'])
eq('content path', [stage.contentPath({ content_type: 'video', content_id: 'v' }), stage.contentPath({ content_type: 'package', content_id: 'p' })], ['/videos/v', '/packages/p'])
check('deadline', stage.isPastDeadline({ expires_at: '2026-01-01T00:00:00Z' }, Date.parse('2026-01-01T00:00:01Z')) && !stage.isPastDeadline({ expires_at: '2026-01-01T00:00:10Z' }, Date.parse('2026-01-01T00:00:01Z')))

// ── Manual-review reasons ──
for (const c of ['amount_mismatch', 'reference_mismatch', 'manual_mode', 'late_payment', 'user_submitted', 'other', null, undefined, 'brand_new_code']) {
  const r = ps.reviewCopy(c as any)
  check(`reviewCopy(${c}) has copy`, r.title.length > 0 && r.body.length > 0)
}
check('mismatch copy says no access yet', ps.reviewCopy('amount_mismatch').body.includes('Access চালু হবে না'))
check('distinct copy per reason', new Set(['amount_mismatch', 'reference_mismatch', 'manual_mode', 'late_payment'].map((c) => ps.reviewCopy(c).title)).size === 4)

// ── Verify answers: only Backend wording is shown; kinds map as expected ──
eq('fulfilled → success', ps.verifyNote({ outcome: 'fulfilled', message: 'm' }).kind, 'success')
eq('failed → error', ps.verifyNote({ outcome: 'failed', message: 'm' }).kind, 'error')
for (const o of ['wait', 'review', 'manual', 'noop', 'new']) eq(`${o} → info`, ps.verifyNote({ outcome: o, message: 'm' }).kind, 'info')
eq('message passes through unchanged', ps.verifyNote({ outcome: 'wait', message: 'Backend text' }).text, 'Backend text')

// ── Throttle cooldown parsing ──
eq('429 text', ps.cooldownFromMessage('3 সেকেন্ড পর আবার চেষ্টা করুন।'), 3)
eq('no number → fallback', ps.cooldownFromMessage('too fast', 7), 7)
eq('clamped high', ps.cooldownFromMessage('99999 সেকেন্ড'), 120)
eq('zero → at least 1', ps.cooldownFromMessage('0 সেকেন্ড', 5), 5)
eq('undefined', ps.cooldownFromMessage(undefined), 5)

// ── Hash rules per network (mirror of the Backend) ──
const H = 'ab'.repeat(32)
eq('trc20 ok', ps.hashProblem('usdt_trc20', H), null)
check('trc20 rejects 0x', ps.hashProblem('usdt_trc20', '0x' + H) !== null)
eq('bep20 adds 0x', ps.hashProblem('usdt_bep20', H), null)
eq('erc20 ok with 0x + uppercase', ps.hashProblem('usdt_erc20', '0x' + H.toUpperCase()), null)
check('erc20 rejects short', ps.hashProblem('usdt_erc20', '12345678') !== null)
eq('binance_id free reference', ps.hashProblem('binance_id', 'ORDER12345'), null)
eq('binance_pay fallback id', ps.hashProblem('binance_pay', 'ABCD1234'), null)
check('too short free ref rejected', ps.hashProblem('binance_id', 'abc') !== null)
check('admin custom type free ref', ps.hashProblem('bkash_usd', 'TX-not-allowed-dash') !== null && ps.hashProblem('bkash_usd', 'TX12345678') === null)
eq('empty is not a problem (button stays disabled elsewhere)', ps.hashProblem('usdt_trc20', '  '), null)
eq('same hash one spelling', ps.normalizeHash('usdt_bep20', H.toUpperCase()), ps.normalizeHash('usdt_bep20', '0x' + H))

// ── Labels ──
check('timeline labels', ps.stepLabel('verified') !== ps.stepLabel('rejected') && ps.stepLabel('???').length > 0)

// ── Source contract: nothing business-specific or secret in the frontend ──
const walk = (d: string): string[] => readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : [p] })
const files = walk('src').filter((f) => /\.(ts|tsx)$/.test(f))
const all = files.map((f) => [f, readFileSync(f, 'utf8')] as const)
for (const [f, src] of all) {
  assert.ok(!/\bT[1-9A-HJ-NP-Za-km-z]{33}\b/.test(src), `${f}: TRON-looking address hardcoded`)
  assert.ok(!/\b0x[0-9a-fA-F]{40}\b/.test(src), `${f}: EVM-looking address hardcoded`)
  assert.ok(!/BINANCE_PAY_API|api_?secret|API_SECRET|sk_live/i.test(src), `${f}: secret-looking name`)
}
check('no wallet addresses or API secrets in src/', true)

const get = (p: string) => readFileSync(p, 'utf8')
const apiSrc = get('src/api/index.ts'), pay = get('src/pages/Payment/index.tsx'), pend = get('src/pages/PaymentPending/index.tsx'), fail = get('src/pages/PaymentFailed/index.tsx')
check('API: verify + retry are POSTs to the Backend', /verify: \(id: string\) =>\s*api\.post<PaymentVerifyResult>\(`\/orders\/\$\{encodeURIComponent\(id\)\}\/verify`/.test(apiSrc) && /retry: \(id: string[^)]*\) =>\s*api\.post<OrderCreateResult>\(`\/orders\/\$\{encodeURIComponent\(id\)\}\/retry`/.test(apiSrc))
check('no page sets an order/payment to completed itself', [pay, pend, fail].every((s) => !/status:\s*['"]completed['"]|setOrder\(\{|setPayment\(\{/.test(s)))
check('Payment page: Binance check goes through the verify hook', pay.includes('useVerifyPayment') && !/ordersApi\.verify/.test(pay))
check('Pending page re-checks Binance only while waiting (not during admin review)', pend.includes('useAutoVerify(isBinanceOrder && waiting'))
check('Failed page retries through the Backend /retry', fail.includes('ordersApi.retry(') && fail.includes('retryBusy'))
check('Payment page shows admin instructions as plain text', !/dangerouslySetInnerHTML/.test(pay + pend + fail))
check('Payment amounts come from the order, not constants', pay.includes('order.final_usdt') && !/\b115\b/.test(pay))
console.log(`\n${n} checks passed`)
