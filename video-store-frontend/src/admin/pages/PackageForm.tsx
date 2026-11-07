import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Badge, Button, ErrorState, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Thumb, Toggle, inputCls } from '../ui'
import { bool, errorText, fmtCount, loadSchema, num, str } from '../util'

interface Draft {
  id: string; name: string; description: string; thumbnail_url: string
  price_bdt: string; original_price_bdt: string
  duration_type: 'lifetime' | 'custom'; duration_value: string; duration_unit: 'hours' | 'days'
  ads_required: string; display_order: string
  ads_unlock_enabled: boolean; purchase_enabled: boolean; is_featured: boolean; is_published: boolean
  videos: Array<{ id: string; title: string }>
}

const blank = (f: Record<string, FieldSpec>): Draft => ({
  id: '', name: '', description: '', thumbnail_url: '', price_bdt: '', original_price_bdt: '',
  duration_type: 'lifetime', duration_value: '', duration_unit: 'days',
  ads_required: String(num(f.ads_required?.default) ?? ''), display_order: String(num(f.display_order?.default) ?? ''),
  ads_unlock_enabled: false, purchase_enabled: true, is_featured: false, is_published: false, videos: [],
})

function fromRecord(p: AdminRecord): Draft {
  const hours = num(p.duration_hours) ?? 0
  const days = hours > 0 && hours % 24 === 0
  const detail = Array.isArray(p.videos) ? (p.videos as AdminRecord[]) : []
  const ids = Array.isArray(p.video_ids) ? (p.video_ids as unknown[]).filter((x): x is string => typeof x === 'string') : []
  return {
    id: p.id, name: str(p.name), description: str(p.description), thumbnail_url: str(p.thumbnail_url),
    price_bdt: num(p.price_bdt) === null ? '' : String(num(p.price_bdt)),
    original_price_bdt: num(p.original_price_bdt) === null ? '' : String(num(p.original_price_bdt)),
    duration_type: str(p.duration_type) === 'custom' ? 'custom' : 'lifetime',
    duration_value: hours > 0 ? String(days ? hours / 24 : hours) : '', duration_unit: days || hours === 0 ? 'days' : 'hours',
    ads_required: num(p.ads_required) === null ? '' : String(num(p.ads_required)),
    display_order: num(p.display_order) === null ? '' : String(num(p.display_order)),
    ads_unlock_enabled: bool(p.ads_unlock_enabled), purchase_enabled: p.purchase_enabled !== false,
    is_featured: bool(p.is_featured), is_published: bool(p.is_published),
    videos: ids.map((id) => ({ id, title: str(detail.find((d) => d.id === id)?.title) || id })),
  }
}

