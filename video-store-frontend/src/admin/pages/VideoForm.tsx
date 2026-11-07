import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Badge, Button, ErrorState, Skeleton, cx, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord, type AdminSchema, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Thumb, Toggle, inputCls } from '../ui'
import { bool, errorText, fmtCount, fmtDateTime, loadSchema, num, str } from '../util'

// Every limit, default and choice below comes from GET /admin/config/schema; the server re-validates all of it.

interface Draft {
  title: string; slug: string; description: string; thumbnail_url: string
  category_ids: string[]; primary_category_id: string
  quality: string; minutes: string; seconds: string; file_size_mb: string
  price_bdt: string; is_free: boolean; is_featured: boolean; is_trending: boolean; is_latest: boolean
  ads_unlock_enabled: boolean; ads_required: string; ads_unlock_duration_hours: string
  purchase_enabled: boolean; purchase_duration_hours: string
  is_published: boolean
  source_type: string; source_url: string
  backup_source_type: string; backup_source_url: string; remove_backup: boolean
}

const intStr = (v: unknown, fallback: unknown): string => {
  const n = num(v) ?? num(fallback)
  return n === null ? '' : String(n)
}

function emptyDraft(fields: Record<string, FieldSpec>): Draft {
  return {
    title: '', slug: '', description: '', thumbnail_url: '', category_ids: [], primary_category_id: '',
    quality: '', minutes: '', seconds: '', file_size_mb: '', price_bdt: '',
    is_free: false, is_featured: false, is_trending: false, is_latest: false,
    ads_unlock_enabled: false, ads_required: intStr(null, fields.ads_required?.default),
    ads_unlock_duration_hours: intStr(null, fields.ads_unlock_duration_hours?.default),
    purchase_enabled: true, purchase_duration_hours: intStr(null, fields.purchase_duration_hours?.default),
    is_published: false, source_type: '', source_url: '', backup_source_type: '', backup_source_url: '', remove_backup: false,
  }
}

function fromRecord(r: AdminRecord, fields: Record<string, FieldSpec>): Draft {
  const dur = num(r.duration_seconds)
  return {
    ...emptyDraft(fields),
    title: str(r.title), slug: str(r.slug), description: str(r.description), thumbnail_url: str(r.thumbnail_url),
    category_ids: Array.isArray(r.category_ids) ? r.category_ids.filter((c): c is string => typeof c === 'string') : [],
    primary_category_id: str(r.primary_category_id),
    quality: str(r.quality),
    minutes: dur === null ? '' : String(Math.floor(dur / 60)), seconds: dur === null ? '' : String(dur % 60),
    file_size_mb: intStr(r.file_size_mb, null), price_bdt: intStr(r.price_bdt, null),
    is_free: bool(r.is_free), is_featured: bool(r.is_featured), is_trending: bool(r.is_trending), is_latest: bool(r.is_latest),
    ads_unlock_enabled: bool(r.ads_unlock_enabled), ads_required: intStr(r.ads_required, fields.ads_required?.default),
    ads_unlock_duration_hours: intStr(r.ads_unlock_duration_hours, fields.ads_unlock_duration_hours?.default),
    purchase_enabled: r.purchase_enabled === undefined || r.purchase_enabled === null ? true : bool(r.purchase_enabled),
    purchase_duration_hours: intStr(r.purchase_duration_hours, fields.purchase_duration_hours?.default),
    is_published: bool(r.is_published),
    source_type: str(r.source_type), backup_source_type: str(r.backup_source_type),
  }
}

const toNum = (s: string): number | undefined => {
  if (s.trim() === '') return undefined
  const n = Number(s)
  return Number.isFinite(n) ? n : undefined
}

