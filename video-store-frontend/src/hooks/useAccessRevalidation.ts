import { useEffect, useRef } from 'react'
import type { AccessStatus } from '@/types'
import { msUntilAccessRecheck } from '@/components/access/accessDisplay'

/**
 * Re-asks the Backend when a temporary access may have run out, so an open
 * page does not keep showing "Open" for an access that has expired.
 *
 * This only TRIGGERS a Backend check (`refresh` must call the Backend and show
 * its answer). It never decides expiry itself, so a wrong device clock cannot
 * grant or extend anything — the Backend refuses protected sources regardless.
 * It fires once per distinct `expires_at`; there is no polling loop.
 */
export function useAccessRevalidation(access: AccessStatus | null | undefined, refresh: () => void) {
  const refreshRef = useRef(refresh)
  refreshRef.current = refresh

  const expiresAt = access?.granted && !access.is_lifetime ? access.expires_at : null

  useEffect(() => {
    if (!expiresAt) return
    let timer: number | undefined

    const arm = () => {
      const wait = msUntilAccessRecheck(expiresAt, Date.now())
      if (wait === null) return
      timer = window.setTimeout(() => {
        // A very long wait is capped by the browser — keep waiting until due.
        if (Date.parse(expiresAt) > Date.now()) arm()
        else refreshRef.current()
      }, wait)
    }
    arm()

    // A backgrounded Mini App may have slept through the timer.
    const onVisible = () => {
      if (document.visibilityState === 'visible' && Date.parse(expiresAt) <= Date.now()) refreshRef.current()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [expiresAt])
}
