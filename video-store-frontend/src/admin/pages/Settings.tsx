import { useCallback, useEffect, useState } from 'react'
import { Button, ConfirmSheet, ErrorState, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Toggle, inputCls } from '../ui'
import { errorText, num, str } from '../util'

interface Draft {
  app_name: string; app_logo_url: string; maintenance_mode: boolean; maintenance_message: string; currency_display: string
  usdt_to_bdt_rate: string; wallet_enabled: boolean; terms_url: string; privacy_url: string; support_url: string
  support_username: string; telegram_bot_username: string
}
const NULLABLE: Array<keyof Draft> = ['app_logo_url', 'terms_url', 'privacy_url', 'support_url', 'support_username']

function toDraft(s: Record<string, unknown>): Draft {
  return {
    app_name: str(s.app_name), app_logo_url: str(s.app_logo_url), maintenance_mode: s.maintenance_mode === true,
    maintenance_message: str(s.maintenance_message), currency_display: str(s.currency_display),
    usdt_to_bdt_rate: String(num(s.usdt_to_bdt_rate) ?? ''), wallet_enabled: s.wallet_enabled === true,
    terms_url: str(s.terms_url), privacy_url: str(s.privacy_url), support_url: str(s.support_url),
    support_username: str(s.support_username), telegram_bot_username: str(s.telegram_bot_username),
  }
}