/** Create: every filled field. Edit: only fields that differ from what was loaded (partial update). */
function buildBody(d: Draft, original: Draft | null): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  const put = (key: string, value: unknown, was: unknown) => {
    if (value === undefined) return
    if (original === null ? value !== '' && value !== false : value !== was) body[key] = value
  }
  const o = original
  put('title', d.title.trim(), o?.title)
  put('slug', d.slug.trim(), o?.slug)
  put('description', d.description, o?.description)
  put('thumbnail_url', d.thumbnail_url.trim(), o?.thumbnail_url)
  if (original === null ? d.category_ids.length > 0 : d.category_ids.join('|') !== original.category_ids.join('|')) body.category_ids = d.category_ids
  put('primary_category_id', d.primary_category_id || undefined, o?.primary_category_id)  // enums can't be cleared, only changed
  put('quality', d.quality || undefined, o?.quality)
  const dur = d.minutes.trim() === '' && d.seconds.trim() === '' ? undefined : (toNum(d.minutes) ?? 0) * 60 + (toNum(d.seconds) ?? 0)
  const odur = o && (o.minutes.trim() !== '' || o.seconds.trim() !== '') ? (toNum(o.minutes) ?? 0) * 60 + (toNum(o.seconds) ?? 0) : undefined
  put('duration_seconds', dur, odur)
  put('file_size_mb', toNum(d.file_size_mb), o ? toNum(o.file_size_mb) : undefined)
  put('price_bdt', toNum(d.price_bdt), o ? toNum(o.price_bdt) : undefined)
  put('ads_required', toNum(d.ads_required), o ? toNum(o.ads_required) : undefined)
  put('ads_unlock_duration_hours', toNum(d.ads_unlock_duration_hours), o ? toNum(o.ads_unlock_duration_hours) : undefined)
  put('purchase_duration_hours', toNum(d.purchase_duration_hours), o ? toNum(o.purchase_duration_hours) : undefined)
  for (const k of ['is_free', 'is_featured', 'is_trending', 'is_latest', 'ads_unlock_enabled', 'purchase_enabled', 'is_published'] as const) {
    if (original === null ? (k === 'purchase_enabled' ? d[k] === false : d[k] === true) : d[k] !== original[k]) body[k] = d[k]
  }
  put('source_type', d.source_type || undefined, o?.source_type)
  if (d.source_url.trim()) body.source_url = d.source_url.trim()                     // write-only: sent only when (re)entered
  put('backup_source_type', d.remove_backup ? undefined : d.backup_source_type || undefined, o?.backup_source_type)
  if (d.remove_backup) body.backup_source_url = ''                                   // "" removes the backup
  else if (d.backup_source_url.trim()) body.backup_source_url = d.backup_source_url.trim()
  return body
}

