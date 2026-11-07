import { useEffect, useState } from 'react'
import { Button, ConfirmSheet, EmptyState, ErrorState, LoadMoreButton, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord, type FieldSpec } from '../configApi'
import { Card, ErrorBanner, Field, inputCls } from '../ui'
import { errorText, fmtDateTime, str } from '../util'
import { useAdminList } from '../useAdminList'

interface Cfg { fields: Record<string, FieldSpec>; max_broadcast_users: number }

export default function Notifications() {
  const [cfg, setCfg] = useState<Cfg | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [target, setTarget] = useState<'user' | 'all'>('all')
  const [userId, setUserId] = useState('')
  const [type, setType] = useState('')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [actionType, setActionType] = useState('')
  const [actionId, setActionId] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [lookup, setLookup] = useState('')
  const [lookupId, setLookupId] = useState('')

  useEffect(() => {
    adminConfigApi.notificationConfig()
      .then((c: Cfg) => { setCfg(c); setType(c.fields.type?.default ? String(c.fields.type.default) : (c.fields.type?.options?.[0] ?? '')) })
      .catch((e) => setLoadError(errorText(e)))
  }, [])

  const history = useAdminList<AdminRecord>((p) => adminConfigApi.userNotifications(lookupId, p), [lookupId], lookupId !== '')

  if (loadError) return <ErrorState message={loadError} onRetry={() => window.location.reload()} />
  if (!cfg) return <Skeleton className="h-[160px] rounded-[12px]" />
  const f = cfg.fields
  const needsAction = actionType !== ''

  function validate(): string | null {
    if (target === 'user' && !userId.trim()) return 'User ID দিন।'
    if (!title.trim()) return 'শিরোনাম দিন।'
    if (!body.trim()) return 'বার্তা লিখুন।'
    if (needsAction && !actionId.trim()) return 'Video / Package ID দিন (Action ও ID একসঙ্গে লাগে)।'
    return null
  }

  async function send() {
    setBusy(true); setErr(null)
    try {
      const res = await adminConfigApi.sendNotification({
        target, user_id: target === 'user' ? userId.trim() : undefined, type, title: title.trim(), body: body.trim(),
        action_type: needsAction ? actionType : undefined, action_id: needsAction && actionId.trim() ? actionId.trim() : undefined,
      })
      toast(`${res.recipients} জনকে Notification পাঠানো হয়েছে।`, 'success')
      setConfirmOpen(false); setTitle(''); setBody(''); setActionId('')
    } catch (e) { setErr(errorText(e)); setConfirmOpen(false) } finally { setBusy(false) }
  }

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">Notification</h1>
      <Card title="নতুন Notification পাঠান">
        <Field label={f.target?.label ?? 'কাকে পাঠাবেন'}>
          <select className={inputCls} value={target} onChange={(e) => setTarget(e.target.value as 'user' | 'all')}>
            {(f.target?.options ?? ['all', 'user']).map((o) => <option key={o} value={o}>{o === 'all' ? 'সব (Banned বাদে)' : 'একজন ব্যবহারকারী'}</option>)}
          </select>
        </Field>
        {target === 'user' && <Field label="User ID"><input className={inputCls} maxLength={f.user_id?.max ?? 64} value={userId} onChange={(e) => setUserId(e.target.value)} /></Field>}
        <Field label="ধরন">
          <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
            {(f.type?.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </Field>
        <Field label="শিরোনাম"><input className={inputCls} maxLength={f.title?.max ?? 100} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="বার্তা"><textarea className={inputCls} rows={3} maxLength={f.body?.max ?? 500} value={body} onChange={(e) => setBody(e.target.value)} /></Field>
        <Field label="ট্যাপ করলে কী খুলবে (ঐচ্ছিক)">
          <select className={inputCls} value={actionType} onChange={(e) => setActionType(e.target.value)}>
            <option value="">কিছু না</option>
            {(f.action_type?.options ?? []).filter((o) => o !== 'open_order').map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </Field>
        {needsAction && <Field label={f.action_id?.label ?? 'ID'} help="ভিডিও/প্যাকেজ খোলার ক্ষেত্রে সেটির ID; সার্ভার ID আছে কিনা যাচাই করবে"><input className={inputCls} maxLength={f.action_id?.max ?? 128} value={actionId} onChange={(e) => setActionId(e.target.value)} /></Field>}
        <ErrorBanner message={err} />
        <Button onClick={() => { const p = validate(); if (p) { setErr(p); return } setErr(null); if (target === 'all') setConfirmOpen(true); else void send() }} loading={busy && !confirmOpen}>পাঠান</Button>
        <p className="text-[11px] text-[#6B7280]">সব ব্যবহারকারীর জন্য সর্বোচ্চ {cfg.max_broadcast_users.toLocaleString('en-US')} জন; সীমা পার হলে কিছুই পাঠানো হয় না।</p>
      </Card>

      <ConfirmSheet open={confirmOpen} title="সবাইকে পাঠাবেন?" confirmLabel="পাঠান" loading={busy} onConfirm={() => void send()} onCancel={() => setConfirmOpen(false)}>
        <p className="text-[12px] text-[#9CA3AF]">এটি Banned নয় এমন সব ব্যবহারকারীর কাছে যাবে এবং ফেরানো যাবে না।</p>
      </ConfirmSheet>

      <Card title="ব্যবহারকারীর Notification দেখুন (শুধু পড়া)">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setLookupId(lookup.trim()) }}>
          <input className={inputCls} placeholder="User ID" value={lookup} onChange={(e) => setLookup(e.target.value)} />
          <button type="submit" className="btn-ghost !w-auto px-4">দেখুন</button>
        </form>
        {lookupId && (history.error && history.items.length === 0 ? <ErrorState message={history.error} onRetry={history.reload} /> : history.loading && history.items.length === 0 ? (
          <Skeleton className="h-[60px] rounded-[12px]" />
        ) : history.items.length === 0 ? <EmptyState icon="🔔" title="কোনো Notification নেই" /> : (
          <ul className="flex flex-col gap-2">
            {history.items.map((n) => (
              <li key={n.id} className="rounded-[10px] bg-card px-3 py-2">
                <div className="text-[12.5px] font-medium text-white">{str(n.title)}</div>
                <div className="text-[12px] text-[#9CA3AF]">{str(n.body)}</div>
                <div className="text-[11px] text-[#6B7280]">{fmtDateTime(n.created_at)} · {n.is_read === true ? 'পড়া হয়েছে' : 'অপঠিত'}{str(n.sent_by) && ` · ${str(n.sent_by)}`}</div>
              </li>
            ))}
          </ul>
        ))}
        {history.hasMore && <LoadMoreButton onClick={history.more} loading={history.loading} />}
      </Card>
    </div>
  )
}
