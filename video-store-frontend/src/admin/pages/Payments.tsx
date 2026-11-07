import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Badge, Button, EmptyState, ErrorState, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Toggle, inputCls } from '../ui'
import { bool, errorText, loadSchema, num, str } from '../util'

interface Method {
  id: string; name: string; type: string; kind: string; is_enabled: boolean; display_order: number | null
  wallet_address: string; pay_id: string; merchant_name: string; network_name: string; qr_code_url: string
  currency: string; min_amount_usdt: number | null; max_amount_usdt: number | null; payment_timeout_minutes: number | null
  instructions_text: string; auto_verification_supported: boolean; manual_review_supported: boolean
  payable: boolean; problems: string[]
}
interface Binance { configured: boolean; credentials: Record<string, boolean>; missing_settings: string[] }
interface Draft {
  id: string; typeChoice: string; customType: string; name: string; display_order: string
  network_name: string; wallet_address: string; pay_id: string; merchant_name: string; qr_code_url: string
  currency: string; min_amount_usdt: string; max_amount_usdt: string; payment_timeout_minutes: string
  instructions_text: string; auto_verification_supported: boolean; manual_review_supported: boolean; is_enabled: boolean
}

const CUSTOM = '__custom__'
const TYPE_LABEL: Record<string, string> = {
  binance_pay: 'Binance Pay', binance_id: 'Binance ID / Pay ID', usdt_trc20: 'USDT TRC20', usdt_bep20: 'USDT BEP20', usdt_erc20: 'USDT ERC20',
}
const kindOf = (t: string) => (t === 'binance_pay' ? 'gateway' : t === 'binance_id' ? 'pay_id' : t.startsWith('usdt_') ? 'wallet' : 'custom')

const toMethod = (r: Record<string, unknown>): Method => ({
  id: str(r.id), name: str(r.name), type: str(r.type), kind: str(r.kind), is_enabled: bool(r.is_enabled), display_order: num(r.display_order),
  wallet_address: str(r.wallet_address), pay_id: str(r.pay_id), merchant_name: str(r.merchant_name), network_name: str(r.network_name),
  qr_code_url: str(r.qr_code_url), currency: str(r.currency) || 'USDT', min_amount_usdt: num(r.min_amount_usdt), max_amount_usdt: num(r.max_amount_usdt),
  payment_timeout_minutes: num(r.payment_timeout_minutes), instructions_text: str(r.instructions_text),
  auto_verification_supported: bool(r.auto_verification_supported), manual_review_supported: r.manual_review_supported !== false,
  payable: bool(r.payable), problems: Array.isArray(r.problems) ? (r.problems as unknown[]).filter((x): x is string => typeof x === 'string') : [],
})

const blank = (f: Record<string, FieldSpec>): Draft => ({
  id: '', typeChoice: 'binance_pay', customType: '', name: '', display_order: String(num(f.display_order?.default) ?? ''),
  network_name: '', wallet_address: '', pay_id: '', merchant_name: '', qr_code_url: '', currency: 'USDT',
  min_amount_usdt: String(num(f.min_amount_usdt?.default) ?? ''), max_amount_usdt: '',
  payment_timeout_minutes: String(num(f.payment_timeout_minutes?.default) ?? ''), instructions_text: '',
  auto_verification_supported: false, manual_review_supported: true, is_enabled: false,
})

function fromMethod(m: Method, builtin: string[]): Draft {
  const known = builtin.includes(m.type)
  return {
    id: m.id, typeChoice: known ? m.type : CUSTOM, customType: known ? '' : m.type, name: m.name,
    display_order: m.display_order === null ? '' : String(m.display_order), network_name: m.network_name,
    wallet_address: m.kind === 'pay_id' ? '' : m.wallet_address, pay_id: m.pay_id, merchant_name: m.merchant_name, qr_code_url: m.qr_code_url,
    currency: m.currency, min_amount_usdt: m.min_amount_usdt === null ? '' : String(m.min_amount_usdt),
    max_amount_usdt: m.max_amount_usdt === null ? '' : String(m.max_amount_usdt),
    payment_timeout_minutes: m.payment_timeout_minutes === null ? '' : String(m.payment_timeout_minutes),
    instructions_text: m.instructions_text, auto_verification_supported: m.auto_verification_supported,
    manual_review_supported: m.manual_review_supported, is_enabled: m.is_enabled,
  }
}

