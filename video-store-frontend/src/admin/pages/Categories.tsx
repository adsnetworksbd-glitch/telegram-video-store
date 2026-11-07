import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Badge, Button, EmptyState, ErrorState, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Thumb, Toggle, inputCls } from '../ui'
import { bool, errorText, fmtCount, loadSchema, num, str } from '../util'

interface Draft { id: string; name: string; slug: string; description: string; thumbnail_url: string; display_order: string; is_visible: boolean }

const blank = (fields: Record<string, FieldSpec>): Draft => ({
  id: '', name: '', slug: '', description: '', thumbnail_url: '',
  display_order: String(num(fields.display_order?.default) ?? ''), is_visible: false,
})

const fromRecord = (c: AdminRecord): Draft => ({
  id: c.id, name: str(c.name), slug: str(c.slug), description: str(c.description), thumbnail_url: str(c.thumbnail_url),
  display_order: num(c.display_order) === null ? '' : String(num(c.display_order)), is_visible: bool(c.is_visible),
})

function CategoryForm({
  initial, fields, isNew, canManage, onSaved, onCancel,
}: {
  initial: Draft; fields: Record<string, FieldSpec>; isNew: boolean; canManage: boolean
  onSaved: () => void; onCancel: () => void
}) {
  const [d, setD] = useState<Draft>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (saving || !canManage) return
    if (!d.name.trim()) { setError('নাম দিন।'); return }
    const order = d.display_order.trim() === '' ? undefined : Number(d.display_order)
    if (order !== undefined && !Number.isFinite(order)) { setError('Display order সংখ্যা হতে হবে।'); return }
    setSaving(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        name: d.name.trim(), description: d.description, thumbnail_url: d.thumbnail_url.trim(), is_visible: d.is_visible,
      }
      if (d.slug.trim()) body.slug = d.slug.trim()
      if (order !== undefined) body.display_order = order
      if (isNew) {
        if (d.id.trim()) body.id = d.id.trim()
        await adminConfigApi.createCategory(body)
      } else {
        await adminConfigApi.updateCategory(initial.id, body)
      }
      toast(isNew ? 'ক্যাটাগরি তৈরি হয়েছে।' : 'সংরক্ষণ হয়েছে।', 'success')
      onSaved()
    } catch (err) {
      setError(errorText(err))
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <Card title={isNew ? 'নতুন ক্যাটাগরি' : 'ক্যাটাগরি সম্পাদনা'}>
        <fieldset disabled={!canManage || saving} className="flex flex-col gap-3 min-w-0">
          {isNew && <Field label="ID (ঐচ্ছিক)" help="খালি রাখলে নিজে তৈরি হবে। পরে বদলানো যায় না।"><input className={inputCls} value={d.id} maxLength={64} autoCapitalize="none" onChange={(e) => set('id', e.target.value)} /></Field>}
          <Field label="নাম *"><input className={inputCls} value={d.name} maxLength={fields.name?.max ?? 80} onChange={(e) => set('name', e.target.value)} /></Field>
          <Field label="Slug" help={fields.slug?.help}><input className={inputCls} value={d.slug} maxLength={fields.slug?.max ?? 80} autoCapitalize="none" onChange={(e) => set('slug', e.target.value)} /></Field>
          <Field label="বিবরণ" help={`${d.description.length} / ${fields.description?.max ?? 500}`}>
            <textarea className={`${inputCls} min-h-[72px]`} value={d.description} maxLength={fields.description?.max ?? 500} onChange={(e) => set('description', e.target.value)} />
          </Field>
          <Field label="Thumbnail URL" help="https:// দিয়ে শুরু হতে হবে">
            <input className={inputCls} type="url" inputMode="url" autoCapitalize="none" value={d.thumbnail_url} maxLength={fields.thumbnail_url?.max ?? 1000} onChange={(e) => set('thumbnail_url', e.target.value)} />
          </Field>
          {d.thumbnail_url && <Thumb url={d.thumbnail_url} className="h-[90px] w-[160px] rounded-[10px]" />}
          <Field label="Display order (ছোট সংখ্যা আগে)"><input className={inputCls} inputMode="numeric" value={d.display_order} onChange={(e) => set('display_order', e.target.value)} /></Field>
          <Toggle label="অ্যাপে দৃশ্যমান (Publish)" help="বন্ধ রাখলে ক্যাটাগরি লুকানো থাকবে" checked={d.is_visible} onChange={(v) => set('is_visible', v)} />
        </fieldset>
        <ErrorBanner message={error} />
        <div className="flex gap-2">
          <button type="button" className="btn-ghost !w-auto px-5" onClick={onCancel} disabled={saving}>বন্ধ করুন</button>
          {canManage && <Button type="submit" loading={saving} className="flex-1">{isNew ? 'তৈরি করুন' : 'সংরক্ষণ করুন'}</Button>}
        </div>
      </Card>
    </form>
  )
}

