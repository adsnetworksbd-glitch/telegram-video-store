import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Badge, Button, EmptyState, ErrorState, FilterChip, LoadMoreButton, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Toggle, inputCls } from '../ui'
import { bool, errorText, fmtCount, fmtDateTime, loadSchema, num, str } from '../util'

const LIMIT = 20
type Filter = 'all' | 'active' | 'inactive'
type Target = { id: string; title: string }

interface Draft {
  id: string; code: string; description: string; discount_type: string; discount_value: string; max_discount_bdt: string
  min_order_bdt: string; usage_limit: string; per_user_limit: string; applicable_to: string; targets: Target[]
  valid_from: string; valid_until: string; is_active: boolean
}

function toLocalInput(v: unknown): string {
  if (typeof v !== 'string' || !v) return ''
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
const fromLocalInput = (v: string): string | null => {
  if (!v) return null
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}
const numStr = (v: unknown) => (num(v) === null ? '' : String(num(v)))

const blank = (f: Record<string, FieldSpec>): Draft => ({
  id: '', code: '', description: '', discount_type: 'percentage', discount_value: '', max_discount_bdt: '',
  min_order_bdt: String(num(f.min_order_bdt?.default) ?? 0), usage_limit: '', per_user_limit: String(num(f.per_user_limit?.default) ?? 1),
  applicable_to: 'all', targets: [], valid_from: '', valid_until: '', is_active: false,
})

const fromRecord = (c: AdminRecord): Draft => ({
  id: c.id, code: str(c.code), description: str(c.description), discount_type: str(c.discount_type) || 'percentage',
  discount_value: numStr(c.discount_value), max_discount_bdt: numStr(c.max_discount_bdt), min_order_bdt: numStr(c.min_order_bdt),
  usage_limit: numStr(c.usage_limit), per_user_limit: numStr(c.per_user_limit), applicable_to: str(c.applicable_to) || 'all',
  targets: (Array.isArray(c.applicable_ids) ? (c.applicable_ids as unknown[]) : []).filter((x): x is string => typeof x === 'string').map((id) => ({ id, title: id })),
  valid_from: toLocalInput(c.valid_from), valid_until: toLocalInput(c.valid_until), is_active: bool(c.is_active),
})

/** Search + add the videos or packages a coupon applies to. */
function TargetPicker({ kind, selected, max, onAdd }: { kind: 'videos' | 'packages'; selected: string[]; max: number; onAdd: (t: Target) => void }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<AdminRecord[]>([])
  const [err, setErr] = useState<string | null>(null)
  const seq = useRef(0)
  const nameKey = kind === 'videos' ? 'title' : 'name'

  useEffect(() => {
    const term = q.trim()
    if (!term) { setResults([]); setErr(null); return }
    const t = setTimeout(() => {
      const my = ++seq.current
      const req = kind === 'videos'
        ? adminConfigApi.list('/admin/videos', { q: term, limit: 8 })
        : adminConfigApi.list('/admin/packages', { limit: 50 }).then((r) => ({ ...r, items: r.items.filter((p) => (str(p.name) + p.id).toLowerCase().includes(term.toLowerCase())).slice(0, 8) }))
      req.then((r) => { if (my === seq.current) setResults(r.items) }).catch((e) => { if (my === seq.current) setErr(errorText(e)) })
    }, 400)
    return () => clearTimeout(t)
  }, [q, kind])

  const full = selected.length >= max
  return (
    <div className="flex flex-col gap-2">
      <input className={inputCls} type="search" placeholder={kind === 'videos' ? 'ভিডিও খুঁজুন (টাইটেল / ID)' : 'প্যাকেজ খুঁজুন (নাম / ID)'} value={q} maxLength={100} disabled={full} onChange={(e) => setQ(e.target.value)} />
      <ErrorBanner message={err} />
      {results.map((r) => (
        <div key={r.id} className="flex items-center gap-2 rounded-[10px] border border-border bg-card p-1.5">
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-white">{str(r[nameKey]) || r.id}</span>
          <button type="button" className="btn-ghost !w-auto px-3 !py-1.5 !text-[12px]" disabled={selected.includes(r.id) || full}
            onClick={() => onAdd({ id: r.id, title: str(r[nameKey]) || r.id })}>{selected.includes(r.id) ? 'যোগ আছে' : '+ যোগ'}</button>
        </div>
      ))}
    </div>
  )
}

function CouponForm({ initial, isNew, fields, onSaved, onCancel }: {
  initial: Draft; isNew: boolean; fields: Record<string, FieldSpec>; onSaved: () => void; onCancel: () => void
}) {
  const [d, setD] = useState<Draft>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))
  const maxIds = fields.applicable_ids?.max ?? 100
  const discountTypes = fields.discount_type?.options ?? ['fixed_bdt', 'percentage']
  const applicable = fields.applicable_to?.options ?? ['all', 'videos', 'packages']

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (saving) return
    const code = d.code.trim().toUpperCase()
    if (isNew && !/^[A-Z0-9][A-Z0-9_-]{2,31}$/.test(code)) { setError('Code ৩–৩২ অক্ষরের হতে হবে: A-Z, 0-9, _ বা -'); return }
    const val = Number(d.discount_value)
    if (!Number.isFinite(val) || val <= 0) { setError('ছাড়ের পরিমাণ ০-র বেশি হতে হবে।'); return }
    if (d.discount_type === 'percentage' && val > 100) { setError('শতাংশ ছাড় ১০০-র বেশি হতে পারে না।'); return }
    if (d.applicable_to !== 'all' && d.targets.length === 0) { setError('কোন ভিডিও/প্যাকেজে কার্যকর হবে তা যোগ করুন।'); return }
    const vf = fromLocalInput(d.valid_from), vu = fromLocalInput(d.valid_until)
    if (vf && vu && new Date(vu) <= new Date(vf)) { setError('শেষ সময় শুরুর সময়ের পরে হতে হবে।'); return }
    const optNum = (raw: string, label: string, int = false): number | null | undefined => {
      if (raw.trim() === '') return null
      const n = Number(raw)
      if (!Number.isFinite(n) || n < 0 || (int && !Number.isInteger(n))) { setError(`${label} সঠিক সংখ্যা হতে হবে।`); return undefined }
      return n
    }
    const maxDisc = optNum(d.max_discount_bdt, 'সর্বোচ্চ ছাড়')
    const minOrder = optNum(d.min_order_bdt, 'ন্যূনতম Order')
    const usage = optNum(d.usage_limit, 'মোট ব্যবহার সীমা', true)
    const perUser = optNum(d.per_user_limit, 'প্রতি ব্যবহারকারী সীমা', true)
    if (maxDisc === undefined || minOrder === undefined || usage === undefined || perUser === undefined) return
    const body: Record<string, unknown> = {
      description: d.description.trim() || null, discount_type: d.discount_type, discount_value: val,
      max_discount_bdt: d.discount_type === 'percentage' ? maxDisc : null,
      min_order_bdt: minOrder ?? 0, usage_limit: usage, per_user_limit: perUser ?? 1,
      applicable_to: d.applicable_to, applicable_ids: d.applicable_to === 'all' ? [] : d.targets.map((t) => t.id),
      valid_from: vf, valid_until: vu, is_active: d.is_active,
    }
    if (isNew) {
      body.code = code
      // creating: omit nulls the server treats as "not sent"
      for (const k of Object.keys(body)) if (body[k] === null) delete body[k]
    }
    setSaving(true)
    setError(null)
    try {
      if (isNew) await adminConfigApi.create('/admin/coupons', body)
      else await adminConfigApi.update('/admin/coupons', d.id, body)
      toast(isNew ? 'Coupon তৈরি হয়েছে।' : 'সংরক্ষণ হয়েছে।', 'success')
      onSaved()
    } catch (err) {
      setError(errorText(err))
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <Card title={isNew ? 'নতুন Coupon' : 'Coupon সম্পাদনা'}>
        <fieldset disabled={saving} className="flex flex-col gap-3 min-w-0">
          <Field label="Code *" help={isNew ? 'ইংরেজি বড় হাতের অক্ষর/সংখ্যা। পরে বদলানো যায় না।' : 'Code বদলানো যায় না'}>
            <input className={inputCls} value={d.code} disabled={!isNew} maxLength={32} autoCapitalize="characters" onChange={(e) => set('code', e.target.value.toUpperCase())} />
          </Field>
          <Field label="অভ্যন্তরীণ নোট"><input className={inputCls} value={d.description} maxLength={fields.description?.max ?? 300} onChange={(e) => set('description', e.target.value)} /></Field>
          <div className="grid grid-cols-2 gap-2">
            {discountTypes.map((t) => (
              <button key={t} type="button" onClick={() => set('discount_type', t)}
                className={`rounded-[12px] border px-3 py-2.5 text-[13px] font-medium ${d.discount_type === t ? 'border-primary bg-primary/15 text-primary-light' : 'border-border bg-card text-[#9CA3AF]'}`}>
                {t === 'percentage' ? 'শতাংশ (%)' : 'নির্দিষ্ট (৳)'}
              </button>
            ))}
          </div>
          <Field label={d.discount_type === 'percentage' ? 'ছাড় (১–১০০ %) *' : 'ছাড় (BDT) *'}><input className={inputCls} inputMode="decimal" value={d.discount_value} onChange={(e) => set('discount_value', e.target.value)} /></Field>
          {d.discount_type === 'percentage' && (
            <Field label="সর্বোচ্চ ছাড় (BDT)" help="খালি = সীমা নেই"><input className={inputCls} inputMode="decimal" value={d.max_discount_bdt} onChange={(e) => set('max_discount_bdt', e.target.value)} /></Field>
          )}
          <Field label="ন্যূনতম Order (BDT)"><input className={inputCls} inputMode="decimal" value={d.min_order_bdt} onChange={(e) => set('min_order_bdt', e.target.value)} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="মোট ব্যবহার সীমা" help="খালি = সীমাহীন"><input className={inputCls} inputMode="numeric" value={d.usage_limit} onChange={(e) => set('usage_limit', e.target.value)} /></Field>
            <Field label="প্রতি ব্যবহারকারী"><input className={inputCls} inputMode="numeric" value={d.per_user_limit} onChange={(e) => set('per_user_limit', e.target.value)} /></Field>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Field label="শুরু (ঐচ্ছিক)"><input className={inputCls} type="datetime-local" value={d.valid_from} onChange={(e) => set('valid_from', e.target.value)} /></Field>
            <Field label="মেয়াদ শেষ (ঐচ্ছিক)"><input className={inputCls} type="datetime-local" value={d.valid_until} onChange={(e) => set('valid_until', e.target.value)} /></Field>
          </div>
          <Field label="কোথায় কার্যকর">
            <select className={inputCls} value={d.applicable_to} onChange={(e) => setD((x) => ({ ...x, applicable_to: e.target.value, targets: [] }))}>
              {applicable.map((a) => <option key={a} value={a}>{({ all: 'সব ভিডিও ও প্যাকেজ', videos: 'নির্দিষ্ট ভিডিও', packages: 'নির্দিষ্ট প্যাকেজ' } as Record<string, string>)[a] ?? a}</option>)}
            </select>
          </Field>
          {d.applicable_to !== 'all' && (
            <div className="flex flex-col gap-2">
              <span className="text-[12px] font-medium text-[#9CA3AF]">নির্বাচিত ({d.targets.length}/{maxIds})</span>
              {d.targets.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {d.targets.map((t) => (
                    <span key={t.id} className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2.5 py-1 text-[11.5px] text-white">
                      {t.title}
                      <button type="button" aria-label="সরান" className="text-[#FCA5A5]" onClick={() => set('targets', d.targets.filter((x) => x.id !== t.id))}>✕</button>
                    </span>
                  ))}
                </div>
              )}
              <TargetPicker kind={d.applicable_to === 'videos' ? 'videos' : 'packages'} selected={d.targets.map((t) => t.id)} max={maxIds} onAdd={(t) => set('targets', [...d.targets, t])} />
            </div>
          )}
          <Toggle label="Coupon চালু" help="নতুন Coupon বন্ধ অবস্থায় শুরু হয়" checked={d.is_active} onChange={(v) => set('is_active', v)} />
        </fieldset>
        <ErrorBanner message={error} />
        <div className="flex gap-2">
          <button type="button" className="btn-ghost !w-auto px-5" onClick={onCancel} disabled={saving}>বন্ধ করুন</button>
          <Button type="submit" loading={saving} className="flex-1">{isNew ? 'তৈরি করুন' : 'সংরক্ষণ করুন'}</Button>
        </div>
      </Card>
    </form>
  )
}

