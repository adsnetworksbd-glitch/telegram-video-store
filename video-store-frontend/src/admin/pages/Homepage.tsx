import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, ErrorState, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type FieldSpec } from '../configApi'
import { can, useAdminStore } from '../store'
import { Card, ErrorBanner, Field, Thumb, Toggle, inputCls } from '../ui'
import { errorText, loadSchema } from '../util'

interface Section { id: string; label: string; enabled: boolean }
interface Banner {
  id: string; title: string; image_url: string; link_type: string; link_id: string; link_url: string
  enabled: boolean; starts_at: string; ends_at: string
}
interface Spec { sectionIds: string[]; linkTypes: string[]; fields: Record<string, FieldSpec> }

const SECTION_HINT: Record<string, string> = {
  featured_banner: 'নিচের Banner তালিকা থেকে আসে',
  featured_videos: 'ভিডিওর "Featured" চিহ্ন থেকে আসে',
  trending_videos: 'ভিডিওর "Trending" চিহ্ন থেকে আসে',
  latest_videos: 'ভিডিওর "Latest" চিহ্ন থেকে আসে',
  popular_categories: 'দৃশ্যমান ক্যাটাগরি থেকে আসে',
  featured_packages: 'প্যাকেজের "Featured" চিহ্ন থেকে আসে',
  all_videos: 'সব Published ভিডিও',
}

// <input type="datetime-local"> works in local time; the API stores/returns ISO instants.
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
const s = (v: unknown) => (typeof v === 'string' ? v : '')

