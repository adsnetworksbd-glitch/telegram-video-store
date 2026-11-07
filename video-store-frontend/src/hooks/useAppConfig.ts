import { configApi } from '@/api'
import { useConfigStore } from '@/store'

// App settings (maintenance mode, announcement, USDT rate, support links, …) are
// admin-controlled and read from GET /config. The login screen loads them once,
// but that load is deliberately non-fatal — so if it failed, or the admin changed
// something while the app stayed open, this keeps them current:
//   • single-flight (concurrent callers share one request)
//   • refetch only when missing or older than CONFIG_STALE_MS
//   • a failed refresh keeps the last good config (never blanks it)
export const CONFIG_STALE_MS = 5 * 60 * 1000

let inflight: Promise<void> | null = null
let loadedAt = 0

export function refreshAppConfig(force = false): Promise<void> {
  const { appConfig, setAppConfig } = useConfigStore.getState()
  // A config that is already present but unstamped was loaded by the login screen just now.
  if (appConfig && loadedAt === 0) loadedAt = Date.now()
  const fresh = appConfig !== null && Date.now() - loadedAt < CONFIG_STALE_MS
  if (!force && fresh) return Promise.resolve()

  inflight ??= configApi
    .getAppConfig()
    .then((res) => { setAppConfig(res.data); loadedAt = Date.now() })
    .catch(() => { /* keep whatever config we have */ })
    .finally(() => { inflight = null })
  return inflight
}
