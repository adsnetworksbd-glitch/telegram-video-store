import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { userApi, ordersApi } from '@/api'
import type { Transaction, Order, OrderStatus } from '@/types'
import { useUserStore, useConfigStore } from '@/store'
import { SubHeader, PageWrapper } from '@/components/layout'
import { Skeleton, EmptyState, ErrorState, FilterChip, LoadMoreButton, Badge } from '@/components/ui'
import { usePaginatedList } from '@/hooks/usePaginatedList'
import { useContentLookup } from '@/hooks/useContentLookup'
import { formatDate, formatBDT, formatUSDT, cx } from '@/utils'

// ─── Balance & Transactions ───────────────────────────────────────────────────
// Balance and the Deposit tab appear only when the Backend wallet is enabled.
// All rows come from the Backend; nothing is computed or invented here.

type Tab = 'transactions' | 'payments' | 'deposits'

const TX_TYPES = [
  { key: '', label: 'সব' },
  { key: 'purchase', label: 'Purchase' },
  { key: 'refund', label: 'Refund' },
  { key: 'referral_reward', label: 'Referral' },
]
const TX_ICON: Record<string, string> = { purchase: '🛒', refund: '↩️', referral_reward: '🎁', admin_adjustment: '⚙️', deposit: '⬇️' }

const ORDER_STATUS: Record<OrderStatus, { label: string; variant: 'green' | 'orange' | 'red' | 'gray' | 'blue' }> = {
  pending:           { label: 'অপেক্ষমান',        variant: 'orange' },
  awaiting_payment:  { label: 'Payment বাকি',      variant: 'orange' },
  payment_submitted: { label: 'যাচাইয়ের জন্য জমা', variant: 'blue' },
  under_review:      { label: 'রিভিউ চলছে',       variant: 'blue' },
  completed:         { label: 'সম্পন্ন',           variant: 'green' },
  failed:            { label: 'ব্যর্থ',            variant: 'red' },
  refunded:          { label: 'Refunded',          variant: 'gray' },
  expired:           { label: 'মেয়াদ শেষ',        variant: 'gray' },
}

export default function TransactionsPage() {
  const profile = useUserStore((s) => s.profile)
  const appConfig = useConfigStore((s) => s.appConfig)
  const walletOn = Boolean(appConfig?.wallet_enabled && profile?.wallet_enabled)

  const [tab, setTab] = useState<Tab>('transactions')
  // If the wallet gets switched off while on the Deposit tab, fall back safely
  useEffect(() => { if (!walletOn && tab === 'deposits') setTab('transactions') }, [walletOn, tab])

  const tabs: Array<{ key: Tab; label: string }> = [
    { key: 'transactions', label: 'লেনদেন' },
    { key: 'payments', label: 'Payment' },
    ...(walletOn ? [{ key: 'deposits' as const, label: 'Deposit' }] : []),
  ]

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title={walletOn ? '💰 Balance ও Transactions' : '💰 Transactions'} />

      {walletOn && profile && (
        <div className="mx-4 mt-3 bg-secondary/8 border border-secondary/25 rounded-[12px] px-4 py-3">
          <p className="text-[10px] text-[#6B7280] font-semibold">বর্তমান Balance</p>
          <p className="text-[24px] font-extrabold text-[#C4B5FD] leading-[1.2]">{formatBDT(profile.wallet_balance)}</p>
        </div>
      )}

      <div className="px-4 pt-3">
        <div className="flex bg-card border border-border rounded-[10px] p-[3px] mb-3" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={cx(
                'flex-1 py-[7px] rounded-[7px] text-[11px] font-semibold border transition-all',
                tab === t.key ? 'bg-primary/15 text-primary border-primary/30' : 'text-[#6B7280] border-transparent',
              )}
            >{t.label}</button>
          ))}
        </div>
      </div>

      {tab === 'transactions' && <TransactionList key="all" filters />}
      {tab === 'deposits' && <TransactionList key="deposit" fixedType="deposit" emptyTitle="কোনো Deposit নেই" />}
      {tab === 'payments' && <PaymentList />}
    </PageWrapper>
  )
}