function MethodForm({ initial, isNew, builtin, fields, binance, onSaved, onCancel }: {
  initial: Draft; isNew: boolean; builtin: string[]; fields: Record<string, FieldSpec>; binance: Binance | null
  onSaved: () => void; onCancel: () => void
}) {
  const [d, setD] = useState<Draft>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))
  const type = d.typeChoice === CUSTOM ? d.customType.trim() : d.typeChoice
  const kind = kindOf(type)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (saving) return
    if (!d.name.trim()) { setError('নাম দিন।'); return }
    if (!type) { setError('Method-এর ধরন দিন।'); return }
    const nz = (v: string) => (v.trim() === '' ? null : v.trim())
    const body: Record<string, unknown> = {
      name: d.name.trim(), type, is_enabled: d.is_enabled, currency: d.currency.trim() || 'USDT',
      network_name: nz(d.network_name), merchant_name: nz(d.merchant_name), qr_code_url: nz(d.qr_code_url),
      instructions_text: nz(d.instructions_text), manual_review_supported: d.manual_review_supported,
      auto_verification_supported: kind === 'gateway' ? d.auto_verification_supported : false,
    }
    if (kind === 'pay_id') { body.pay_id = nz(d.pay_id); body.wallet_address = null } else if (kind !== 'gateway') { body.wallet_address = nz(d.wallet_address); body.pay_id = nz(d.pay_id) }
    const numeric = (key: string, raw: string, label: string, int: boolean, allowEmptyNull: boolean): boolean => {
      if (raw.trim() === '') { if (allowEmptyNull && !isNew) body[key] = null; return true }
      const n = Number(raw)
      if (!Number.isFinite(n) || (int && !Number.isInteger(n))) { setError(`${label} সঠিক সংখ্যা হতে হবে।`); return false }
      body[key] = n
      return true
    }
    if (!numeric('display_order', d.display_order, 'Display order', true, false)) return
    if (!numeric('min_amount_usdt', d.min_amount_usdt, 'ন্যূনতম পরিমাণ', false, false)) return
    if (!numeric('max_amount_usdt', d.max_amount_usdt, 'সর্বোচ্চ পরিমাণ', false, true)) return
    if (!numeric('payment_timeout_minutes', d.payment_timeout_minutes, 'Payment timeout', true, false)) return
    if (isNew && d.id.trim()) body.id = d.id.trim()
    setSaving(true)
    setError(null)
    try {
      if (isNew) await adminConfigApi.createPaymentMethod(body)
      else await adminConfigApi.updatePaymentMethod(d.id, body)
      toast(isNew ? 'Method তৈরি হয়েছে (বন্ধ অবস্থায়)।' : 'সংরক্ষণ হয়েছে।', 'success')
      onSaved()
    } catch (err) {
      setError(errorText(err))
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <Card title={isNew ? 'নতুন Payment Method' : 'Payment Method সম্পাদনা'}>
        <fieldset disabled={saving} className="flex flex-col gap-3 min-w-0">
          {isNew && <Field label="ID (ঐচ্ছিক)" help="a-z, 0-9, _ বা - ; খালি রাখলে নিজে তৈরি হবে। পরে বদলানো যায় না।"><input className={inputCls} value={d.id} maxLength={64} autoCapitalize="none" onChange={(e) => set('id', e.target.value)} /></Field>}
          <Field label="ধরন *">
            <select className={inputCls} value={d.typeChoice} disabled={!isNew} onChange={(e) => set('typeChoice', e.target.value)}>
              {builtin.map((t) => <option key={t} value={t}>{TYPE_LABEL[t] ?? t}</option>)}
              <option value={CUSTOM}>অন্য (Custom)</option>
            </select>
          </Field>
          {d.typeChoice === CUSTOM && (
            <Field label="Custom type slug *" help="যেমন: bkash_usd (a-z, 0-9, _)"><input className={inputCls} value={d.customType} disabled={!isNew} maxLength={32} autoCapitalize="none" onChange={(e) => set('customType', e.target.value)} /></Field>
          )}
          <Field label="নাম *"><input className={inputCls} value={d.name} maxLength={fields.name?.max ?? 80} onChange={(e) => set('name', e.target.value)} /></Field>

          {kind === 'pay_id' && <Field label="Binance ID / Pay ID *" help="৬–২০ সংখ্যা"><input className={inputCls} inputMode="numeric" value={d.pay_id} maxLength={40} onChange={(e) => set('pay_id', e.target.value)} /></Field>}
          {kind === 'wallet' && <Field label="Wallet Address" help="চালু করতে প্রয়োজন; Network-এর ফরম্যাট সার্ভার যাচাই করবে"><input className={inputCls} value={d.wallet_address} maxLength={200} autoCapitalize="none" onChange={(e) => set('wallet_address', e.target.value)} /></Field>}
          {kind === 'custom' && (
            <>
              <Field label="Wallet / Account"><input className={inputCls} value={d.wallet_address} maxLength={200} autoCapitalize="none" onChange={(e) => set('wallet_address', e.target.value)} /></Field>
              <Field label="Pay ID"><input className={inputCls} value={d.pay_id} maxLength={40} onChange={(e) => set('pay_id', e.target.value)} /></Field>
            </>
          )}
          {kind !== 'gateway' && <Field label="Network নাম" help="খালি রাখলে ধরন অনুযায়ী ডিফল্ট দেখাবে"><input className={inputCls} value={d.network_name} maxLength={60} onChange={(e) => set('network_name', e.target.value)} /></Field>}
          <Field label="Merchant নাম"><input className={inputCls} value={d.merchant_name} maxLength={80} onChange={(e) => set('merchant_name', e.target.value)} /></Field>
          <Field label="QR Code URL" help="https:// দিয়ে শুরু হতে হবে"><input className={inputCls} type="url" inputMode="url" autoCapitalize="none" value={d.qr_code_url} maxLength={1000} onChange={(e) => set('qr_code_url', e.target.value)} /></Field>
          <Field label="Payment নির্দেশনা" help={`${d.instructions_text.length} / ${fields.instructions_text?.max ?? 2000}`}>
            <textarea className={`${inputCls} min-h-[84px]`} value={d.instructions_text} maxLength={fields.instructions_text?.max ?? 2000} onChange={(e) => set('instructions_text', e.target.value)} />
          </Field>

          <div className="grid grid-cols-2 gap-2">
            <Field label="ন্যূনতম (USDT)"><input className={inputCls} inputMode="decimal" value={d.min_amount_usdt} onChange={(e) => set('min_amount_usdt', e.target.value)} /></Field>
            <Field label="সর্বোচ্চ (USDT)" help="খালি = সীমা নেই"><input className={inputCls} inputMode="decimal" value={d.max_amount_usdt} onChange={(e) => set('max_amount_usdt', e.target.value)} /></Field>
            <Field label="Currency"><input className={inputCls} value={d.currency} maxLength={10} autoCapitalize="characters" onChange={(e) => set('currency', e.target.value)} /></Field>
            <Field label="Payment timeout (মিনিট)" help={`${fields.payment_timeout_minutes?.min ?? 5} – ${fields.payment_timeout_minutes?.max ?? 1440}`}><input className={inputCls} inputMode="numeric" value={d.payment_timeout_minutes} onChange={(e) => set('payment_timeout_minutes', e.target.value)} /></Field>
          </div>
          <Field label="Display order (ছোট সংখ্যা আগে)"><input className={inputCls} inputMode="numeric" value={d.display_order} onChange={(e) => set('display_order', e.target.value)} /></Field>

          {kind === 'gateway' ? (
            <>
              <Toggle label="Auto Verification (Binance API)" help={binance?.configured ? 'Binance Pay-এর অফিসিয়াল Order Query দিয়ে যাচাই' : 'সতর্কতা: সার্ভারে Binance Credential সম্পূর্ণ নেই — Auto Verification কাজ করবে না'} checked={d.auto_verification_supported} onChange={(v) => set('auto_verification_supported', v)} />
              <Toggle label="Manual Review" help="Auto যাচাই না হলে Admin নিজে দেখে Approve/Reject করবেন" checked={d.manual_review_supported} onChange={(v) => set('manual_review_supported', v)} />
            </>
          ) : (
            <p className="rounded-[10px] border border-border bg-card px-3 py-2 text-[11.5px] text-[#9CA3AF]">এই Method-এর জন্য নির্ভরযোগ্য Auto Verification নেই — সব Payment Admin Manual Review করবেন।</p>
          )}
          <Toggle label="Method চালু" help="অসম্পূর্ণ কনফিগারেশনে সার্ভার চালু করতে দেবে না" checked={d.is_enabled} onChange={(v) => set('is_enabled', v)} />
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

export default function Payments() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'payment_methods.manage')
  const canSweep = can(admin, 'payments.review')

  const [methods, setMethods] = useState<Method[]>([])
  const [builtin, setBuiltin] = useState<string[]>([])
  const [binance, setBinance] = useState<Binance | null>(null)
  const [fields, setFields] = useState<Record<string, FieldSpec> | null>(null)
  const [settingFields, setSettingFields] = useState<Record<string, FieldSpec>>({})
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ draft: Draft; isNew: boolean } | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [savingSettings, setSavingSettings] = useState(false)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [sweeping, setSweeping] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [sch, list, overview] = await Promise.all([
        loadSchema(), adminConfigApi.listPaymentMethods(), adminConfigApi.paymentOverview(),
      ]) as [Awaited<ReturnType<typeof loadSchema>>, { methods?: Record<string, unknown>[]; builtin_types?: string[] }, { binance?: Binance; settings?: Record<string, number>; settings_fields?: Record<string, FieldSpec> }]
      setFields(sch.modules.payments.fields)
      setMethods((list.methods ?? []).map(toMethod))
      setBuiltin(list.builtin_types ?? [])
      setBinance(overview.binance ?? null)
      setSettingFields(overview.settings_fields ?? sch.modules.payments.settings_fields ?? {})
      setSettings(Object.fromEntries(Object.entries(overview.settings ?? {}).map(([k, v]) => [k, String(v)])))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function toggleEnabled(m: Method) {
    setBusyId(m.id)
    try {
      await adminConfigApi.setPaymentMethodEnabled(m.id, !m.is_enabled)
      toast(m.is_enabled ? 'Method বন্ধ করা হয়েছে।' : 'Method চালু হয়েছে।', 'success')
      await load()
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusyId(null)
    }
  }

  async function saveSettings() {
    const body: Record<string, number> = {}
    for (const [k, spec] of Object.entries(settingFields)) {
      const n = Number(settings[k])
      if (settings[k] === '' || !Number.isInteger(n) || n < (spec.min ?? 0) || n > (spec.max ?? 1_000_000)) {
        setSettingsError(`${spec.label}: ${spec.min ?? 0}–${spec.max} এর মধ্যে পূর্ণসংখ্যা দিন।`)
        return
      }
      body[k] = n
    }
    setSavingSettings(true)
    setSettingsError(null)
    try {
      await adminConfigApi.savePaymentSettings(body)
      toast('Verification settings সংরক্ষণ হয়েছে।', 'success')
    } catch (e) {
      setSettingsError(errorText(e))
    } finally {
      setSavingSettings(false)
    }
  }

  async function sweep() {
    setSweeping(true)
    try {
      const r = await adminConfigApi.expireStaleOrders()
      toast(`${r.scanned}টি দেখা হয়েছে, ${r.expired}টি মেয়াদোত্তীর্ণ চিহ্নিত।`, 'success')
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setSweeping(false)
    }
  }

  if (loading && !fields) return <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[96px] rounded-[12px]" />)}</div>
  if (error && !fields) return <ErrorState message={error} onRetry={() => void load()} />
  if (!fields) return null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[16px] font-bold text-white">Payment ম্যানেজমেন্ট</h1>
        {canManage && !editing && (
          <button className="btn-primary !w-auto px-4 !py-2.5 !text-[13px]" onClick={() => setEditing({ draft: blank(fields), isNew: true })}>+ নতুন Method</button>
        )}
      </div>

      <Card title="Binance Auto Verification">
        <div className="flex flex-wrap gap-1.5">
          <Badge variant={binance?.configured ? 'green' : 'orange'}>{binance?.configured ? 'Credential সম্পূর্ণ' : 'Credential অসম্পূর্ণ'}</Badge>
          {binance && Object.entries(binance.credentials).map(([k, ok]) => <Badge key={k} variant={ok ? 'green' : 'red'}>{k} {ok ? '✓' : '✗'}</Badge>)}
        </div>
        <p className="text-[11.5px] text-[#9CA3AF]">
          Binance API Key/Secret সার্ভারের Environment Variable-এ থাকে — এই প্যানেলে সংরক্ষণ বা প্রদর্শন করা হয় না।
          {binance && binance.missing_settings.length > 0 && <> অনুপস্থিত: {binance.missing_settings.join(', ')}। Credential না থাকলে Payment Manual Review-তে যাবে।</>}
          {' '}Wallet / Pay ID Method সবসময় Manual Review।
        </p>
      </Card>

      {editing && (
        <MethodForm
          key={editing.draft.id || 'new'}
          initial={editing.draft} isNew={editing.isNew} builtin={builtin} fields={fields} binance={binance}
          onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); void load() }}
        />
      )}

      {methods.length === 0 ? (
        <EmptyState icon="💳" title="কোনো Payment Method নেই" description={canManage ? 'প্রথম Method যোগ করুন (নতুন Method বন্ধ অবস্থায় শুরু হয়)।' : undefined} />
      ) : (
        <ul className="flex flex-col gap-2">
          {methods.map((m) => (
            <li key={m.id} className="card-base flex flex-col gap-2 p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] font-semibold text-white">{m.name}</div>
                  <div className="mt-0.5 text-[11px] text-[#6B7280]">{m.id} · {TYPE_LABEL[m.type] ?? m.type} · order {m.display_order ?? '—'}</div>
                </div>
                <div className="flex shrink-0 flex-wrap justify-end gap-1">
                  <Badge variant={m.is_enabled ? 'green' : 'gray'}>{m.is_enabled ? 'চালু' : 'বন্ধ'}</Badge>
                  <Badge variant={m.auto_verification_supported ? 'purple' : 'blue'}>{m.auto_verification_supported ? 'Auto' : 'Manual'}</Badge>
                  {m.is_enabled && !m.payable && <Badge variant="red">ব্যবহারকারী পাবে না</Badge>}
                </div>
              </div>
              <div className="text-[11.5px] text-[#9CA3AF]">
                {m.kind === 'gateway' ? 'Binance Checkout' : (m.pay_id || m.wallet_address) ? `${m.network_name || ''} · ${(m.pay_id || m.wallet_address).slice(0, 14)}…` : 'ঠিকানা সেট নেই'}
                {` · ${m.min_amount_usdt ?? '—'}–${m.max_amount_usdt ?? '∞'} ${m.currency} · ${m.payment_timeout_minutes ?? '—'} মিনিট`}
              </div>
              {m.problems.length > 0 && <ul className="list-disc pl-4 text-[11.5px] text-[#FCD34D]">{m.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>}
              {canManage && (
                <div className="flex gap-2">
                  <button className="btn-ghost !py-2 !text-[12px]" onClick={() => setEditing({ draft: fromMethod(m, builtin), isNew: false })}>এডিট</button>
                  <button className="btn-ghost !py-2 !text-[12px]" disabled={busyId === m.id} onClick={() => void toggleEnabled(m)}>{m.is_enabled ? 'বন্ধ করুন' : 'চালু করুন'}</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <Card title="Verification Settings">
        <fieldset disabled={!canManage || savingSettings} className="flex flex-col gap-3 min-w-0">
          {Object.entries(settingFields).map(([k, spec]) => (
            <Field key={k} label={spec.label} help={`${spec.min ?? 0} – ${spec.max}`}>
              <input className={inputCls} inputMode="numeric" value={settings[k] ?? ''} onChange={(e) => setSettings((s) => ({ ...s, [k]: e.target.value }))} />
            </Field>
          ))}
        </fieldset>
        <ErrorBanner message={settingsError} />
        {canManage && <Button loading={savingSettings} onClick={() => void saveSettings()}>সংরক্ষণ করুন</Button>}
      </Card>

      {canSweep && (
        <Card title="মেয়াদোত্তীর্ণ Order">
          <p className="text-[11.5px] text-[#9CA3AF]">সময় পেরিয়ে যাওয়া অপরিশোধিত Order-গুলো "expired" হিসেবে সংরক্ষণ করে। Review-এ পাঠানো Order ছোঁয়া হয় না।</p>
          <Button variant="ghost" loading={sweeping} onClick={() => void sweep()}>এখনই সাফ করুন</Button>
        </Card>
      )}
    </div>
  )
}
