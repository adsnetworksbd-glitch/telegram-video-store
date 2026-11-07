/**
 * Phase 8 Part 1 — session-state check for src/store (auth + user stores).
 *
 * Run (after `npm install`, with the REAL zustand):
 *     npx tsx tests/auth-store.check.mts
 *
 * Executes the real src/store/index.ts. It does NOT render React / AuthGate and
 * does not touch the network; it only checks the store transitions that
 * AuthGate and the axios interceptor rely on.
 */
import assert from 'node:assert/strict'
import { useAuthStore, useUserStore, resetSession } from '../src/store/index.ts'

const profile = { telegram_id: '1', first_name: 'A' } as never
let n = 0
const check = (name: string, fn: () => void) => { fn(); n++; console.log('ok  ', name) }

check('initial state is loading + unauthenticated (AuthGate shows loading screen)', () => {
  const s = useAuthStore.getState()
  assert.equal(s.isLoading, true); assert.equal(s.isAuthenticated, false); assert.equal(s.token, null)
})

check('setToken => authenticated, loading cleared, error cleared', () => {
  useAuthStore.getState().setError('old'); useAuthStore.getState().setLoading(true)
  useAuthStore.getState().setToken('jwt-1')
  const s = useAuthStore.getState()
  assert.deepEqual([s.token, s.isAuthenticated, s.isLoading, s.error], ['jwt-1', true, false, null])
})

check('setError (auth failure) => unauthenticated + message, loading off', () => {
  useAuthStore.setState({ token: null, isAuthenticated: false, isLoading: true })
  useAuthStore.getState().setError('failed')
  const s = useAuthStore.getState()
  assert.deepEqual([s.isAuthenticated, s.isLoading, s.error], [false, false, 'failed'])
})

check('resetSession(message) drops JWT and ALL per-user data in memory', () => {
  useAuthStore.getState().setToken('jwt-2')
  useUserStore.getState().setProfile(profile)
  useUserStore.getState().setNotifications([{ id: 'n' } as never], 3)
  resetSession('Session শেষ')
  const a = useAuthStore.getState(), u = useUserStore.getState()
  assert.deepEqual([a.token, a.isAuthenticated, a.isLoading, a.error], [null, false, false, 'Session শেষ'])
  assert.deepEqual([u.profile, u.notifications, u.unreadCount], [null, [], 0])
})

check('resetSession() (logout) leaves unauthenticated with no error', () => {
  useAuthStore.getState().setToken('jwt-3'); useUserStore.getState().setProfile(profile)
  resetSession()
  const a = useAuthStore.getState()
  assert.deepEqual([a.token, a.isAuthenticated, a.error], [null, false, null])
  assert.equal(useUserStore.getState().profile, null)
})

check('auth is flipped before user data is cleared (app unmounts first)', () => {
  useAuthStore.getState().setToken('jwt-4'); useUserStore.getState().setProfile(profile)
  const order: string[] = []
  const ua = useAuthStore.subscribe(() => order.push('auth'))
  const uu = useUserStore.subscribe(() => order.push('user'))
  resetSession('x'); ua(); uu()
  assert.deepEqual(order, ['auth', 'user'])
})

console.log(`\n${n} checks passed`)
