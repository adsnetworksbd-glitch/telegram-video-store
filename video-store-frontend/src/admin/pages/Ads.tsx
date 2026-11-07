import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Badge, Button, EmptyState, ErrorState, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Toggle, inputCls } from '../ui'
import { bool, errorText, loadSchema, num, str } from '../util'

interface Network {
  id: string; name: string; type: string; is_enabled: boolean; priority: number | null; zone_id: string; sdk_url: string
  placements: Record<string, boolean>; default_ads_required: number | null; unlock_duration_hours: number | null
  session_timeout_minutes: number | null
}
interface Readiness {
  id: string; ready: boolean; provider_known: boolean; supports_s2s?: boolean; secret_setting?: string
  secret_configured?: boolean; problems: string[]; placements: Record<string, boolean>
}
interface Draft {
  id: string; name: string; type: string; priority: string; zone_id: string; sdk_url: string
  placements: Record<string, boolean>; default_ads_required: string; unlock_value: string; unlock_unit: 'hours' | 'days' | 'lifetime'
  session_timeout_minutes: string; is_enabled: boolean
}

const PLACEMENT_LABEL: Record<string, string> = {
  video_unlock: 'ভিডিও Unlock', package_unlock: 'প্যাকেজ Unlock', rewarded: 'Rewarded Ad',
}

function toNetwork(r: Record<string, unknown>): Network {
  const pl = (r.placements && typeof r.placements === 'object' ? r.placements : {}) as Record<string, unknown>
  return {
    id: str(r.id), name: str(r.name), type: str(r.type), is_enabled: bool(r.is_enabled), priority: num(r.priority),
    zone_id: str(r.zone_id), sdk_url: str(r.sdk_url), placements: Object.fromEntries(Object.entries(pl).map(([k, v]) => [k, v === true])),
    default_ads_required: num(r.default_ads_required), unlock_duration_hours: num(r.unlock_duration_hours),
    session_timeout_minutes: num(r.session_timeout_minutes),
  }
}

function toDraft(n: Network | null, placements: string[], f: Record<string, FieldSpec>): Draft {
  const hours = n ? n.unlock_duration_hours : num(f.unlock_duration_hours?.default)
  const life = hours === 0
  const days = !life && hours !== null && hours % 24 === 0
  return {
    id: n?.id ?? '', name: n?.name ?? '', type: n?.type ?? '', priority: n?.priority === null || n === null ? '' : String(n.priority),
    zone_id: n?.zone_id ?? '', sdk_url: n?.sdk_url ?? '',
    placements: Object.fromEntries(placements.map((p) => [p, n ? n.placements[p] === true : false])),
    default_ads_required: String((n ? n.default_ads_required : num(f.default_ads_required?.default)) ?? ''),
    unlock_value: life || hours === null ? '' : String(days ? hours / 24 : hours), unlock_unit: life ? 'lifetime' : days ? 'days' : 'hours',
    session_timeout_minutes: String((n ? n.session_timeout_minutes : num(f.session_timeout_minutes?.default)) ?? ''),
    is_enabled: n?.is_enabled ?? false,
  }
}

