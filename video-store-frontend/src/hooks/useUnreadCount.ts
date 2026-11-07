import { userApi } from '@/api'
import { useUserStore } from '@/store'

/**
 * Refreshes the unread-notification badge from the Backend. Best effort: a
 * failure leaves the previous count untouched (the badge is never "invented").
 */
export async function refreshUnreadCount(): Promise<void> {
  try {
    const res = await userApi.notifications({ unread_only: true })
    useUserStore.getState().setNotifications(
      useUserStore.getState().notifications,
      res.data.unread_count,
    )
  } catch { /* keep last known count */ }
}