/** Search + add videos. A video may belong to any number of packages. */
function VideoPicker({ selected, max, disabled, onAdd }: {
  selected: string[]; max: number; disabled: boolean; onAdd: (v: { id: string; title: string }) => void
}) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<AdminRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const seq = useRef(0)

  useEffect(() => {
    const term = q.trim()
    if (!term) { setResults([]); setErr(null); return }
    const t = setTimeout(() => {
      const my = ++seq.current
      setLoading(true)
      setErr(null)
      adminConfigApi.list('/admin/videos', { q: term, limit: 8 })
        .then((r) => { if (my === seq.current) setResults(r.items) })
        .catch((e) => { if (my === seq.current) setErr(errorText(e)) })
        .finally(() => { if (my === seq.current) setLoading(false) })
    }, 400)
    return () => clearTimeout(t)
  }, [q])

  const full = selected.length >= max
  return (
    <div className="flex flex-col gap-2">
      <input className={inputCls} type="search" placeholder="টাইটেল বা ID দিয়ে ভিডিও খুঁজুন" value={q} maxLength={100} disabled={disabled || full} onChange={(e) => setQ(e.target.value)} />
      {full && <p className="text-[11px] text-[#FCD34D]">সর্বোচ্চ {max}টি ভিডিও যোগ করা যায়।</p>}
      {err && <ErrorBanner message={err} />}
      {loading && <Skeleton className="h-[44px] rounded-[10px]" />}
      {results.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {results.map((v) => {
            const already = selected.includes(v.id)
            return (
              <li key={v.id} className="flex items-center gap-2 rounded-[10px] border border-border bg-card p-1.5">
                <Thumb url={str(v.thumbnail_url)} className="h-[36px] w-[60px] shrink-0 rounded-[6px]" />
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-white">{str(v.title) || v.id}</span>
                {!bool(v.is_published) && <Badge variant="gray">Hidden</Badge>}
                <button type="button" className="btn-ghost !w-auto px-3 !py-1.5 !text-[12px]" disabled={already || full || disabled}
                  onClick={() => onAdd({ id: v.id, title: str(v.title) || v.id })}>{already ? 'যোগ আছে' : '+ যোগ'}</button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default function PackageForm() {
  const { id } = useParams<{ id: string }>()
  const isNew = !id
  const navigate = useNavigate()
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'videos.manage')

  const [fields, setFields] = useState<Record<string, FieldSpec> | null>(null)
  const [d, setD] = useState<Draft | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => (x ? { ...x, [k]: v } : x))

  useEffect(() => {
    let cancelled = false
    setLoadError(null)
    Promise.all([loadSchema(), id ? adminConfigApi.get('/admin/packages', id) : Promise.resolve(null)])
      .then(([sch, rec]) => {
        if (cancelled) return
        const f = sch.modules.packages.fields
        setFields(f)
        setD(rec ? fromRecord(rec) : blank(f))
      })
      .catch((e) => { if (!cancelled) setLoadError(errorText(e)) })
    return () => { cancelled = true }
  }, [id, isNew, attempt])

  if (loadError) return <ErrorState message={loadError} onRetry={() => setAttempt((n) => n + 1)} />
  if (!fields || !d) return <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[76px] rounded-[12px]" />)}</div>

  const maxVideos = fields.video_ids?.max ?? 20
  const price = Number(d.price_bdt)
  const orig = Number(d.original_price_bdt)
  const discount = d.price_bdt !== '' && d.original_price_bdt !== '' && orig > 0 && orig >= price ? Math.round(((orig - price) / orig) * 10000) / 100 : 0

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (saving || !canManage || !d) return
    if (!d.name.trim()) { setError('নাম দিন।'); return }
    const body: Record<string, unknown> = {
      name: d.name.trim(), description: d.description, thumbnail_url: d.thumbnail_url.trim(),
      video_ids: d.videos.map((v) => v.id),
      ads_unlock_enabled: d.ads_unlock_enabled, purchase_enabled: d.purchase_enabled,
      is_featured: d.is_featured, is_published: d.is_published, duration_type: d.duration_type,
    }
    const numField = (key: string, raw: string, label: string, int = false): boolean => {
      if (raw.trim() === '') return true
      const n = Number(raw)
      if (!Number.isFinite(n) || (int && !Number.isInteger(n))) { setError(`${label} সঠিক সংখ্যা হতে হবে।`); return false }
      body[key] = n
      return true
    }
    if (!numField('price_bdt', d.price_bdt, 'মূল্য')) return
    if (!numField('original_price_bdt', d.original_price_bdt, 'আগের মূল্য')) return
    if (!numField('ads_required', d.ads_required, 'Ads সংখ্যা', true)) return
    if (!numField('display_order', d.display_order, 'Display order', true)) return
    if (d.duration_type === 'custom') {
      const v = Number(d.duration_value)
      if (!Number.isFinite(v) || v <= 0 || !Number.isInteger(v)) { setError('Custom সময়ের জন্য ০-র বেশি পূর্ণসংখ্যা দিন।'); return }
      body.duration_hours = d.duration_unit === 'days' ? v * 24 : v
    }
    setSaving(true)
    setError(null)
    try {
      if (isNew) {
        if (d.id.trim()) body.id = d.id.trim()
        const created = await adminConfigApi.create('/admin/packages', body)
        toast('প্যাকেজ তৈরি হয়েছে।', 'success')
        navigate(`/admin/packages/${encodeURIComponent(created.id)}`, { replace: true })
      } else {
        const updated = await adminConfigApi.update('/admin/packages', d.id, body)
        setD((x) => (x ? { ...fromRecord({ ...updated, videos: undefined }), videos: x.videos } : x))
        toast('সংরক্ষণ হয়েছে।', 'success')
        setSaving(false)
      }
    } catch (err) {
      setError(errorText(err))
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[16px] font-bold text-white">{isNew ? 'নতুন প্যাকেজ' : 'প্যাকেজ সম্পাদনা'}</h1>
        <Link to="/admin/packages" className="btn-ghost !w-auto px-4 !py-2 !text-[12px]">← তালিকা</Link>
      </div>
      <fieldset disabled={!canManage || saving} className="flex flex-col gap-3 min-w-0">
        <Card title="মূল তথ্য">
          {isNew && <Field label="ID (ঐচ্ছিক)" help="খালি রাখলে নিজে তৈরি হবে। পরে বদলানো যায় না।"><input className={inputCls} value={d.id} maxLength={64} autoCapitalize="none" onChange={(e) => set('id', e.target.value)} /></Field>}
          <Field label="নাম *"><input className={inputCls} value={d.name} maxLength={fields.name?.max ?? 120} onChange={(e) => set('name', e.target.value)} /></Field>
          <Field label="বিবরণ" help={`${d.description.length} / ${fields.description?.max ?? 5000}`}>
            <textarea className={`${inputCls} min-h-[84px]`} value={d.description} maxLength={fields.description?.max ?? 5000} onChange={(e) => set('description', e.target.value)} />
          </Field>
          <Field label="Thumbnail URL" help="https:// দিয়ে শুরু হতে হবে">
            <input className={inputCls} type="url" inputMode="url" autoCapitalize="none" value={d.thumbnail_url} maxLength={fields.thumbnail_url?.max ?? 1000} onChange={(e) => set('thumbnail_url', e.target.value)} />
          </Field>
          {d.thumbnail_url && <Thumb url={d.thumbnail_url} className="h-[90px] w-[160px] rounded-[10px]" />}
        </Card>

        <Card title={`অন্তর্ভুক্ত ভিডিও (${d.videos.length}/${maxVideos})`}>
          <p className="text-[11.5px] text-[#6B7280]">একটি ভিডিও একাধিক প্যাকেজে রাখা যায়। ভিডিও সংখ্যা সার্ভার নিজে হিসাব করে।</p>
          {d.videos.length === 0 ? (
            <p className="text-[12.5px] text-[#9CA3AF]">এখনো কোনো ভিডিও যোগ করা হয়নি।</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {d.videos.map((v, i) => (
                <li key={v.id} className="flex items-center gap-2 rounded-[10px] border border-border bg-card px-2.5 py-1.5">
                  <span className="w-5 text-center text-[11px] text-[#6B7280]">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-white">{v.title}</span>
                  <button type="button" aria-label="উপরে" className="px-1.5 text-[#9CA3AF] disabled:opacity-30" disabled={i === 0}
                    onClick={() => set('videos', d.videos.map((x, j, a) => (j === i - 1 ? a[i] : j === i ? a[i - 1] : x)))}>↑</button>
                  <button type="button" aria-label="নিচে" className="px-1.5 text-[#9CA3AF] disabled:opacity-30" disabled={i === d.videos.length - 1}
                    onClick={() => set('videos', d.videos.map((x, j, a) => (j === i + 1 ? a[i] : j === i ? a[i + 1] : x)))}>↓</button>
                  <button type="button" aria-label="সরান" className="px-1.5 text-[#FCA5A5]" onClick={() => set('videos', d.videos.filter((x) => x.id !== v.id))}>✕</button>
                </li>
              ))}
            </ul>
          )}
          {canManage && <VideoPicker selected={d.videos.map((v) => v.id)} max={maxVideos} disabled={saving} onAdd={(v) => set('videos', [...d.videos, v])} />}
        </Card>

        <Card title="মূল্য ও ছাড়">
          <Field label="বর্তমান মূল্য (BDT) *"><input className={inputCls} inputMode="decimal" value={d.price_bdt} onChange={(e) => set('price_bdt', e.target.value)} /></Field>
          <Field label="আগের মূল্য (BDT)" help="বর্তমান মূল্যের চেয়ে বেশি হলে ছাড় % নিজে হিসাব হবে। খালি রাখলে ছাড় নেই।">
            <input className={inputCls} inputMode="decimal" value={d.original_price_bdt} onChange={(e) => set('original_price_bdt', e.target.value)} />
          </Field>
          {discount > 0 && <Badge variant="green">{discount}% ছাড় ({fmtCount(Number.isFinite(orig) ? orig : null)} → {fmtCount(Number.isFinite(price) ? price : null)})</Badge>}
        </Card>

        <Card title="Access সময়কাল">
          <div className="grid grid-cols-2 gap-2">
            {(['lifetime', 'custom'] as const).map((t) => (
              <button key={t} type="button" onClick={() => set('duration_type', t)}
                className={`rounded-[12px] border px-3 py-2.5 text-[13px] font-medium ${d.duration_type === t ? 'border-primary bg-primary/15 text-primary-light' : 'border-border bg-card text-[#9CA3AF]'}`}>
                {t === 'lifetime' ? 'Lifetime' : 'Custom সময়'}
              </button>
            ))}
          </div>
          {d.duration_type === 'custom' && (
            <div className="flex gap-2">
              <input className={inputCls} inputMode="numeric" placeholder="সংখ্যা" value={d.duration_value} onChange={(e) => set('duration_value', e.target.value)} />
              <select className={`${inputCls} !w-[110px]`} value={d.duration_unit} onChange={(e) => set('duration_unit', e.target.value as 'hours' | 'days')}>
                <option value="days">দিন</option>
                <option value="hours">ঘণ্টা</option>
              </select>
            </div>
          )}
        </Card>

        <Card title="Unlock ও Visibility">
          <Toggle label="Purchase চালু" help="বন্ধ থাকলে ব্যবহারকারী কিনতে পারবে না" checked={d.purchase_enabled} onChange={(v) => set('purchase_enabled', v)} />
          <Toggle label="Ads দিয়ে Unlock চালু" checked={d.ads_unlock_enabled} onChange={(v) => set('ads_unlock_enabled', v)} />
          {d.ads_unlock_enabled && (
            <Field label="প্রয়োজনীয় Ads সংখ্যা" help={`${fields.ads_required?.min ?? 1} – ${fields.ads_required?.max ?? 50}`}>
              <input className={inputCls} inputMode="numeric" value={d.ads_required} onChange={(e) => set('ads_required', e.target.value)} />
            </Field>
          )}
          <Toggle label="Featured" help="হোমপেজের Featured Packages-এ দেখাবে" checked={d.is_featured} onChange={(v) => set('is_featured', v)} />
          <Toggle label="অ্যাপে দৃশ্যমান (Publish)" help="বন্ধ রাখলে প্যাকেজ লুকানো থাকবে" checked={d.is_published} onChange={(v) => set('is_published', v)} />
          <Field label="Display order (ছোট সংখ্যা আগে)"><input className={inputCls} inputMode="numeric" value={d.display_order} onChange={(e) => set('display_order', e.target.value)} /></Field>
        </Card>
      </fieldset>

      <ErrorBanner message={error} />
      {canManage && <Button type="submit" loading={saving}>{isNew ? 'প্যাকেজ তৈরি করুন' : 'সংরক্ষণ করুন'}</Button>}
    </form>
  )
}
