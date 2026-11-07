import { useCallback, useEffect, useState } from 'react'
import { Badge, ConfirmSheet, EmptyState, ErrorState, FilterChip, LoadMoreButton, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, inputCls } from '../ui'
import { errorText, fmtCount, fmtDateTime, fmtMoney, num, str } from '../util'
import { useAdminList } from '../useAdminList'

const STATE_VARIANT: Record<string, 'blue' | 'green' | 'orange' | 'red' | 'gray'> = { active: 'green', expired: 'gray', revoked: 'red', scheduled: 'orange' }

function UserDetail({ uid, canManage, onChanged }: { uid: string; canManage: boolean; onChanged: () => void }) {
  const [user, setUser] = useState<AdminRecord | null>(null)
  const [ents, setEnts] = useState<AdminRecord[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [banOpen, setBanOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [gType, setGType] = useState<'video' | 'package'>('video')
  const [gId, setGId] = useState('')
  const [gHours, setGHours] = useState('')
  const [extra, setExtra] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const [u, a] = await Promise.all([adminConfigApi.user(uid), adminConfigApi.userAccess(uid) as Promise<{ entitlements: AdminRecord[] }>])
      setUser(u)
      setEnts(a.entitlements)
    } catch (e) {
      setLoadError(errorText(e))
    }
  }, [uid])
  useEffect(() => { void load() }, [load])

  if (loadError) return <ErrorState message={loadError} onRetry={() => void load()} />
  if (!user || !ents) return <Skeleton className="h-[120px] rounded-[12px]" />
  const banned = user.is_banned === true

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true)
    setErr(null)
    try { await fn(); toast(ok, 'success'); await load(); onChanged() } catch (e) { setErr(errorText(e)) } finally { setBusy(false) }
  }

  async function grant() {
    const hours = Number(gHours)
    if (!gId.trim()) { setErr('Video / Package ID দিন।'); return }
    if (!Number.isInteger(hours) || hours < 0) { setErr('সময় ঘণ্টায় (০ = Lifetime) সঠিক পূর্ণসংখ্যা হতে হবে।'); return }
    await run(() => adminConfigApi.grantAccess({ user_id: uid, content_type: gType, content_id: gId.trim(), duration_hours: hours }), 'Access দেওয়া হয়েছে।')
    setGId('')
  }

  return (
    <div className="flex flex-col gap-3 rounded-[12px] border border-border bg-card2 p-3">
      <div className="flex flex-col gap-0.5 text-[12px] text-[#9CA3AF]">
        <div>ID: <span className="break-all text-white">{user.id}</span></div>
        <div>মোট খরচ: <span className="text-white">{fmtMoney(num(user.total_spent_bdt))}</span> · যোগ দিয়েছেন: {fmtDateTime(user.created_at)} · শেষ লগইন: {fmtDateTime(user.last_login_at)}</div>
        {str(user.referred_by) && <div>Referred by: <span className="text-white">{str(user.referred_by)}</span></div>}
        {banned && <div className="text-[#FCA5A5]">Banned: {str(user.ban_reason) || 'কারণ দেওয়া হয়নি'} ({fmtDateTime(user.banned_at)}, {str(user.banned_by) || '—'})</div>}
      </div>
      {canManage && (
        <div>
          <button className={banned ? 'btn-success !w-auto px-4 !py-2' : 'btn-ghost !w-auto px-4 !py-2'} onClick={() => { setReason(''); setErr(null); setBanOpen(true) }}>
            {banned ? 'Unban করুন' : 'Ban করুন'}
          </button>
        </div>
      )}
      <ErrorBanner message={err} />

      <h3 className="text-[13px] font-bold text-white">Access ও মেয়াদ ({ents.length})</h3>
      {ents.length === 0 ? <p className="text-[12px] text-[#6B7280]">কোনো Access নেই।</p> : (
        <ul className="flex flex-col gap-2">
          {ents.map((e) => {
            const state = str(e.state)
            return (
              <li key={e.id} className="card-base flex flex-col gap-1 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <Badge variant={STATE_VARIANT[state] ?? 'gray'}>{state || '—'}</Badge>
                  <span className="text-[11px] text-[#6B7280]">{str(e.access_source)}</span>
                </div>
                <div className="text-[12px] text-[#9CA3AF]">{str(e.content_type)}: <span className="break-all text-white">{str(e.content_id)}</span></div>
                <div className="text-[12px] text-[#9CA3AF]">মেয়াদ: <span className="text-white">{e.is_lifetime === true ? 'Lifetime' : fmtDateTime(e.expires_at)}</span></div>
                {str(e.revoked_reason) && <div className="text-[11.5px] text-[#FCA5A5]">বাতিল: {str(e.revoked_reason)}</div>}
                {canManage && state !== 'revoked' && (
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    {e.is_lifetime !== true && (
                      <>
                        <input className={`${inputCls} !w-[90px] !py-1.5`} inputMode="numeric" placeholder="ঘণ্টা" value={extra[e.id] ?? ''} onChange={(ev) => setExtra((x) => ({ ...x, [e.id]: ev.target.value }))} />
                        <button className="btn-ghost !w-auto px-3 !py-1.5" disabled={busy} onClick={() => {
                          const h = Number(extra[e.id])
                          if (!Number.isInteger(h) || h < 1) { setErr('বাড়ানোর ঘণ্টা ১ বা তার বেশি পূর্ণসংখ্যা হতে হবে।'); return }
                          void run(() => adminConfigApi.extendAccess(e.id, { hours: h }), 'মেয়াদ বাড়ানো হয়েছে।')
                        }}>মেয়াদ বাড়ান</button>
                        <button className="btn-ghost !w-auto px-3 !py-1.5" disabled={busy} onClick={() => void run(() => adminConfigApi.extendAccess(e.id, { lifetime: true }), 'Lifetime করা হয়েছে।')}>Lifetime</button>
                      </>
                    )}
                    <button className="btn-ghost !w-auto px-3 !py-1.5" disabled={busy} onClick={() => {
                      if (window.confirm('এই Access বাতিল করবেন? Purchase History মুছবে না।')) void run(() => adminConfigApi.revokeAccess(e.id, 'admin_revoked'), 'Access বাতিল হয়েছে।')
                    }}>বাতিল</button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {canManage && (
        <Card title="Access দিন (Admin Grant)">
          <Field label="ধরন">
            <select className={inputCls} value={gType} onChange={(e) => setGType(e.target.value as 'video' | 'package')}>
              <option value="video">ভিডিও</option><option value="package">প্যাকেজ</option>
            </select>
          </Field>
          <Field label="Video / Package ID"><input className={inputCls} value={gId} onChange={(e) => setGId(e.target.value)} /></Field>
          <Field label="সময় (ঘণ্টা)" help="০ = Lifetime"><input className={inputCls} inputMode="numeric" value={gHours} onChange={(e) => setGHours(e.target.value)} /></Field>
          <button className="btn-secondary" disabled={busy} onClick={() => void grant()}>Access দিন</button>
        </Card>
      )}

      <ConfirmSheet
        open={banOpen}
        title={banned ? 'Unban করবেন?' : 'ব্যবহারকারীকে Ban করবেন?'}
        confirmLabel={banned ? 'Unban' : 'Ban'}
        loading={busy}
        onConfirm={() => void run(() => adminConfigApi.setBanned(uid, !banned, reason.trim() || undefined), banned ? 'Unban করা হয়েছে।' : 'Ban করা হয়েছে।').then(() => setBanOpen(false))}
        onCancel={() => setBanOpen(false)}
      >
        {!banned && <Field label="কারণ (ঐচ্ছিক)"><input className={inputCls} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>}
        <p className="text-[12px] text-[#9CA3AF]">{banned ? 'ব্যবহারকারী আবার অ্যাপ ব্যবহার করতে পারবেন।' : 'Ban হলে ব্যবহারকারীর সব API অ্যাক্সেস বন্ধ হবে। আগের Purchase ও Access ডেটা অক্ষত থাকবে।'}</p>
      </ConfirmSheet>
    </div>
  )
}

export default function Users() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'users.manage')
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [banned, setBanned] = useState<'' | 'yes' | 'no'>('')
  const [open, setOpen] = useState<string | null>(null)
  const list = useAdminList<AdminRecord>(
    (p) => adminConfigApi.users({ q: query || undefined, banned: banned === '' ? undefined : banned === 'yes', page: p }),
    [query, banned],
  )

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">ইউজার ম্যানেজমেন্ট <span className="text-[12px] font-normal text-[#9CA3AF]">({fmtCount(list.total)})</span></h1>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()) }}>
        <input className={inputCls} placeholder="নাম / Username / ID" value={q} onChange={(e) => setQ(e.target.value)} />
        <button type="submit" className="btn-ghost !w-auto px-4">খুঁজুন</button>
      </form>
      <div className="flex gap-2">
        <FilterChip active={banned === ''} onClick={() => setBanned('')}>সব</FilterChip>
        <FilterChip active={banned === 'no'} onClick={() => setBanned('no')}>Active</FilterChip>
        <FilterChip active={banned === 'yes'} onClick={() => setBanned('yes')}>Banned</FilterChip>
      </div>
      {list.error && list.items.length === 0 ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading && list.items.length === 0 ? (
        <Skeleton className="h-[72px] rounded-[12px]" />
      ) : list.items.length === 0 ? <EmptyState icon="👥" title="কোনো ইউজার পাওয়া যায়নি" /> : (
        <ul className="flex flex-col gap-2">
          {list.items.map((u) => (
            <li key={u.id} className="card-base flex flex-col gap-2 p-3">
              <button className="flex items-center justify-between gap-2 text-left" onClick={() => setOpen(open === u.id ? null : u.id)}>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-medium text-white">{[str(u.first_name), str(u.last_name)].filter(Boolean).join(' ') || '—'}{str(u.username) && ` @${str(u.username)}`}</span>
                  <span className="block truncate text-[11px] text-[#6B7280]">{u.id}</span>
                </span>
                {u.is_banned === true ? <Badge variant="red">Banned</Badge> : <Badge variant="green">Active</Badge>}
              </button>
              {open === u.id && <UserDetail uid={u.id} canManage={canManage} onChanged={list.reload} />}
            </li>
          ))}
        </ul>
      )}
      {list.hasMore && <LoadMoreButton onClick={list.more} loading={list.loading} />}
    </div>
  )
}