export default function Homepage() {
  const admin = useAdminStore((x) => x.admin)
  const canManage = can(admin, 'settings.manage')

  const [spec, setSpec] = useState<Spec | null>(null)
  const [sections, setSections] = useState<Section[]>([])
  const [banners, setBanners] = useState<Banner[]>([])
  const [announcement, setAnnouncement] = useState('')
  const [announcementUrl, setAnnouncementUrl] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState<null | 'sections' | 'banners' | 'announcement'>(null)
  const [errors, setErrors] = useState<{ sections?: string; banners?: string; announcement?: string }>({})

  const apply = useCallback((hp: Record<string, unknown>, sp: Spec) => {
    const raw = Array.isArray(hp.sections) ? (hp.sections as Record<string, unknown>[]) : []
    const known = raw.filter((x) => sp.sectionIds.includes(s(x.id)))
    const missing = sp.sectionIds.filter((id) => !known.some((x) => x.id === id))
    setSections([
      ...known.map((x) => ({ id: s(x.id), label: s(x.label), enabled: x.enabled !== false })),
      ...missing.map((id) => ({ id, label: id.replace(/_/g, ' '), enabled: false })),
    ])
    setBanners((Array.isArray(hp.banners) ? (hp.banners as Record<string, unknown>[]) : []).map((b) => ({
      id: s(b.id), title: s(b.title), image_url: s(b.image_url), link_type: s(b.link_type) || 'none',
      link_id: s(b.link_id), link_url: s(b.link_url), enabled: b.enabled !== false,
      starts_at: toLocalInput(b.starts_at), ends_at: toLocalInput(b.ends_at),
    })))
    setAnnouncement(s(hp.homepage_announcement))
    setAnnouncementUrl(s(hp.homepage_announcement_url))
  }, [])

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const [sch, hp] = await Promise.all([loadSchema(), adminConfigApi.homepage() as Promise<Record<string, unknown>>])
      const m = sch.modules.homepage
      const sp: Spec = { sectionIds: m.choices?.section_ids ?? [], linkTypes: m.choices?.banner_link_types ?? ['none'], fields: m.fields }
      setSpec(sp)
      apply(hp, sp)
    } catch (e) {
      setLoadError(errorText(e))
    }
  }, [apply])

  useEffect(() => { void load() }, [load])

  if (loadError) return <ErrorState message={loadError} onRetry={() => void load()} />
  if (!spec) return <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[96px] rounded-[12px]" />)}</div>

  const maxBanners = spec.fields.banners?.max ?? 10
  const annMax = spec.fields.homepage_announcement?.max ?? 300

  async function save(part: 'sections' | 'banners' | 'announcement', body: Record<string, unknown>) {
    setSaving(part)
    setErrors((e) => ({ ...e, [part]: undefined }))
    try {
      const res = (await adminConfigApi.saveHomepage(body)) as Record<string, unknown>
      if (spec) apply(res, spec)
      toast('সংরক্ষণ হয়েছে।', 'success')
    } catch (e) {
      setErrors((x) => ({ ...x, [part]: errorText(e) }))
    } finally {
      setSaving(null)
    }
  }

  function saveSections() {
    if (sections.some((x) => !x.label.trim())) { setErrors((e) => ({ ...e, sections: 'প্রতিটি Section-এর নাম দিন।' })); return }
    void save('sections', { sections: sections.map((x, i) => ({ id: x.id, label: x.label.trim(), enabled: x.enabled, order: i + 1 })) })
  }

  function saveBanners() {
    const out: Record<string, unknown>[] = []
    for (const [i, b] of banners.entries()) {
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(b.id)) { setErrors((e) => ({ ...e, banners: `Banner ${i + 1}: ID-তে শুধু অক্ষর, সংখ্যা, _ বা - ব্যবহার করুন।` })); return }
      if (!b.image_url.trim().startsWith('https://')) { setErrors((e) => ({ ...e, banners: `Banner ${i + 1}: ছবির URL https:// দিয়ে শুরু হতে হবে।` })); return }
      if ((b.link_type === 'video' || b.link_type === 'package') && !b.link_id.trim()) { setErrors((e) => ({ ...e, banners: `Banner ${i + 1}: Video/Package ID দিন।` })); return }
      if (b.link_type === 'url' && !b.link_url.trim().startsWith('https://')) { setErrors((e) => ({ ...e, banners: `Banner ${i + 1}: লিংক https:// দিয়ে শুরু হতে হবে।` })); return }
      const row: Record<string, unknown> = {
        id: b.id, title: b.title.trim() || null, image_url: b.image_url.trim(), link_type: b.link_type, enabled: b.enabled, order: i + 1,
        starts_at: fromLocalInput(b.starts_at), ends_at: fromLocalInput(b.ends_at),
      }
      if (b.link_type === 'video' || b.link_type === 'package') row.link_id = b.link_id.trim()
      if (b.link_type === 'url') row.link_url = b.link_url.trim()
      out.push(row)
    }
    void save('banners', { banners: out })
  }

  const move = <T,>(arr: T[], i: number, dir: -1 | 1): T[] => {
    const j = i + dir
    if (j < 0 || j >= arr.length) return arr
    const c = arr.slice()
    ;[c[i], c[j]] = [c[j], c[i]]
    return c
  }
  const patchBanner = (i: number, p: Partial<Banner>) => setBanners((arr) => arr.map((b, k) => (k === i ? { ...b, ...p } : b)))

  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">হোমপেজ ম্যানেজমেন্ট</h1>

      <Card title="Section দৃশ্যমানতা ও ক্রম">
        <p className="text-[11.5px] text-[#6B7280]">
          ↑ ↓ দিয়ে ক্রম বদলান, সুইচ দিয়ে Section দেখান/লুকান। কনটেন্ট ঠিক করতে{' '}
          <Link to="/admin/videos" className="text-primary-light underline">ভিডিও</Link>,{' '}
          <Link to="/admin/packages" className="text-primary-light underline">প্যাকেজ</Link> ও{' '}
          <Link to="/admin/categories" className="text-primary-light underline">ক্যাটাগরি</Link> পেজ ব্যবহার করুন।
        </p>
        <fieldset disabled={!canManage || saving !== null} className="flex flex-col gap-2 min-w-0">
          {sections.map((sec, i) => (
            <div key={sec.id} className="flex flex-col gap-1.5 rounded-[12px] border border-border bg-card p-2.5">
              <div className="flex items-center gap-2">
                <span className="w-5 text-center text-[11px] text-[#6B7280]">{i + 1}</span>
                <input className={`${inputCls} !py-1.5`} value={sec.label} maxLength={60}
                  onChange={(e) => setSections((a) => a.map((x, k) => (k === i ? { ...x, label: e.target.value } : x)))} />
                <button type="button" aria-label="উপরে" className="px-1.5 text-[#9CA3AF] disabled:opacity-30" disabled={i === 0} onClick={() => setSections((a) => move(a, i, -1))}>↑</button>
                <button type="button" aria-label="নিচে" className="px-1.5 text-[#9CA3AF] disabled:opacity-30" disabled={i === sections.length - 1} onClick={() => setSections((a) => move(a, i, 1))}>↓</button>
              </div>
              <Toggle label={sec.enabled ? 'দেখানো হচ্ছে' : 'লুকানো'} help={SECTION_HINT[sec.id]} checked={sec.enabled}
                onChange={(v) => setSections((a) => a.map((x, k) => (k === i ? { ...x, enabled: v } : x)))} />
            </div>
          ))}
        </fieldset>
        <ErrorBanner message={errors.sections ?? null} />
        {canManage && <Button loading={saving === 'sections'} disabled={saving !== null} onClick={saveSections}>Section সংরক্ষণ করুন</Button>}
      </Card>

      <Card title={`Featured Banner (${banners.length}/${maxBanners})`}>
        <fieldset disabled={!canManage || saving !== null} className="flex flex-col gap-3 min-w-0">
          {banners.length === 0 && <p className="text-[12.5px] text-[#9CA3AF]">কোনো Banner নেই।</p>}
          {banners.map((b, i) => (
            <div key={i} className="flex flex-col gap-2 rounded-[12px] border border-border bg-card p-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5">
                  <span className="text-[12px] font-semibold text-white">Banner {i + 1}</span>
                  <Badge variant={b.enabled ? 'green' : 'gray'}>{b.enabled ? 'চালু' : 'বন্ধ'}</Badge>
                </div>
                <div className="flex items-center">
                  <button type="button" aria-label="উপরে" className="px-1.5 text-[#9CA3AF] disabled:opacity-30" disabled={i === 0} onClick={() => setBanners((a) => move(a, i, -1))}>↑</button>
                  <button type="button" aria-label="নিচে" className="px-1.5 text-[#9CA3AF] disabled:opacity-30" disabled={i === banners.length - 1} onClick={() => setBanners((a) => move(a, i, 1))}>↓</button>
                  <button type="button" aria-label="মুছুন" className="px-1.5 text-[#FCA5A5]" onClick={() => setBanners((a) => a.filter((_, k) => k !== i))}>✕</button>
                </div>
              </div>
              <Field label="ID *" help="একটি Banner-এর ইউনিক নাম (a-z, 0-9, _ -)"><input className={inputCls} value={b.id} maxLength={64} autoCapitalize="none" onChange={(e) => patchBanner(i, { id: e.target.value })} /></Field>
              <Field label="শিরোনাম"><input className={inputCls} value={b.title} maxLength={100} onChange={(e) => patchBanner(i, { title: e.target.value })} /></Field>
              <Field label="ছবির URL *" help="https:// দিয়ে শুরু হতে হবে"><input className={inputCls} type="url" inputMode="url" autoCapitalize="none" value={b.image_url} maxLength={1000} onChange={(e) => patchBanner(i, { image_url: e.target.value })} /></Field>
              {b.image_url && <Thumb url={b.image_url} className="h-[80px] w-[200px] rounded-[10px]" />}
              <Field label="লিংকের ধরন">
                <select className={inputCls} value={b.link_type} onChange={(e) => patchBanner(i, { link_type: e.target.value })}>
                  {spec.linkTypes.map((t) => <option key={t} value={t}>{({ none: 'কোনো লিংক নেই', video: 'ভিডিও', package: 'প্যাকেজ', url: 'বাইরের URL' } as Record<string, string>)[t] ?? t}</option>)}
                </select>
              </Field>
              {(b.link_type === 'video' || b.link_type === 'package') && (
                <Field label={b.link_type === 'video' ? 'ভিডিও ID' : 'প্যাকেজ ID'}><input className={inputCls} value={b.link_id} maxLength={128} autoCapitalize="none" onChange={(e) => patchBanner(i, { link_id: e.target.value })} /></Field>
              )}
              {b.link_type === 'url' && (
                <Field label="বাইরের URL" help="https:// দিয়ে শুরু হতে হবে"><input className={inputCls} type="url" inputMode="url" autoCapitalize="none" value={b.link_url} maxLength={1000} onChange={(e) => patchBanner(i, { link_url: e.target.value })} /></Field>
              )}
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Field label="দেখানো শুরু (ঐচ্ছিক)"><input className={inputCls} type="datetime-local" value={b.starts_at} onChange={(e) => patchBanner(i, { starts_at: e.target.value })} /></Field>
                <Field label="দেখানো শেষ (ঐচ্ছিক)"><input className={inputCls} type="datetime-local" value={b.ends_at} onChange={(e) => patchBanner(i, { ends_at: e.target.value })} /></Field>
              </div>
              <Toggle label="চালু" checked={b.enabled} onChange={(v) => patchBanner(i, { enabled: v })} />
            </div>
          ))}
          {canManage && banners.length < maxBanners && (
            <button type="button" className="btn-ghost" onClick={() => setBanners((a) => [...a, { id: `banner-${Date.now().toString(36)}`, title: '', image_url: '', link_type: 'none', link_id: '', link_url: '', enabled: true, starts_at: '', ends_at: '' }])}>+ Banner যোগ করুন</button>
          )}
        </fieldset>
        <ErrorBanner message={errors.banners ?? null} />
        {canManage && <Button loading={saving === 'banners'} disabled={saving !== null} onClick={saveBanners}>Banner সংরক্ষণ করুন</Button>}
      </Card>

      <Card title="Announcement">
        <fieldset disabled={!canManage || saving !== null} className="flex flex-col gap-3 min-w-0">
          <Field label="বার্তা" help={`${announcement.length} / ${annMax} · খালি রাখলে Announcement লুকানো থাকবে`}>
            <textarea className={`${inputCls} min-h-[72px]`} value={announcement} maxLength={annMax} onChange={(e) => setAnnouncement(e.target.value)} />
          </Field>
          <Field label="লিংক (ঐচ্ছিক)" help="https:// দিয়ে শুরু হতে হবে">
            <input className={inputCls} type="url" inputMode="url" autoCapitalize="none" value={announcementUrl} maxLength={1000} onChange={(e) => setAnnouncementUrl(e.target.value)} />
          </Field>
        </fieldset>
        <ErrorBanner message={errors.announcement ?? null} />
        {canManage && (
          <Button loading={saving === 'announcement'} disabled={saving !== null}
            onClick={() => void save('announcement', { homepage_announcement: announcement.trim() || null, homepage_announcement_url: announcementUrl.trim() || null })}>
            Announcement সংরক্ষণ করুন
          </Button>
        )}
      </Card>
    </div>
  )
}
