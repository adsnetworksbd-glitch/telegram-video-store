import { useCallback, useEffect, useRef, useState } from 'react'
import { Badge, Button, EmptyState, ErrorState, FilterChip, LoadMoreButton, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Toggle, inputCls } from '../ui'
import { errorText, fmtCount, fmtDateTime, loadSchema, num, str } from '../util'

const STATUS_LABEL: Record<string, string> = { pending: 'অপেক্ষমাণ', qualifying: 'যাচাই চলছে', rewarded: 'Reward দেওয়া হয়েছে', fraud_detected: 'সন্দেহজনক' }
const STATUS_VARIANT: Record<string, 'blue' | 'green' | 'orange' | 'red' | 'gray'> = { pending: 'gray', qualifying: 'orange', rewarded: 'green', fraud_detected: 'red' }

interface SettingsDraft { enabled: boolean; type: string; amount: string; cooldown: string; validDays: string }

function toDraft(s: Record<string, unknown>): SettingsDraft {
  return {
    enabled: s.referral_enabled === true, type: str(s.referral_reward_type) || 'coupon', amount: String(num(s.referral_reward_amount) ?? ''),
    cooldown: String(num(s.referral_fraud_cooldown_hours) ?? ''), validDays: String(num(s.referral_coupon_valid_days) ?? ''),
  }
}