function Usage({ id }: { id: string }) {
  const [rows, setRows] = useState<AdminRecord[]>([])
  const [page, setPage] = useState(1)
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback((p: number) => {
    setLoading(true)
    setError(null)
    adminConfigApi.couponUsage(id, p)
      .then((r) => { setRows((prev) => (p === 1 ? r.items : [...prev, ...r.items])); setMore(r.has_more); setPage(p) })
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => { load(1) }, [load])

  return (
    <div className="flex flex-col gap-1.5 border-t border-border pt-2">
      <ErrorBanner message={error} />
      {loading && rows.length === 0 ? <Skeleton className="h-[40px] rounded-[10px]" /> : rows.length === 0 && !error ? (
        <p className="text-[12px] text-[#9CA3AF]">এখনো কেউ ব্যবহার করেনি।</p>
      ) : rows.map((r, i) => (
        <div key={i} className="flex items-center justify-between gap-2 text-[11.5px] text-[#9CA3AF]">
          <span className="truncate">{str(r.user_id)} · {str(r.order_id).slice(0, 12)}</span>
          <span className="shrink-0">৳{fmtCount(num(r.discount_applied_bdt))} · {fmtDateTime(r.used_at)}</span>
        </div>
      ))}
      {more && <LoadMoreButton onClick={() => load(page + 1)} loading={loading} />}
    </div>
  )
}

export default function Coupons() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'coupons.manage')

  const [items, setItems] = useState<AdminRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [fields, setFields] = useState<Record<string, FieldSpec> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ draft: Draft; isNew: boolean } | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [usageId, setUsageId] = useState<string | null>(null)
  const seq = useRef(0)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 400)
    return () => clearTimeout(t)
  }, [query])

  const load = useCallback((p: number, replace: boolean) => {
    const my = ++seq.current
    setLoading(true)
    setError(null)
    Promise.all([
      loadSchema(),
      adminConfigApi.list('/admin/coupons', { q: debounced || undefined, active: filter === 'all' ? undefined : filter === 'active', page: p, limit: LIMIT }),
    ])
      .then(([sch, r]) => {
        if (my !== seq.current) return
        setFields(sch.modules.coupons.fields)
        setItems((prev) => (replace ? r.items : [...prev, ...r.items]))
        setTotal(r.total)
        setHasMore(r.has_more)
        setPage(p)
      })
      .catch((e) => { if (my === seq.current) setError(errorText(e)) })
      .finally(() => { if (my === seq.current) setLoading(false) })
  }, [debounced, filter])

  useEffect(() => { load(1, true) }, [load])

  async function toggleActive(c: AdminRecord) {
    setBusyId(c.id)
    try {
      const updated = await adminConfigApi.setCouponActive(c.id, !bool(c.is_active))
      setItems((prev) => prev.map((x) => (x.id === c.id ? { ...x, ...updated } : x)))
      toast(bool(updated.is_active) ? 'Coupon চালু হয়েছে।' : 'Coupon বন্ধ করা হয়েছে।', 'success')
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusyId(null)
    }
  }

  async function openEdit(c: AdminRecord) {
    // Resolve readable names for the targeted videos / packages (best effort; falls back to the ID).
    const draft = fromRecord(c)
    const base = draft.applicable_to === 'videos' ? '/admin/videos' : draft.applicable_to === 'packages' ? '/admin/packages' : null
    if (base) {
      draft.targets = await Promise.all(draft.targets.map(async (t) => {
        try {
          const r = await adminConfigApi.get(base, t.id)
          return { id: t.id, title: str(r.title) || str(r.name) || t.id }
        } catch { return t }
      }))
    }
    setEditing({ draft, isNew: false })
  }

  if (loading && !fields) return <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[84px] rounded-[12px]" />)}</div>
  if (error && !fields) return <ErrorState message={error} onRetry={() => load(1, true)} />
  if (!fields) return null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[16px] font-bold text-white">Coupon <span className="text-[12px] font-normal text-[#9CA3AF]">({fmtCount(total)})</span></h1>
        {canManage && !editing && <button className="btn-primary !w-auto px-4 !py-2.5 !text-[13px]" onClick={() => setEditing({ draft: blank(fields), isNew: true })}>+ নতুন Coupon</button>}
      </div>

      {editing && (
        <CouponForm key={editing.draft.id || 'new'} initial={editing.draft} isNew={editing.isNew} fields={fields}
          onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); load(1, true) }} />
      )}

      <input className={inputCls} type="search" placeholder="Code দিয়ে খুঁজুন" value={query} maxLength={40} onChange={(e) => setQuery(e.target.value)} />
      <div className="flex gap-2">
        <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>সব</FilterChip>
        <FilterChip active={filter === 'active'} onClick={() => setFilter('active')}>চালু</FilterChip>
        <FilterChip active={filter === 'inactive'} onClick={() => setFilter('inactive')}>বন্ধ</FilterChip>
      </div>

      {error && items.length === 0 ? <ErrorState message={error} onRetry={() => load(1, true)} /> : items.length === 0 && !loading ? (
        <EmptyState icon="🏷️" title="কোনো Coupon নেই" description={debounced || filter !== 'all' ? 'ফিল্টার বদলে দেখুন।' : canManage ? 'প্রথম Coupon তৈরি করুন।' : undefined} />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((c) => {
            const active = bool(c.is_active)
            const pct = str(c.discount_type) === 'percentage'
            const until = str(c.valid_until) ? new Date(str(c.valid_until)) : null
            const expired = until !== null && until.getTime() < Date.now()
            const limit = num(c.usage_limit)
            return (
              <li key={c.id} className="card-base flex flex-col gap-2 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate font-mono text-[14px] font-bold text-white">{str(c.code)}</div>
                    <div className="mt-0.5 text-[11.5px] text-[#9CA3AF]">
                      {pct ? `${fmtCount(num(c.discount_value))}% ছাড়${num(c.max_discount_bdt) ? ` (সর্বোচ্চ ৳${fmtCount(num(c.max_discount_bdt))})` : ''}` : `৳${fmtCount(num(c.discount_value))} ছাড়`}
                      {num(c.min_order_bdt) ? ` · ন্যূনতম ৳${fmtCount(num(c.min_order_bdt))}` : ''}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-1">
                    <Badge variant={active ? 'green' : 'gray'}>{active ? 'চালু' : 'বন্ধ'}</Badge>
                    {expired && <Badge variant="red">মেয়াদ শেষ</Badge>}
                    {str(c.type) && str(c.type) !== 'admin' && <Badge variant="purple">{str(c.type)}</Badge>}
                  </div>
                </div>
                <div className="text-[11.5px] text-[#6B7280]">
                  ব্যবহার {fmtCount(num(c.used_count))}{limit ? ` / ${fmtCount(limit)}` : ' (সীমাহীন)'} · প্রতি ইউজার {fmtCount(num(c.per_user_limit))} ·{' '}
                  {str(c.applicable_to) === 'videos' ? 'নির্দিষ্ট ভিডিও' : str(c.applicable_to) === 'packages' ? 'নির্দিষ্ট প্যাকেজ' : 'সব কনটেন্ট'}
                  {until ? ` · শেষ ${fmtDateTime(c.valid_until)}` : ''}
                </div>
                <div className="flex gap-2">
                  {canManage && <button className="btn-ghost !py-2 !text-[12px]" onClick={() => void openEdit(c)}>এডিট</button>}
                  {canManage && <button className="btn-ghost !py-2 !text-[12px]" disabled={busyId === c.id} onClick={() => void toggleActive(c)}>{active ? 'বন্ধ করুন' : 'চালু করুন'}</button>}
                  <button className="btn-ghost !py-2 !text-[12px]" onClick={() => setUsageId((u) => (u === c.id ? null : c.id))}>{usageId === c.id ? 'ব্যবহার লুকান' : 'ব্যবহার'}</button>
                </div>
                {usageId === c.id && <Usage id={c.id} />}
              </li>
            )
          })}
        </ul>
      )}
      {hasMore && <LoadMoreButton onClick={() => load(page + 1, false)} loading={loading} />}
    </div>
  )
}
