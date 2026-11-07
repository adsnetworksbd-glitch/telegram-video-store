/**
 * Phase 8 Part 2A — behaviour check for src/api (client interceptors, response
 * guards) and hooks/useAppConfig.
 *
 * Run:   sh tests/run-api-client-check.sh
 *
 * It executes the REAL src/api/client.ts, src/api/index.ts, src/store/index.ts
 * and src/hooks/useAppConfig.ts. Only the transport is faked: axios' `adapter`
 * is replaced, so no network is used. Telegram's `window.Telegram` is faked.
 * It does NOT render React and does NOT talk to the real Backend / Firestore.
 */
import assert from 'node:assert/strict'
import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'

;(globalThis as any).window = globalThis
const G = globalThis as any
G.__VITE_ENV__ = { VITE_API_URL: 'https://api.test.local/api/v1', DEV: false }

const { apiClient, connectionMessage, getErrorStatus, INVALID_RESPONSE_MESSAGE } = await import('../src/api/client.ts')
const { authApi, videosApi, categoriesApi, configApi, userApi } = await import('../src/api/index.ts')
const { useAuthStore, useUserStore, useConfigStore } = await import('../src/store/index.ts')
const { refreshAppConfig } = await import('../src/hooks/useAppConfig.ts')

// ── fake transport ───────────────────────────────────────────────────────────
type Reply = { status: number; data?: unknown } | 'network' | 'timeout'
let script: Array<(cfg: InternalAxiosRequestConfig) => Reply> = []
const calls: Array<{ method: string; url: string; auth?: string }> = []

function adapter(config: InternalAxiosRequestConfig) {
  calls.push({
    method: String(config.method),
    url: String(config.url),
    auth: (config.headers as unknown as Record<string, string>)?.Authorization,
  })
  const next = script.shift()
  if (!next) throw new Error(`unscripted request: ${config.method} ${config.url}`)
  const r = next(config)
  if (r === 'network') return Promise.reject(new AxiosError('Network Error', 'ERR_NETWORK', config))
  if (r === 'timeout') return Promise.reject(new AxiosError('timeout', 'ECONNABORTED', config))
  const response = { status: r.status, data: r.data, headers: {}, config, statusText: '' }
  if (r.status >= 200 && r.status < 300) return Promise.resolve(response)
  return Promise.reject(new AxiosError('bad', 'ERR_BAD_RESPONSE', config, null, response as never))
}
apiClient.defaults.adapter = adapter as never
axios.defaults.adapter = adapter as never

const setTelegram = (initData: string | null) => { G.Telegram = initData === null ? undefined : { WebApp: { initData } } }
function login(token = 'old-token') {
  useAuthStore.getState().setToken(token)
  useUserStore.getState().setProfile({ telegram_id: '1', first_name: 'A' } as never)
}
function reset() { script = []; calls.length = 0 }
async function rejected(p: Promise<unknown>): Promise<any> {
  try { await p } catch (e) { return e }
  assert.fail('expected the call to be rejected')
}

let n = 0
async function check(name: string, fn: () => Promise<void> | void) {
  reset(); await fn(); n++; console.log('ok  ', name)
}

