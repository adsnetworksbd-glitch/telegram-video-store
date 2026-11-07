import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, ErrorState, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminAccount } from '../configApi'
import { useAdminStore, ROLE_LABEL } from '../store'
import { Card, ErrorBanner, Field, inputCls } from '../ui'
import { errorText, fmtDateTime } from '../util'

export default function Admins() {
  const me = useAdminStore((s) => s.admin)
  const [items, setItems] = useState<AdminAccount[] | null>(null)
  const [roles, setRoles] = useState<string[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [nu, setNu] = useState({ username: '', display_name: '', role: '', password: '' })
  const [pw, setPw] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoadError(null)
    try { const r = await adminConfigApi.admins(); setItems(r.items); setRoles(r.roles); setNu((x) => ({ ...x, role: x.role || r.roles[r.roles.length - 1] || '' })) }
    catch (e) { setLoadError(errorText(e)) }
  }, [])
  useEffect(() => { void load() }, [load])

  if (loadError) return <ErrorState message={loadError} onRetry={() => void load()} />
  if (!items) return <Skeleton className="h-[120px] rounded-[12px]" />

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setErr(null)
    try { await fn(); toast(ok, 'success'); await load() } catch (e) { setErr(errorText(e)) } finally { setBusy(false) }
  }

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">Admin অ্যাকাউন্ট</h1>
      <ErrorBanner message={err} />
      <ul className="flex flex-col gap-2">
        {items.map((a) => {
          const editable = a.source === 'firestore'
          const self = a.username === me?.username
          return (
            <li key={a.username} className="card-base flex flex-col gap-2 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-[13px] font-medium text-white">{a.display_name || a.username} <span className="text-[11px] text-[#6B7280]">@{a.username}</span></span>
                <span className="flex gap-1">{a.is_locked && <Badge variant="red">Locked</Badge>}<Badge variant={a.is_active === false ? 'gray' : 'green'}>{a.is_active === false ? 'বন্ধ' : 'সক্রিয়'}</Badge></span>
              </div>
              <div className="text-[11.5px] text-[#9CA3AF]">{ROLE_LABEL[a.role as keyof typeof ROLE_LABEL] ?? a.role} · শেষ লগইন {fmtDateTime(a.last_login_at)}{!editable && ' · Environment-এ সেট করা (এখান থেকে বদলানো যায় না)'}</div>
              {editable && !self && (
                <div className="flex flex-col gap-2 border-t border-border pt-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <select className={`${inputCls} !w-auto`} value={a.role} disabled={busy} onChange={(e) => void run(() => adminConfigApi.updateAdmin(a.username, { role: e.target.value }), 'Role বদলানো হয়েছে।')}>
                      {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r as keyof typeof ROLE_LABEL] ?? r}</option>)}
                    </select>
                    <button className="btn-ghost !w-auto px-3 !py-1.5" disabled={busy} onClick={() => void run(() => adminConfigApi.updateAdmin(a.username, { is_active: a.is_active === false }), a.is_active === false ? 'সক্রিয় করা হয়েছে।' : 'বন্ধ করা হয়েছে।')}>
                      {a.is_active === false ? 'সক্রিয় করুন' : 'বন্ধ করুন'}
                    </button>
                  </div>
                  <div className="flex gap-2">
                    <input className={inputCls} type="password" autoComplete="new-password" placeholder="নতুন পাসওয়ার্ড" value={pw[a.username] ?? ''} onChange={(e) => setPw((x) => ({ ...x, [a.username]: e.target.value }))} />
                    <button className="btn-ghost !w-auto px-3" disabled={busy || !(pw[a.username] ?? '')} onClick={() => void run(() => adminConfigApi.resetAdminPassword(a.username, pw[a.username]), 'পাসওয়ার্ড বদলানো হয়েছে।').then(() => setPw((x) => ({ ...x, [a.username]: '' })))}>রিসেট</button>
                  </div>
                </div>
              )}
              {self && <div className="text-[11px] text-[#6B7280]">নিজের অ্যাকাউন্টের Role/Status এখান থেকে বদলানো যায় না।</div>}
            </li>
          )
        })}
      </ul>
      <Card title="নতুন Admin তৈরি">
        <Field label="Username"><input className={inputCls} autoComplete="off" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} /></Field>
        <Field label="প্রদর্শিত নাম (ঐচ্ছিক)"><input className={inputCls} value={nu.display_name} onChange={(e) => setNu({ ...nu, display_name: e.target.value })} /></Field>
        <Field label="Role">
          <select className={inputCls} value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
            {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r as keyof typeof ROLE_LABEL] ?? r}</option>)}
          </select>
        </Field>
        <Field label="পাসওয়ার্ড"><input className={inputCls} type="password" autoComplete="new-password" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} /></Field>
        <Button loading={busy} onClick={() => {
          if (!nu.username.trim() || !nu.password || !nu.role) { setErr('Username, Role ও পাসওয়ার্ড দিন।'); return }
          void run(() => adminConfigApi.createAdmin({ username: nu.username.trim(), role: nu.role, password: nu.password, display_name: nu.display_name.trim() || undefined }), 'Admin তৈরি হয়েছে।')
            .then(() => setNu((x) => ({ ...x, username: '', display_name: '', password: '' })))
        }}>তৈরি করুন</Button>
      </Card>
    </div>
  )
}