export default function Settings() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'settings.manage')
  const [fields, setFields] = useState<Record<string, FieldSpec> | null>(null)
  const [saved, setSaved] = useState<Draft | null>(null)
  const [d, setD] = useState<Draft | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirmMaint, setConfirmMaint] = useState(false)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const r = (await adminConfigApi.appSettings()) as { settings: Record<string, unknown>; fields: Record<string, FieldSpec> }
      setFields(r.fields); setSaved(toDraft(r.settings)); setD(toDraft(r.settings))
    } catch (e) { setLoadError(errorText(e)) }
  }, [])
  useEffect(() => { void load() }, [load])

  if (loadError) return <ErrorState message={loadError} onRetry={() => void load()} />
  if (!fields || !d || !saved) return <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[96px] rounded-[12px]" />)}</div>

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => (x ? { ...x, [k]: v } : x))

  function build(): Record<string, unknown> | string {
    const f = fields!
    const rate = Number(d!.usdt_to_bdt_rate)
    if (!d!.app_name.trim()) return 'App-এর নাম দিন।'
    if (!Number.isFinite(rate) || rate <= 0 || rate > (f.usdt_to_bdt_rate?.max ?? 10000)) return 'USDT → BDT রেট সঠিক ধনাত্মক সংখ্যা হতে হবে।'
    const out: Record<string, unknown> = {}
    for (const k of Object.keys(d!) as Array<keyof Draft>) {
      const cur = d![k]
      if (cur === saved![k]) continue                                   // send only what changed
      if (k === 'usdt_to_bdt_rate') out[k] = rate
      else if (typeof cur === 'string') out[k] = NULLABLE.includes(k) && !cur.trim() ? null : cur.trim()
      else out[k] = cur
    }
    for (const k of ['app_logo_url', 'terms_url', 'privacy_url', 'support_url'] as const) {
      const v = out[k]
      if (typeof v === 'string' && !v.startsWith('https://')) return `${f[k]?.label ?? k} অবশ্যই https:// দিয়ে শুরু হতে হবে।`
    }
    return Object.keys(out).length ? out : 'কোনো পরিবর্তন নেই।'
  }

  async function save() {
    const body = build()
    if (typeof body === 'string') { setErr(body); setConfirmMaint(false); return }
    setSaving(true); setErr(null)
    try {
      const r = (await adminConfigApi.saveAppSettings(body)) as { settings: Record<string, unknown> }
      setSaved(toDraft(r.settings)); setD(toDraft(r.settings))
      toast('সেটিংস সংরক্ষণ হয়েছে।', 'success')
    } catch (e) { setErr(errorText(e)) } finally { setSaving(false); setConfirmMaint(false) }
  }

  const turningOn = d.maintenance_mode && !saved.maintenance_mode

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">অ্যাপ সেটিংস</h1>
      <fieldset disabled={!canManage || saving} className="flex flex-col gap-3 min-w-0">
        <Card title="Maintenance Mode">
          <Toggle label="Maintenance Mode চালু" help="চালু থাকলে Mini App-এ Maintenance স্ক্রিন দেখাবে এবং সার্ভার নতুন Order / Ad Session নেবে না। Admin Panel চালু থাকবে।" checked={d.maintenance_mode} onChange={(v) => set('maintenance_mode', v)} />
          <Field label="ব্যবহারকারীকে দেখানো বার্তা"><textarea className={inputCls} rows={2} maxLength={maxOf(fields, 'maintenance_message', 500)} value={d.maintenance_message} onChange={(e) => set('maintenance_message', e.target.value)} /></Field>
        </Card>
        <Card title="সাধারণ">
          <Field label="App-এর নাম"><input className={inputCls} maxLength={60} value={d.app_name} onChange={(e) => set('app_name', e.target.value)} /></Field>
          <Field label="Logo URL (https)"><input className={inputCls} value={d.app_logo_url} onChange={(e) => set('app_logo_url', e.target.value)} /></Field>
          <Field label="দাম দেখানোর মুদ্রা"><input className={inputCls} maxLength={10} value={d.currency_display} onChange={(e) => set('currency_display', e.target.value)} /></Field>
          <Field label="USDT → BDT রেট" help="শুধু নতুন Order-এ প্রযোজ্য; আগের Order-এর রেট বদলায় না"><input className={inputCls} inputMode="decimal" value={d.usdt_to_bdt_rate} onChange={(e) => set('usdt_to_bdt_rate', e.target.value)} /></Field>
          <Toggle label="Wallet চালু" checked={d.wallet_enabled} onChange={(v) => set('wallet_enabled', v)} />
          <Field label="Bot Username (@ ছাড়া)"><input className={inputCls} maxLength={32} value={d.telegram_bot_username} onChange={(e) => set('telegram_bot_username', e.target.value)} /></Field>
        </Card>
        <Card title="Terms, Privacy ও Support লিংক">
          <Field label="Terms & Conditions URL (https)"><input className={inputCls} value={d.terms_url} onChange={(e) => set('terms_url', e.target.value)} /></Field>
          <Field label="Privacy Policy URL (https)"><input className={inputCls} value={d.privacy_url} onChange={(e) => set('privacy_url', e.target.value)} /></Field>
          <Field label="Support URL (https)"><input className={inputCls} value={d.support_url} onChange={(e) => set('support_url', e.target.value)} /></Field>
          <Field label="Support Telegram Username (@ ছাড়া)"><input className={inputCls} maxLength={32} value={d.support_username} onChange={(e) => set('support_username', e.target.value)} /></Field>
          <p className="text-[11px] text-[#6B7280]">ফাঁকা রাখলে সেই লিংক Support পেজ থেকে সরে যাবে।</p>
        </Card>
      </fieldset>
      <ErrorBanner message={err} />
      {canManage && <Button loading={saving} onClick={() => (turningOn ? setConfirmMaint(true) : void save())}>সংরক্ষণ করুন</Button>}
      <ConfirmSheet open={confirmMaint} title="Maintenance Mode চালু করবেন?" confirmLabel="চালু করুন" loading={saving} onConfirm={() => void save()} onCancel={() => setConfirmMaint(false)}>
        <p className="text-[12px] text-[#9CA3AF]">চালু করলে ব্যবহারকারীরা নতুন কিছু কিনতে বা Ads দেখে Unlock করতে পারবেন না। আগে কেনা Access বহাল থাকবে।</p>
      </ConfirmSheet>
    </div>
  )
}

function maxOf(fields: Record<string, FieldSpec>, key: string, fallback: number): number {
  return fields[key]?.max ?? fallback
}
