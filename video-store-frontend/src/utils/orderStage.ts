import type { Order } from '@/types'

// ─── Order status → page ──────────────────────────────────────────────────────
// The Backend decides what an order's status is (Binance verification / admin
// review). The frontend only maps that status to the matching screen — it never
// decides that a payment succeeded. Pure (no React) so it can be tested offline.

export type OrderStage = 'pay' | 'pending' | 'success' | 'failed'

export function stageOf(order: Pick<Order, 'status'>): OrderStage {
  switch (order.status) {
    case 'completed':
      return 'success'
    case 'failed':
    case 'expired':
    case 'refunded':
      return 'failed'
    case 'under_review':
    case 'payment_submitted':
      return 'pending'
    case 'pending':
    case 'awaiting_payment':
    default:
      return 'pay'
  }
}

export const stagePath = (orderId: string, stage: OrderStage): string =>
  stage === 'pay' ? `/payment/${orderId}` : `/payment/${orderId}/${stage}`

export const contentPath = (o: Pick<Order, 'content_type' | 'content_id'>): string =>
  `/${o.content_type === 'video' ? 'videos' : 'packages'}/${o.content_id}`

/** True when an unfinished order has passed its Backend-set deadline. */
export function isPastDeadline(order: Pick<Order, 'expires_at'>, now: number = Date.now()): boolean {
  return new Date(order.expires_at).getTime() <= now
}