// ── invalid responses ────────────────────────────────────────────────────────
await check('2xx with an HTML/text body is rejected as "invalid" (not handed to a page)', async () => {
  login(); setTelegram('init')
  script = [() => ({ status: 200, data: '<html>captive portal</html>' })]
  const e = await rejected(apiClient.get('/videos'))
  assert.equal(e.kind, 'invalid'); assert.equal(e.message, INVALID_RESPONSE_MESSAGE)
  assert.equal(connectionMessage(e), INVALID_RESPONSE_MESSAGE)
})
await check('2xx with an empty body is rejected as "invalid"', async () => {
  script = [() => ({ status: 200, data: '' })]
  assert.equal((await rejected(apiClient.get('/videos'))).kind, 'invalid')
})
await check('guard: /videos page without `items` is rejected; a valid page passes', async () => {
  script = [() => ({ status: 200, data: { total: 0 } })]
  assert.equal((await rejected(videosApi.list())).kind, 'invalid')
  script = [() => ({ status: 200, data: { items: [], total: 0, page: 1, has_more: false } })]
  assert.deepEqual((await videosApi.list()).data.items, [])
})
await check('guard: video detail needs id + access + available_methods', async () => {
  script = [() => ({ status: 200, data: { id: 'v1', title: 'x' } })]
  assert.equal((await rejected(videosApi.detail('v1'))).kind, 'invalid')
  script = [() => ({ status: 200, data: { id: 'v1', access: { granted: false }, available_methods: { purchase: true } } })]
  assert.equal((await videosApi.detail('v1')).data.id, 'v1')
})
await check('guard: categories / homepage / notifications / search shapes', async () => {
  script = [() => ({ status: 200, data: { cats: [] } })]
  assert.equal((await rejected(categoriesApi.list())).kind, 'invalid')
  script = [() => ({ status: 200, data: { sections: 'nope' } })]
  assert.equal((await rejected(configApi.getHomepageConfig())).kind, 'invalid')
  script = [() => ({ status: 200, data: { notifications: [] } })]            // unread_count missing
  assert.equal((await rejected(userApi.notifications())).kind, 'invalid')
  script = [() => ({ status: 200, data: { notifications: [], unread_count: 2 } })]
  assert.equal((await userApi.notifications()).data.unread_count, 2)
})
await check('guard: login response without a token never reaches the auth store', async () => {
  useAuthStore.getState().clearAuth()
  script = [() => ({ status: 200, data: { user: { telegram_id: '1' } } })]
  assert.equal((await rejected(authApi.login('init'))).kind, 'invalid')
  assert.equal(useAuthStore.getState().isAuthenticated, false)
})
await check('ids are URL-encoded in detail paths', async () => {
  script = [() => ({ status: 200, data: { id: 'a', access: {}, available_methods: {} } })]
  await videosApi.detail('a/b?c')
  assert.equal(calls[0].url, '/videos/a%2Fb%3Fc')
})

// ── HTTP / network errors ────────────────────────────────────────────────────
await check('404 keeps its status; message comes from `detail`', async () => {
  script = [() => ({ status: 404, data: { detail: 'Video not found' } })]
  const e = await rejected(apiClient.get('/videos/x'))
  assert.deepEqual([getErrorStatus(e), e.kind, e.message], [404, 'http', 'Video not found'])
  assert.equal(connectionMessage(e), null)          // ordinary server answers keep the page's own wording
})
await check('POST network failure is NOT retried and is reported as "network"', async () => {
  script = [() => 'network']
  const e = await rejected(apiClient.post('/orders', {}))
  assert.equal(calls.length, 1); assert.equal(e.kind, 'network')
  assert.ok(connectionMessage(e))
})
await check('GET transient failure is retried twice, then reported (bounded — no endless loading)', async () => {
  script = [() => 'network', () => 'timeout', () => 'network']
  const t0 = Date.now()
  const e = await rejected(apiClient.get('/videos'))
  assert.equal(calls.length, 3); assert.equal(e.kind, 'network')
  assert.ok(Date.now() - t0 < 8000)
})
await check('GET recovers when a retry succeeds', async () => {
  script = [() => 'network', () => ({ status: 200, data: { ok: 1 } })]
  assert.deepEqual((await apiClient.get('/videos')).data, { ok: 1 })
  assert.equal(calls.length, 2)
})