export default function Referral() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'settings.manage')
  const canViewReferrals = can(admin, 'users.view')

  const [fields, setFields] = useState<Record<string, FieldSpec> | null>(null)
  const [d, setD] = useState<SettingsDraft | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [items, setItems] = useState<AdminRecord[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState<string>('')
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const seq = useRef(0)

  const loadSettings = useCallback(async () => {
    setLoadError(null)
    try {
      const [sch, res] = await Promise.all([loadSchema(), adminConfigApi.referralSettings() as Promise<{ settings: Record<string, unknown> }>])
      setFields(sch.modules.referral.fields)
      setD(toDraft(res.settings))
    } catch (e) {
      setLoadError(errorText(e))
    }
  }, [])

  useEffect(() => { void loadSettings() }, [loadSettings])

  const loadList = useCallback((p: number, replace: boolean) => {
    const my = ++seq.current
    setListLoading(true)
    setListError(null)
    adminConfigApi.referrals({ status: status || undefined, page: p })
      .then((r) => {
        if (my !== seq.current) return
        setItems((prev) => (replace ? r.items : [...prev, ...r.items]))
        setTotal(r.total)
        setHasMore(r.has_more)
        setPage(p)
      })
      .catch((e) => { if (my === seq.current) setListError(errorText(e)) })
      .finally(() => { if (my === seq.current) setListLoading(false) })
  }, [status])

  useEffect(() => { if (canViewReferrals) loadList(1, true) }, [canViewReferrals, loadList])

  if (loadError) return <ErrorState message={loadError} onRetry={() => void loadSettings()} />
  if (!fields || !d) return <div className="flex flex-col gap-2">{[0, 1].map((i) => <Skeleton key={i} className="h-[96px] rounded-[12px]" />)}</div>

  const set = <K extends keyof SettingsDraft>(k: K, v: SettingsDraft[K]) => setD((x) => (x ? { ...x, [k]: v } : x))
  const rewardTypes = fields.referral_reward_type?.options ?? ['coupon']

  async function save() {
    if (!d || saving) return
    const amount = Number(d.amount), cooldown = Number(d.cooldown), validDays = Number(d.validDays)
    const f = fields!
    if (!Number.isFinite(amount) || amount <= (f.referral_reward_amount?.min_exclusive ?? 0) || amount > (f.referral_reward_amount?.max ?? 100000)) { setSaveError(`Reward পরিমাণ ০-র বেশি ও সর্বোচ্চ ${f.referral_reward_amount?.max ?? 100000} হতে হবে।`); return }
    if (!Number.isInteger(cooldown) || cooldown < (f.referral_fraud_cooldown_hours?.min ?? 0) || cooldown > (f.referral_fraud_cooldown_hours?.max ?? 8760)) { setSaveError('Account বয়সের সীমা সঠিক পূর্ণসংখ্যা হতে হবে।'); return }
    if (!Number.isInteger(validDays) || validDays < (f.referral_coupon_valid_days?.min ?? 1) || validDays > (f.referral_coupon_valid_days?.max ?? 365)) { setSaveError('Coupon-এর মেয়াদ সঠিক পূর্ণসংখ্যা (দিন) হতে হবে।'); return }
    setSaving(true)
    setSaveError(null)
    try {
      const res = (await adminConfigApi.saveReferralSettings({
        referral_enabled: d.enabled, referral_reward_type: d.type, referral_reward_amount: amount,
        referral_fraud_cooldown_hours: cooldown, referral_coupon_valid_days: validDays,
      })) as { settings: Record<string, unknown> }
      setD(toDraft(res.settings))
      toast('Referral settings সংরক্ষণ হয়েছে।', 'success')
    } catch (e) {
      setSaveError(errorText(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">Referral ম্যানেজমেন্ট</h1>

      <Card title="Referral সেটিংস">
        <fieldset disabled={!canManage || saving} className="flex flex-col gap-3 min-w-0">
          <Toggle label="Referral প্রোগ্রাম চালু" help="বন্ধ থাকলে নতুন Purchase-এ কোনো Reward তৈরি হবে না" checked={d.enabled} onChange={(v) => set('enabled', v)} />
          <Field label="Reward-এর ধরন">
            <select className={inputCls} value={d.type} onChange={(e) => set('type', e.target.value)}>
              {rewardTypes.map((t) => <option key={t} value={t}>{t === 'coupon' ? 'Coupon (এককালীন)' : t}</option>)}
            </select>
          </Field>
          <Field label="Reward পরিমাণ (BDT)" help="Referrer একবার ব্যবহারযোগ্য এই পরিমাণ ছাড়ের Coupon পাবেন"><input className={inputCls} inputMode="decimal" value={d.amount} onChange={(e) => set('amount', e.target.value)} /></Field>
          <Field label="Reward Coupon-এর মেয়াদ (দিন)"><input className={inputCls} inputMode="numeric" value={d.validDays} onChange={(e) => set('validDays', e.target.value)} /></Field>
          <Field label="Fraud সুরক্ষা: Referred Account-এর ন্যূনতম বয়স (ঘণ্টা)" help="এর চেয়ে নতুন Account প্রথম Purchase করলে Referral সন্দেহজনক চিহ্নিত হবে, Reward দেওয়া হবে না">
            <input className={inputCls} inputMode="numeric" value={d.cooldown} onChange={(e) => set('cooldown', e.target.value)} />
          </Field>
        </fieldset>
        <div className="rounded-[10px] border border-border bg-card px-3 py-2 text-[11.5px] text-[#9CA3AF]">
          <div className="mb-1 font-medium text-white">সার্ভার যা সবসময় প্রয়োগ করে (বদলানো যায় না)</div>
          <ul className="list-disc pl-4">
            <li>Reward শুধু Referred ব্যবহারকারীর সফল Purchase-এর পর দেওয়া হয়।</li>
            <li>নিজেকে Referral করা যায় না।</li>
            <li>একজন ব্যবহারকারীর একটিই Referral রেকর্ড হয় (Duplicate আটকানো)।</li>
            <li>একটি Referral-এ একবারই Reward দেওয়া হয়।</li>
          </ul>
        </div>
        <ErrorBanner message={saveError} />
        {canManage && <Button loading={saving} onClick={() => void save()}>সংরক্ষণ করুন</Button>}
      </Card>

      {canViewReferrals && (
        <section className="flex flex-col gap-2">
          <h2 className="text-[14px] font-bold text-white">Referral তালিকা <span className="text-[12px] font-normal text-[#9CA3AF]">({fmtCount(total)})</span></h2>
          <div className="flex flex-wrap gap-2">
            <FilterChip active={status === ''} onClick={() => setStatus('')}>সব</FilterChip>
            {Object.keys(STATUS_LABEL).map((s) => <FilterChip key={s} active={status === s} onClick={() => setStatus(s)}>{STATUS_LABEL[s]}</FilterChip>)}
          </div>
          {listError && items.length === 0 ? <ErrorState message={listError} onRetry={() => loadList(1, true)} /> : listLoading && items.length === 0 ? (
            <Skeleton className="h-[72px] rounded-[12px]" />
          ) : items.length === 0 ? (
            <EmptyState icon="🤝" title="কোনো Referral নেই" />
          ) : (
            <ul className="flex flex-col gap-2">
              {items.map((r) => (
                <li key={r.id} className="card-base flex flex-col gap-1 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <Badge variant={STATUS_VARIANT[str(r.status)] ?? 'gray'}>{STATUS_LABEL[str(r.status)] ?? str(r.status)}</Badge>
                    <span className="text-[11px] text-[#6B7280]">{fmtDateTime(r.created_at)}</span>
                  </div>
                  <div className="text-[12px] text-[#9CA3AF]">Referrer: <span className="text-white">{str(r.referrer_user_id)}</span></div>
                  <div className="text-[12px] text-[#9CA3AF]">Referred: <span className="text-white">{str(r.referred_user_id)}</span></div>
                  {str(r.status) === 'rewarded' && <div className="text-[11.5px] text-[#6EE7B7]">Reward: {str(r.reward_type) || '—'}{r.reward_amount_bdt ? ` ৳${fmtCount(num(r.reward_amount_bdt))}` : ''} · {fmtDateTime(r.rewarded_at)}</div>}
                </li>
              ))}
            </ul>
          )}
          {hasMore && <LoadMoreButton onClick={() => loadList(page + 1, false)} loading={listLoading} />}
        </section>
      )}
    </div>
  )
}