function NetworkForm({ initial, isNew, providers, placements, fields, onSaved, onCancel }: {
  initial: Draft; isNew: boolean; providers: string[]; placements: string[]; fields: Record<string, FieldSpec>
  onSaved: () => void; onCancel: () => void
}) {
  const [d, setD] = useState<Draft>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (saving) return
    const id = d.id.trim()
    if (isNew && !/^[A-Za-z0-9_-]{1,64}$/.test(id)) { setError('Network ID-তে শুধু অক্ষর, সংখ্যা, _ বা - (সর্বোচ্চ ৬৪) ব্যবহার করুন।'); return }
    if (!d.name.trim()) { setError('নাম দিন।'); return }
    if (!d.type) { setError('Provider বাছুন।'); return }
    const body: Record<string, unknown> = { name: d.name.trim(), type: d.type, is_enabled: d.is_enabled, placements: d.placements, zone_id: d.zone_id.trim() }
    if (d.sdk_url.trim()) {
      if (!d.sdk_url.trim().startsWith('https://')) { setError('SDK URL https:// দিয়ে শুরু হতে হবে।'); return }
      body.sdk_url = d.sdk_url.trim()
    }
    const intField = (key: string, raw: string, label: string, min: number, max: number): boolean => {
      if (raw.trim() === '') return true
      const n = Number(raw)
      if (!Number.isInteger(n) || n < min || n > max) { setError(`${label}: ${min}–${max} এর মধ্যে পূর্ণসংখ্যা দিন।`); return false }
      body[key] = n
      return true
    }
    if (!intField('priority', d.priority, 'Priority', fields.priority?.min ?? 0, fields.priority?.max ?? 1000)) return
    if (!intField('default_ads_required', d.default_ads_required, 'Required Ads', fields.default_ads_required?.min ?? 1, fields.default_ads_required?.max ?? 50)) return
    if (!intField('session_timeout_minutes', d.session_timeout_minutes, 'Session timeout', fields.session_timeout_minutes?.min ?? 1, fields.session_timeout_minutes?.max ?? 240)) return
    if (d.unlock_unit === 'lifetime') body.unlock_duration_hours = 0
    else if (d.unlock_value.trim() !== '') {
      const v = Number(d.unlock_value)
      const hours = d.unlock_unit === 'days' ? v * 24 : v
      if (!Number.isInteger(v) || v <= 0 || hours > (fields.unlock_duration_hours?.max ?? 87600)) { setError('Unlock সময় সঠিক পূর্ণসংখ্যা হতে হবে।'); return }
      body.unlock_duration_hours = hours
    }
    setSaving(true)
    setError(null)
    try {
      await adminConfigApi.saveAdNetwork(isNew ? id : d.id, body)
      toast(isNew ? 'Network তৈরি হয়েছে (বন্ধ অবস্থায়)।' : 'সংরক্ষণ হয়েছে।', 'success')
      onSaved()
    } catch (err) {
      setError(errorText(err))
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <Card title={isNew ? 'নতুন Ad Network' : 'Ad Network সম্পাদনা'}>
        <fieldset disabled={saving} className="flex flex-col gap-3 min-w-0">
          {isNew && <Field label="Network ID *" help="পরে বদলানো যায় না (যেমন: monetag-main)"><input className={inputCls} value={d.id} maxLength={64} autoCapitalize="none" onChange={(e) => set('id', e.target.value)} /></Field>}
          <Field label="নাম *"><input className={inputCls} value={d.name} maxLength={fields.name?.max ?? 64} onChange={(e) => set('name', e.target.value)} /></Field>
          <Field label="Provider *" help="Server-side verification যে Provider-এর জন্য তৈরি, শুধু সেগুলোই বাছা যায়">
            <select className={inputCls} value={d.type} onChange={(e) => set('type', e.target.value)}>
              <option value="">— বাছুন —</option>
              {providers.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="Zone ID" help="Provider ড্যাশবোর্ড থেকে পাওয়া Zone ID"><input className={inputCls} value={d.zone_id} maxLength={64} autoCapitalize="none" onChange={(e) => set('zone_id', e.target.value)} /></Field>
          <Field label="SDK URL" help="https:// দিয়ে শুরু হতে হবে"><input className={inputCls} type="url" inputMode="url" autoCapitalize="none" value={d.sdk_url} maxLength={fields.sdk_url?.max ?? 300} onChange={(e) => set('sdk_url', e.target.value)} /></Field>
          <Field label="Priority (ছোট সংখ্যা আগে)"><input className={inputCls} inputMode="numeric" value={d.priority} onChange={(e) => set('priority', e.target.value)} /></Field>

          <div className="flex flex-col gap-2">
            <span className="text-[12px] font-medium text-[#9CA3AF]">Ad Placement</span>
            {placements.map((p) => (
              <Toggle key={p} label={PLACEMENT_LABEL[p] ?? p} checked={d.placements[p] === true} onChange={(v) => set('placements', { ...d.placements, [p]: v })} />
            ))}
          </div>

          <Field label="প্রয়োজনীয় Ads সংখ্যা (Frequency)" help={`একবার Unlock করতে কতটি Ad দেখতে হবে (${fields.default_ads_required?.min ?? 1}–${fields.default_ads_required?.max ?? 50})`}>
            <input className={inputCls} inputMode="numeric" value={d.default_ads_required} onChange={(e) => set('default_ads_required', e.target.value)} />
          </Field>
          <Field label="Unlock সময়কাল">
            <div className="flex gap-2">
              {d.unlock_unit !== 'lifetime' && <input className={inputCls} inputMode="numeric" placeholder="সংখ্যা" value={d.unlock_value} onChange={(e) => set('unlock_value', e.target.value)} />}
              <select className={`${inputCls} ${d.unlock_unit === 'lifetime' ? '' : '!w-[120px]'}`} value={d.unlock_unit} onChange={(e) => set('unlock_unit', e.target.value as Draft['unlock_unit'])}>
                <option value="hours">ঘণ্টা</option>
                <option value="days">দিন</option>
                <option value="lifetime">Lifetime</option>
              </select>
            </div>
          </Field>
          <Field label="Ad Session Timeout (মিনিট)"><input className={inputCls} inputMode="numeric" value={d.session_timeout_minutes} onChange={(e) => set('session_timeout_minutes', e.target.value)} /></Field>
          <Toggle label="Network চালু" help="চালু করতে Provider-এর সব প্রয়োজনীয় তথ্য থাকতে হবে, নাহলে সার্ভার আটকে দেবে" checked={d.is_enabled} onChange={(v) => set('is_enabled', v)} />
        </fieldset>
        <ErrorBanner message={error} />
        <div className="flex gap-2">
          <button type="button" className="btn-ghost !w-auto px-5" onClick={onCancel} disabled={saving}>বন্ধ করুন</button>
          <Button type="submit" loading={saving} className="flex-1">সংরক্ষণ করুন</Button>
        </div>
      </Card>
    </form>
  )
}

export default function Ads() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'ads.manage')

  const [networks, setNetworks] = useState<Network[]>([])
  const [ready, setReady] = useState<Record<string, Readiness>>({})
  const [fallback, setFallback] = useState<Record<string, string[]>>({})
  const [providers, setProviders] = useState<string[]>([])
  const [placements, setPlacements] = useState<string[]>([])
  const [fields, setFields] = useState<Record<string, FieldSpec> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ draft: Draft; isNew: boolean } | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [sch, list, overview] = await Promise.all([
        loadSchema(),
        adminConfigApi.listAdNetworks() as Promise<{ networks?: Record<string, unknown>[]; available_providers?: string[]; placements?: string[] }>,
        adminConfigApi.adsOverview() as Promise<{ networks?: Readiness[]; fallback_order?: Record<string, string[]> }>,
      ])
      setFields(sch.modules.ads.fields)
      setNetworks((list.networks ?? []).map(toNetwork))
      setProviders(list.available_providers ?? [])
      setPlacements(list.placements ?? [])
      setReady(Object.fromEntries((overview.networks ?? []).map((r) => [r.id, r])))
      setFallback(overview.fallback_order ?? {})
    } catch (e) {
      setError(errorText(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function toggleEnabled(n: Network) {
    setBusyId(n.id)
    try {
      await adminConfigApi.saveAdNetwork(n.id, { is_enabled: !n.is_enabled })
      toast(n.is_enabled ? 'Network বন্ধ করা হয়েছে।' : 'Network চালু হয়েছে।', 'success')
      await load()
    } catch (e) {
      toast(errorText(e), 'error')   // e.g. "Cannot enable: zone_id is required"
    } finally {
      setBusyId(null)
    }
  }

  if (loading && !fields) return <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[96px] rounded-[12px]" />)}</div>
  if (error && !fields) return <ErrorState message={error} onRetry={() => void load()} />
  if (!fields) return null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[16px] font-bold text-white">Ads ম্যানেজমেন্ট</h1>
        {canManage && !editing && (
          <button className="btn-primary !w-auto px-4 !py-2.5 !text-[13px]" onClick={() => setEditing({ draft: toDraft(null, placements, fields), isNew: true })}>+ নতুন Network</button>
        )}
      </div>

      <p className="rounded-[10px] border border-border bg-card px-3 py-2 text-[11.5px] text-[#9CA3AF]">
        Ads-এর Reward শুধু Provider-এর আসল Server-to-Server Callback যাচাই হলেই দেওয়া হয়। এখানের "Ready" মানে শুধু কনফিগারেশন ঠিক আছে — কোনো Ad দেখা বা যাচাই হয়েছে তা নয়।
        Callback Secret সার্ভারের Environment Variable-এ থাকে, এই প্যানেলে দেখা বা বদলানো যায় না।
      </p>

      {editing && (
        <NetworkForm
          key={editing.draft.id || 'new'}
          initial={editing.draft} isNew={editing.isNew} providers={providers} placements={placements} fields={fields}
          onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); void load() }}
        />
      )}

      {networks.length === 0 ? (
        <EmptyState icon="📺" title="কোনো Ad Network নেই" description={canManage ? 'প্রথম Network যোগ করুন (নতুন Network বন্ধ অবস্থায় শুরু হয়)।' : undefined} />
      ) : (
        <ul className="flex flex-col gap-2">
          {networks.map((n) => {
            const r = ready[n.id]
            return (
              <li key={n.id} className="card-base flex flex-col gap-2 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-[13.5px] font-semibold text-white">{n.name || n.id}</div>
                    <div className="mt-0.5 text-[11px] text-[#6B7280]">{n.id} · {n.type || '—'} · priority {n.priority ?? '—'}</div>
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-1">
                    <Badge variant={n.is_enabled ? 'green' : 'gray'}>{n.is_enabled ? 'চালু' : 'বন্ধ'}</Badge>
                    {r && <Badge variant={r.ready ? 'green' : 'orange'}>{r.ready ? 'Ready' : 'Setup বাকি'}</Badge>}
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  {placements.map((p) => <Badge key={p} variant={n.placements[p] ? 'blue' : 'gray'}>{PLACEMENT_LABEL[p] ?? p}</Badge>)}
                </div>
                <div className="text-[11.5px] text-[#9CA3AF]">
                  {n.default_ads_required ?? '—'}টি Ad · Unlock {n.unlock_duration_hours === 0 ? 'Lifetime' : `${n.unlock_duration_hours ?? '—'} ঘণ্টা`} · Session {n.session_timeout_minutes ?? '—'} মিনিট
                </div>
                {r && r.provider_known && (
                  <div className="text-[11.5px] text-[#9CA3AF]">
                    Server verification: {r.supports_s2s ? 'S2S Callback' : 'নেই'} · Secret {r.secret_configured ? 'সেট আছে ✓' : 'সেট নেই ✗'}
                    {r.secret_setting ? ` (${r.secret_setting})` : ''}
                  </div>
                )}
                {r && r.problems.length > 0 && (
                  <ul className="list-disc pl-4 text-[11.5px] text-[#FCD34D]">
                    {r.problems.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                )}
                {canManage && (
                  <div className="flex gap-2">
                    <button className="btn-ghost !py-2 !text-[12px]" onClick={() => setEditing({ draft: toDraft(n, placements, fields), isNew: false })}>এডিট</button>
                    <button className="btn-ghost !py-2 !text-[12px]" disabled={busyId === n.id} onClick={() => void toggleEnabled(n)}>{n.is_enabled ? 'বন্ধ করুন' : 'চালু করুন'}</button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {Object.keys(fallback).length > 0 && (
        <Card title="Placement অনুযায়ী Network ক্রম (Priority অনুসারে)">
          {placements.map((p) => (
            <div key={p} className="flex flex-col gap-0.5">
              <span className="text-[12px] font-medium text-white">{PLACEMENT_LABEL[p] ?? p}</span>
              <span className="text-[12px] text-[#9CA3AF]">{(fallback[p] ?? []).length ? (fallback[p] ?? []).join(' → ') : 'কোনো ব্যবহারযোগ্য Network নেই — এই Placement-এ Ads Unlock কাজ করবে না'}</span>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}