export default function VideoForm() {
  const { id } = useParams<{ id: string }>()
  const isNew = !id
  const navigate = useNavigate()
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'videos.manage')

  const [schema, setSchema] = useState<AdminSchema | null>(null)
  const [categories, setCategories] = useState<AdminRecord[]>([])
  const [record, setRecord] = useState<AdminRecord | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [original, setOriginal] = useState<Draft | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fields = schema?.modules.videos.fields

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [sch, cats, rec] = await Promise.all([
        loadSchema(),
        adminConfigApi.categories(),
        isNew ? Promise.resolve(null) : adminConfigApi.get('/admin/videos', id as string),
      ])
      setSchema(sch)
      setCategories(cats.items)
      setRecord(rec)
      const f = sch.modules.videos.fields
      const d = rec ? fromRecord(rec, f) : emptyDraft(f)
      setDraft(d)
      setOriginal(rec ? d : null)
    } catch (e) {
      setLoadError(errorText(e))
    } finally {
      setLoading(false)
    }
  }, [id, isNew])

  useEffect(() => { void load() }, [load])

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => (d ? { ...d, [key]: value } : d))

  function toggleCategory(catId: string) {
    setDraft((d) => {
      if (!d) return d
      const on = d.category_ids.includes(catId)
      const ids = on ? d.category_ids.filter((c) => c !== catId) : [...d.category_ids, catId]
      const primary = ids.includes(d.primary_category_id) ? d.primary_category_id : (ids[0] ?? '')
      return { ...d, category_ids: ids, primary_category_id: primary }
    })
  }

  const body = useMemo(() => (draft ? buildBody(draft, original) : {}), [draft, original])
  const dirty = Object.keys(body).length > 0

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!draft || saving || !canManage) return
    if (!draft.title.trim()) { setError('টাইটেল দিন।'); return }
    setSaving(true)
    setError(null)
    try {
      if (isNew) {
        const created = await adminConfigApi.create('/admin/videos', body)
        toast('ভিডিও তৈরি হয়েছে।', 'success')
        navigate(`/admin/videos/${encodeURIComponent(created.id)}`, { replace: true })
      } else {
        await adminConfigApi.update('/admin/videos', id as string, body)
        toast('সংরক্ষণ হয়েছে।', 'success')
        await load()
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  if (loading && !draft) return <div className="flex flex-col gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[140px] rounded-[12px]" />)}</div>
  if (loadError || !draft || !fields) return <ErrorState message={loadError ?? undefined} onRetry={() => void load()} />

  const qualities = fields.quality?.options ?? []
  const sourceTypes = fields.source_type?.options ?? []
  const hasSource = bool(record?.has_source)
  const hasBackup = bool(record?.has_backup_source)
  const rawPackages = record?.packages
  const packages = Array.isArray(rawPackages) ? (rawPackages as Array<{ id: string; name: string | null }>) : []

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
      <div className="flex items-center justify-between gap-3">
        <Link to="/admin/videos" className="text-[13px] text-primary-light">← ভিডিও তালিকা</Link>
        {!isNew && <Badge variant={draft.is_published ? 'green' : 'gray'}>{draft.is_published ? 'Published' : 'Hidden'}</Badge>}
      </div>
      <h1 className="text-[16px] font-bold text-white">{isNew ? 'নতুন ভিডিও' : 'ভিডিও সম্পাদনা'}</h1>
      {!canManage && <p className="text-[12px] text-[#FCD34D]">আপনার Role-এ ভিডিও পরিবর্তনের অনুমতি নেই (শুধু দেখা)।</p>}

      <fieldset disabled={!canManage || saving} className="flex flex-col gap-3 min-w-0">
        <Card title="মূল তথ্য">
          <Field label="টাইটেল *"><input className={inputCls} value={draft.title} maxLength={fields.title?.max ?? 200} onChange={(e) => set('title', e.target.value)} /></Field>
          <Field label="Slug" help={fields.slug?.help}><input className={inputCls} value={draft.slug} maxLength={fields.slug?.max ?? 120} autoCapitalize="none" onChange={(e) => set('slug', e.target.value)} /></Field>
          <Field label="বিবরণ" help={`${draft.description.length} / ${fields.description?.max ?? 5000}`}>
            <textarea className={cx(inputCls, 'min-h-[96px]')} value={draft.description} maxLength={fields.description?.max ?? 5000} onChange={(e) => set('description', e.target.value)} />
          </Field>
          <Field label="Thumbnail URL" help="https:// দিয়ে শুরু হতে হবে">
            <input className={inputCls} type="url" inputMode="url" value={draft.thumbnail_url} maxLength={fields.thumbnail_url?.max ?? 1000} autoCapitalize="none" onChange={(e) => set('thumbnail_url', e.target.value)} />
          </Field>
          {draft.thumbnail_url && <Thumb url={draft.thumbnail_url} className="h-[120px] w-[210px] rounded-[10px]" />}
        </Card>

        <Card title="ক্যাটাগরি">
          {categories.length === 0 ? (
            <p className="text-[12px] text-[#9CA3AF]">কোনো ক্যাটাগরি নেই। আগে ক্যাটাগরি তৈরি করুন।</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {categories.map((c) => {
                const on = draft.category_ids.includes(c.id)
                return (
                  <button
                    key={c.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggleCategory(c.id)}
                    className={cx('rounded-[20px] border px-3 py-1 text-[12px] font-medium disabled:opacity-60',
                      on ? 'border-primary/40 bg-primary/15 text-primary-light' : 'border-border bg-card text-[#9CA3AF]')}
                  >
                    {str(c.name) || c.id}{!bool(c.is_visible) ? ' (hidden)' : ''}
                  </button>
                )
              })}
            </div>
          )}
          {draft.category_ids.length > 1 && (
            <Field label="Primary category">
              <select className={inputCls} value={draft.primary_category_id} onChange={(e) => set('primary_category_id', e.target.value)}>
                {draft.category_ids.map((cid) => <option key={cid} value={cid}>{str(categories.find((c) => c.id === cid)?.name) || cid}</option>)}
              </select>
            </Field>
          )}
        </Card>

        <Card title="কোয়ালিটি, সময় ও সাইজ">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Quality">
              <select className={inputCls} value={draft.quality} onChange={(e) => set('quality', e.target.value)}>
                <option value="">—</option>
                {qualities.map((q) => <option key={q} value={q}>{q}</option>)}
              </select>
            </Field>
            <Field label="ফাইল সাইজ (MB)"><input className={inputCls} inputMode="decimal" value={draft.file_size_mb} onChange={(e) => set('file_size_mb', e.target.value)} /></Field>
            <Field label="সময়: মিনিট"><input className={inputCls} inputMode="numeric" value={draft.minutes} onChange={(e) => set('minutes', e.target.value)} /></Field>
            <Field label="সময়: সেকেন্ড"><input className={inputCls} inputMode="numeric" value={draft.seconds} onChange={(e) => set('seconds', e.target.value)} /></Field>
          </div>
        </Card>

        <Card title="Source">
          <Field label="Source type">
            <select className={inputCls} value={draft.source_type} onChange={(e) => set('source_type', e.target.value)}>
              <option value="">—</option>
              {sourceTypes.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Source লিংক" help={hasSource ? 'সংরক্ষিত আছে (এনক্রিপ্টেড, দেখানো হয় না)। বদলাতে নতুন লিংক দিন।' : 'Publish করতে Source লিংক লাগবে। https:// দিয়ে শুরু হতে হবে।'}>
            <input className={inputCls} type="url" inputMode="url" autoComplete="off" autoCapitalize="none" value={draft.source_url} maxLength={fields.source_url?.max ?? 2000}
              placeholder={hasSource ? '•••••• (অপরিবর্তিত)' : 'https://'} onChange={(e) => set('source_url', e.target.value)} />
          </Field>
          <Field label="Backup source type">
            <select className={inputCls} value={draft.backup_source_type} onChange={(e) => set('backup_source_type', e.target.value)}>
              <option value="">— (Source type-এর মতো)</option>
              {sourceTypes.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Backup source লিংক (ঐচ্ছিক)" help={hasBackup ? 'Backup সংরক্ষিত আছে। বদলাতে নতুন লিংক দিন।' : 'মূল Source কাজ না করলে ব্যবহারের জন্য।'}>
            <input className={inputCls} type="url" inputMode="url" autoComplete="off" autoCapitalize="none" value={draft.backup_source_url} maxLength={fields.backup_source_url?.max ?? 2000}
              placeholder={hasBackup ? '•••••• (অপরিবর্তিত)' : 'https://'} disabled={draft.remove_backup} onChange={(e) => set('backup_source_url', e.target.value)} />
          </Field>
          {hasBackup && <Toggle label="Backup source মুছে ফেলুন" checked={draft.remove_backup} onChange={(v) => set('remove_backup', v)} />}
        </Card>

        <Card title="মূল্য ও অ্যাক্সেস">
          <Toggle label="ফ্রি ভিডিও" checked={draft.is_free} onChange={(v) => set('is_free', v)} />
          <Field label="মূল্য (BDT)"><input className={inputCls} inputMode="decimal" value={draft.price_bdt} onChange={(e) => set('price_bdt', e.target.value)} /></Field>
          <Toggle label="কেনা চালু (Purchase)" checked={draft.purchase_enabled} onChange={(v) => set('purchase_enabled', v)} />
          <Field label="কেনার পর অ্যাক্সেসের সময় (ঘণ্টা, 0 = আজীবন)"><input className={inputCls} inputMode="numeric" value={draft.purchase_duration_hours} onChange={(e) => set('purchase_duration_hours', e.target.value)} /></Field>
          <Toggle label="Ads দিয়ে আনলক চালু" checked={draft.ads_unlock_enabled} onChange={(v) => set('ads_unlock_enabled', v)} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="প্রয়োজনীয় Ads"><input className={inputCls} inputMode="numeric" value={draft.ads_required} onChange={(e) => set('ads_required', e.target.value)} /></Field>
            <Field label="Ads আনলকের সময় (ঘণ্টা)"><input className={inputCls} inputMode="numeric" value={draft.ads_unlock_duration_hours} onChange={(e) => set('ads_unlock_duration_hours', e.target.value)} /></Field>
          </div>
        </Card>

        <Card title="প্রদর্শন">
          <Toggle label="Featured" checked={draft.is_featured} onChange={(v) => set('is_featured', v)} />
          <Toggle label="Trending" checked={draft.is_trending} onChange={(v) => set('is_trending', v)} />
          <Toggle label="Latest" checked={draft.is_latest} onChange={(v) => set('is_latest', v)} />
          <Toggle label="Published" help="বন্ধ রাখলে ভিডিও অ্যাপে লুকানো (Archive) থাকবে" checked={draft.is_published} onChange={(v) => set('is_published', v)} />
        </Card>
      </fieldset>

      {!isNew && record && (
        <Card title="পরিসংখ্যান">
          <p className="text-[12px] text-[#9CA3AF]">
            {fmtCount(num(record.view_count))} ভিউ · {fmtCount(num(record.purchase_count))} বিক্রি · তৈরি: {fmtDateTime(record.created_at)} · আপডেট: {fmtDateTime(record.updated_at)}
          </p>
          {packages.length > 0 && (
            <p className="text-[12px] text-[#9CA3AF]">প্যাকেজে আছে: {packages.map((p) => p.name || p.id).join(', ')}</p>
          )}
        </Card>
      )}

      <ErrorBanner message={error} />
      {canManage && (
        <Button type="submit" loading={saving} disabled={!isNew && !dirty}>
          {isNew ? 'ভিডিও তৈরি করুন' : dirty ? 'সংরক্ষণ করুন' : 'কোনো পরিবর্তন নেই'}
        </Button>
      )}
    </form>
  )
}