// ── session expiry ───────────────────────────────────────────────────────────
await check('401 → refresh OK → request is retried with the NEW token', async () => {
  login('old-token'); setTelegram('init-data')
  script = [
    () => ({ status: 401, data: { detail: 'Invalid or expired token' } }),
    () => ({ status: 200, data: { access_token: 'new-token' } }),
    () => ({ status: 200, data: { items: [] } }),
  ]
  const r = await apiClient.get('/entitlements')
  assert.deepEqual(r.data, { items: [] })
  assert.deepEqual(calls.map((c) => c.url), ['/entitlements', 'https://api.test.local/api/v1/auth/refresh', '/entitlements'])
  assert.equal(calls[2].auth, 'Bearer new-token')
  assert.equal(useAuthStore.getState().token, 'new-token')
})
await check('401 + concurrent calls share ONE refresh (single-flight)', async () => {
  login('old-token'); setTelegram('init-data')
  let refreshes = 0
  script = [
    () => ({ status: 401 }), () => ({ status: 401 }),
    () => { refreshes++; return { status: 200, data: { access_token: 't2' } } },
    () => ({ status: 200, data: { a: 1 } }), () => ({ status: 200, data: { b: 1 } }),
  ]
  await Promise.all([apiClient.get('/a'), apiClient.get('/b')])
  assert.equal(refreshes, 1)
})
await check('401 + refresh fails because the connection is down → session KEPT, "network" error', async () => {
  login('old-token'); setTelegram('init-data')
  script = [() => ({ status: 401 }), () => 'network']
  const e = await rejected(apiClient.get('/entitlements'))
  assert.equal(e.kind, 'network')
  assert.equal(useAuthStore.getState().isAuthenticated, true)
  assert.equal(useAuthStore.getState().token, 'old-token')
  assert.ok(useUserStore.getState().profile)
})
await check('401 + refresh answered 5xx → session KEPT', async () => {
  login('old-token'); setTelegram('init-data')
  script = [() => ({ status: 401 }), () => ({ status: 503 })]
  assert.equal((await rejected(apiClient.get('/x'))).kind, 'network')
  assert.equal(useAuthStore.getState().isAuthenticated, true)
})
await check('401 + refresh REJECTED (401) → session ended, private data cleared', async () => {
  login('old-token'); setTelegram('init-data')
  script = [() => ({ status: 401 }), () => ({ status: 401, data: { detail: 'Authentication failed' } })]
  const e = await rejected(apiClient.get('/entitlements'))
  assert.equal(e.kind, 'session')
  const a = useAuthStore.getState()
  assert.deepEqual([a.token, a.isAuthenticated], [null, false]); assert.ok(a.error)
  assert.equal(useUserStore.getState().profile, null)
})
await check('401 outside Telegram (no initData to refresh with) → session ended', async () => {
  login('old-token'); setTelegram(null)
  script = [() => ({ status: 401 })]
  assert.equal((await rejected(apiClient.get('/x'))).kind, 'session')
  assert.equal(useAuthStore.getState().isAuthenticated, false)
})
await check('a fresh token that is refused again (401) → session ended, no refresh loop', async () => {
  login('old-token'); setTelegram('init-data')
  script = [() => ({ status: 401 }), () => ({ status: 200, data: { access_token: 't3' } }), () => ({ status: 401 })]
  assert.equal((await rejected(apiClient.get('/x'))).kind, 'session')
  assert.equal(calls.length, 3)
  assert.equal(useAuthStore.getState().isAuthenticated, false)
})
await check('403 "Account banned" mid-session → session ended; other 403s are left alone', async () => {
  login('old-token')
  script = [() => ({ status: 403, data: { detail: 'Account banned' } })]
  assert.equal((await rejected(apiClient.get('/x'))).kind, 'session')
  assert.equal(useAuthStore.getState().isAuthenticated, false)
  login('old-token')
  script = [() => ({ status: 403, data: { detail: 'Access denied' } })]
  const e = await rejected(apiClient.get('/access/video/1/source'))
  assert.deepEqual([e.status, e.kind], [403, 'http'])
  assert.equal(useAuthStore.getState().isAuthenticated, true)
})
await check('/auth/* calls never trigger refresh', async () => {
  login('old-token'); setTelegram('init-data')
  script = [() => ({ status: 401, data: { detail: 'Authentication failed' } })]
  const e = await rejected(authApi.login('bad'))
  assert.equal(e.status, 401); assert.equal(calls.length, 1)
})

// ── app settings refresh ─────────────────────────────────────────────────────
await check('refreshAppConfig: loads when missing, single-flight, keeps last good config on failure', async () => {
  useConfigStore.setState({ appConfig: null })
  script = [() => ({ status: 200, data: { app_name: 'A', maintenance_mode: false } })]
  await Promise.all([refreshAppConfig(), refreshAppConfig()])
  assert.equal(calls.length, 1); assert.equal(useConfigStore.getState().appConfig?.app_name, 'A')
  await refreshAppConfig()                              // fresh → no request
  assert.equal(calls.length, 1)
  script = [() => 'network']
  await refreshAppConfig(true)                          // forced + failing → old config stays
  assert.equal(useConfigStore.getState().appConfig?.app_name, 'A')
  script = [() => ({ status: 200, data: { app_name: 'B', maintenance_mode: true } })]
  await refreshAppConfig(true)
  assert.equal(useConfigStore.getState().appConfig?.maintenance_mode, true)
})

console.log(`\n${n} checks passed`)
