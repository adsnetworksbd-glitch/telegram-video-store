import { useEffect } from 'react'
import { getTelegram, tgSupports } from '@/hooks/useTelegram'

/**
 * While `active` (an ad is loading/showing) block accidental navigation:
 *  - Telegram: hide the native BackButton and ask before the Mini App closes
 *  - Browser / WebView: confirm on tab close / reload and swallow the Back gesture
 * Everything is restored on cleanup. No-op when not active.
 */
export function useAdNavigationLock(active: boolean) {
  useEffect(() => {
    if (!active) return
    const tg = getTelegram()
    let hidBack = false
    let closing = false
    try {
      if (tg && tgSupports('6.1') && tg.BackButton.isVisible) { tg.BackButton.hide(); hidBack = true }
      if (tg && tgSupports('6.2')) { tg.enableClosingConfirmation?.(); closing = true }
    } catch { /* old client: ignore */ }

    const onBeforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    // Re-push the current entry so one Back gesture only "uses up" the guard.
    const guard = () => window.history.pushState(window.history.state, '', window.location.href)
    guard()
    window.addEventListener('popstate', guard)
    window.addEventListener('beforeunload', onBeforeUnload)

    return () => {
      window.removeEventListener('popstate', guard)
      window.removeEventListener('beforeunload', onBeforeUnload)
      try {
        if (closing) tg?.disableClosingConfirmation?.()
        if (hidBack) tg?.BackButton.show()
      } catch { /* ignore */ }
    }
  }, [active])
}