export default function Categories() {
  const admin = useAdminStore((s) => s.admin)
  const canManage = can(admin, 'videos.manage')

  const [items, setItems] = useState<AdminRecord[]>([])
  const [fields, setFields] = useState<Record<string, FieldSpec> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ draft: Draft; isNew: boolean } | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [sch, list] = await Promise.all([loadSchema(), adminConfigApi.categories()])
      setFields(sch.modules.categories.fields)
      setItems(list.items)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function toggleVisible(c: AdminRecord) {
    setBusyId(c.id)
    try {
      const updated = await adminConfigApi.updateCategory(c.id, { is_visible: !bool(c.is_visible) })
      setItems((prev) => prev.map((x) => (x.id === c.id ? { ...x, ...updated } : x)))
      toast(bool(updated.is_visible) ? 'ক্যাটাগরি দৃশ্যমান।' : 'ক্যাটাগরি Hide করা হয়েছে।', 'success')
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusyId(null)
    }
  }

  async function recount(c: AdminRecord) {
    setBusyId(c.id)
    try {
      const r = await adminConfigApi.recountCategory(c.id)
      setItems((prev) => prev.map((x) => (x.id === c.id ? { ...x, video_count: r.video_count } : x)))
      toast(`Published ভিডিও: ${r.video_count}`, 'success')
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusyId(null)
    }
  }

  if (loading && items.length === 0 && !fields) return <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[76px] rounded-[12px]" />)}</div>
  if (error && !fields) return <ErrorState message={error} onRetry={() => void load()} />
  if (!fields) return null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[16px] font-bold text-white">ক্যাটাগরি <span className="text-[12px] font-normal text-[#9CA3AF]">({items.length})</span></h1>
        {canManage && !editing && (
          <button className="btn-primary !w-auto px-4 !py-2.5 !text-[13px]" onClick={() => setEditing({ draft: blank(fields), isNew: true })}>+ নতুন ক্যাটাগরি</button>
        )}
      </div>

      {editing && (
        <CategoryForm
          key={editing.draft.id || 'new'}
          initial={editing.draft}
          fields={fields}
          isNew={editing.isNew}
          canManage={canManage}
          onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); void load() }}
        />
      )}

      {items.length === 0 ? (
        <EmptyState icon="🗂️" title="কোনো ক্যাটাগরি নেই" description={canManage ? 'প্রথম ক্যাটাগরি তৈরি করুন।' : undefined} />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((c) => {
            const visible = bool(c.is_visible)
            return (
              <li key={c.id} className="card-base flex flex-col gap-2 p-2.5">
                <div className="flex items-center gap-3">
                  <Thumb url={str(c.thumbnail_url)} className="h-[48px] w-[48px] shrink-0 rounded-[8px]" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-semibold text-white">{str(c.name) || c.id}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <Badge variant={visible ? 'green' : 'gray'}>{visible ? 'Visible' : 'Hidden'}</Badge>
                      <Badge variant="blue">{fmtCount(num(c.video_count))} ভিডিও</Badge>
                      <span className="text-[11px] text-[#6B7280]">order {fmtCount(num(c.display_order))}</span>
                    </div>
                    {str(c.description) && <p className="mt-1 line-clamp-2 text-[11.5px] text-[#9CA3AF]">{str(c.description)}</p>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button className="btn-ghost !py-2 !text-[12px]" onClick={() => setEditing({ draft: fromRecord(c), isNew: false })}>{canManage ? 'এডিট' : 'দেখুন'}</button>
                  {canManage && (
                    <>
                      <button className="btn-ghost !py-2 !text-[12px]" disabled={busyId === c.id} onClick={() => void toggleVisible(c)}>{visible ? 'Hide' : 'Publish'}</button>
                      <button className="btn-ghost !py-2 !text-[12px]" disabled={busyId === c.id} onClick={() => void recount(c)}>Count আপডেট</button>
                    </>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
