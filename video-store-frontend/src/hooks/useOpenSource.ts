import { useCallback, useRef, useState } from 'react'
import { accessApi } from '@/api'
import { getErrorMessage, getErrorStatus } from '@/api/client'
import { handleSourceRedirect } from '@/utils'
import { toast } from '@/components/ui'

/**
 * Opens a video's source. The Backend re-checks access on every call; the link
 * never lives in the frontend before that.
 * `onDenied` runs when the Backend refuses (403 — e.g. the access just expired)
 * so the caller can re-ask the Backend and refresh what it shows.
 */
export function useOpenSource(onDenied?: () => void) {
  const [openingId, setOpeningId] = useState<string | null>(null)
  const deniedRef = useRef(onDenied)
  deniedRef.current = onDenied

  const open = useCallback(async (videoId: string) => {
    setOpeningId(videoId)
    try {
      const res = await accessApi.getSource(videoId)
      if (!handleSourceRedirect(res.data.source_type, res.data.redirect_url)) {
        toast('এই Source-এর লিংক নিরাপদ/সঠিক নয়, তাই খোলা হয়নি। Support-এ জানান।', 'error')
      }
    } catch (e) {
      const status = getErrorStatus(e)
      if (status === 403) {
        toast('এই ভিডিওতে আপনার Access এখন আর সক্রিয় নেই। মেয়াদ শেষ হয়ে থাকতে পারে।', 'error')
        deniedRef.current?.()
      } else if (status === 404) {
        toast('এই ভিডিওর Source পাওয়া যায়নি বা আর উপলব্ধ নেই।', 'error')
      } else {
        toast(getErrorMessage(e, 'Source খুলতে সমস্যা হয়েছে। আবার চেষ্টা করুন।'), 'error')
      }
    } finally {
      setOpeningId(null)
    }
  }, [])

  return { openingId, open }
}