function ListSkeleton() {
  return (
    <div className="px-4 space-y-2">
      {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[56px] w-full rounded-[10px]" />)}
    </div>
  )
}

// ─── Transactions / Deposits ──────────────────────────────────────────────────
function TransactionList({ filters = false, fixedType, emptyTitle = 'কোনো Transaction নেই' }: {
  filters?: boolean
  fixedType?: string
  emptyTitle?: string
}) {
  const [type, setType] = useState('')
  const effectiveType = fixedType ?? type
  const list = usePaginatedList<Transaction>(
    (page) => userApi.transactions({ type: effectiveType || undefined, page, limit: 20 }).then((r) => r.data),
    [effectiveType],
  )

  return (
    <>
      {filters && (
        <div className="px-4 flex gap-2 overflow-x-auto pb-1 mb-3">
          {TX_TYPES.map((t) => (
            <FilterChip key={t.key} active={type === t.key} onClick={() => setType(t.key)}>{t.label}</FilterChip>
          ))}
        </div>
      )}

      {list.error && list.items.length === 0 ? <ErrorState message={list.errorMessage ?? undefined} onRetry={list.reload} />
        : list.loading ? <ListSkeleton />
        : list.items.length === 0 ? <EmptyState icon="💰" title={emptyTitle} />
        : (
          <>
            <div className="px-4 space-y-2">
              {list.items.map((tx) => (
                <div key={tx.id} className="flex items-center gap-3 bg-card border border-border rounded-[10px] p-[10px]">
                  <div className="w-[34px] h-[34px] rounded-[9px] bg-card2 flex items-center justify-center text-[16px] flex-shrink-0">
                    {TX_ICON[tx.type] ?? '💳'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-semibold text-white break-words">{tx.description || tx.type}</p>
                    <p className="text-[9px] text-[#6B7280] mt-[1px]">{formatDate(tx.created_at)}</p>
                  </div>
                  <p className={cx('text-[12px] font-bold flex-shrink-0', tx.direction === 'credit' ? 'text-[#6EE7B7]' : 'text-[#FCA5A5]')}>
                    {tx.direction === 'credit' ? '+' : '-'}{formatBDT(tx.amount_bdt)}
                  </p>
                </div>
              ))}
            </div>
            {list.error && <p className="text-center text-[11px] text-[#FCA5A5] mt-3">আরও লোড করা যায়নি।</p>}
            {list.hasMore && <LoadMoreButton onClick={list.loadMore} loading={list.loadingMore} />}
          </>
        )}
    </>
  )
}

// ─── Payment history (orders) ─────────────────────────────────────────────────
function PaymentList() {
  const navigate = useNavigate()
  const list = usePaginatedList<Order>(
    (page) => ordersApi.history({ page, limit: 20 }).then((r) => r.data),
    [],
  )
  const lookup = useContentLookup(list.items)

  function openOrder(o: Order) {
    // Only states that have a matching page are tappable
    if (o.status === 'pending' || o.status === 'awaiting_payment') navigate(`/payment/${o.id}`)
    else if (o.status === 'payment_submitted' || o.status === 'under_review') navigate(`/payment/${o.id}/pending`)
    else if (o.status === 'completed') navigate(`/payment/${o.id}/success`)
    else if (o.status === 'failed') navigate(`/payment/${o.id}/failed`)
  }
  const tappable = (s: OrderStatus) => s !== 'expired' && s !== 'refunded'

  if (list.error && list.items.length === 0) return <ErrorState message={list.errorMessage ?? undefined} onRetry={list.reload} />
  if (list.loading) return <ListSkeleton />
  if (list.items.length === 0) return <EmptyState icon="🧾" title="কোনো Payment নেই" description="Purchase করলে Payment-এর ইতিহাস এখানে দেখা যাবে।" />

  return (
    <>
      <div className="px-4 space-y-2">
        {list.items.map((o) => {
          const st = ORDER_STATUS[o.status] ?? { label: o.status, variant: 'gray' as const }
          const info = lookup(o.content_type, o.content_id)
          const cls = 'w-full text-left bg-card border border-border rounded-[10px] p-[10px] block'
          const body = (
            <>
              <div className="flex items-start justify-between gap-2 mb-1">
                <p className="text-[11px] font-semibold text-white break-words flex-1 min-w-0">
                  {info?.title ?? (o.content_type === 'video' ? 'ভিডিও' : 'Package')}
                </p>
                <Badge variant={st.variant}>{st.label}</Badge>
              </div>
              <div className="flex items-end justify-between gap-2">
                <div className="text-[9px] text-[#6B7280] leading-[1.5]">
                  <p>{formatDate(o.created_at)}{o.completed_at ? ` · সম্পন্ন ${formatDate(o.completed_at)}` : ''}</p>
                  {o.coupon_code && <p>Coupon: {o.coupon_code} (- {formatBDT(o.discount_bdt)})</p>}
                </div>
                <div className="text-right flex-shrink-0">
                  <p className="text-[12px] font-bold text-white">{formatBDT(o.final_bdt)}</p>
                  <p className="text-[9px] text-[#6B7280]">{formatUSDT(o.final_usdt)}</p>
                </div>
              </div>
            </>
          )
          return tappable(o.status)
            ? <button key={o.id} type="button" onClick={() => openOrder(o)} className={cls}>{body}</button>
            : <div key={o.id} className={cls}>{body}</div>
        })}
      </div>
      {list.error && <p className="text-center text-[11px] text-[#FCA5A5] mt-3">আরও লোড করা যায়নি।</p>}
      {list.hasMore && <LoadMoreButton onClick={list.loadMore} loading={list.loadingMore} />}
    </>
  )
}
