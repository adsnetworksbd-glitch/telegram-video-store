import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, EmptyState, ErrorState, FilterChip, LoadMoreButton, Skeleton, toast } from '@/components/ui'
import { adminConfigApi, type AdminRecord, type TicketStatus } from '../configApi'
import { Card, ErrorBanner, Field, Toggle, inputCls } from '../ui'
import { errorText, fmtDateTime, loadSchema, num, str } from '../util'
import { useAdminList } from '../useAdminList'

const STATUS_LABEL: Record<string, string> = { open: 'খোলা', in_progress: 'চলছে', resolved: 'সমাধান হয়েছে', closed: 'বন্ধ' }
const STATUS_VARIANT: Record<string, 'blue' | 'green' | 'orange' | 'red' | 'gray'> = { open: 'orange', in_progress: 'blue', resolved: 'green', closed: 'gray' }

function Tickets() {
  const [statuses, setStatuses] = useState<string[]>(['open', 'in_progress', 'resolved', 'closed'])
  const [status, setStatus] = useState<string>('')
  const [open, setOpen] = useState<string | null>(null)
  const [reply, setReply] = useState('')
  const [next, setNext] = useState<TicketStatus>('resolved')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const list = useAdminList<AdminRecord>((p) => adminConfigApi.tickets({ status: (status || undefined) as TicketStatus | undefined, page: p }), [status])
  useEffect(() => { loadSchema().then((s) => { const c = s.modules.support.choices?.statuses; if (c?.length) setStatuses(c) }).catch(() => undefined) }, [])

  async function send(t: AdminRecord) {
    if (!reply.trim()) { setErr('উত্তর লিখুন।'); return }
    setBusy(true); setErr(null)
    try { await adminConfigApi.replyTicket(t.id, reply.trim(), next); toast('উত্তর পাঠানো হয়েছে।', 'success'); setReply(''); list.reload() }
    catch (e) { setErr(errorText(e)) } finally { setBusy(false) }
  }
  async function changeStatus(t: AdminRecord, s: TicketStatus) {
    try { await adminConfigApi.setTicketStatus(t.id, s); toast('Status বদলানো হয়েছে।', 'success'); list.reload() } catch (e) { toast(errorText(e), 'error') }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <FilterChip active={status === ''} onClick={() => setStatus('')}>সব</FilterChip>
        {statuses.map((s) => <FilterChip key={s} active={status === s} onClick={() => setStatus(s)}>{STATUS_LABEL[s] ?? s}</FilterChip>)}
      </div>
      {list.error && list.items.length === 0 ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading && list.items.length === 0 ? (
        <Skeleton className="h-[80px] rounded-[12px]" />
      ) : list.items.length === 0 ? <EmptyState icon="🎧" title="কোনো Ticket নেই" /> : (
        <ul className="flex flex-col gap-2">
          {list.items.map((t) => (
            <li key={t.id} className="card-base flex flex-col gap-1.5 p-3">
              <button className="flex flex-col gap-1 text-left" onClick={() => { setOpen(open === t.id ? null : t.id); setReply(''); setErr(null) }}>
                <span className="flex items-center justify-between gap-2">
                  <Badge variant={STATUS_VARIANT[str(t.status)] ?? 'gray'}>{STATUS_LABEL[str(t.status)] ?? str(t.status)}</Badge>
                  <span className="text-[11px] text-[#6B7280]">{fmtDateTime(t.created_at)}</span>
                </span>
                <span className="text-[13px] font-medium text-white">{str(t.subject) || '(বিষয় নেই)'}</span>
                <span className="text-[11px] text-[#6B7280]">User: {str(t.user_id)}{str(t.category) && ` · ${str(t.category)}`}</span>
              </button>
              {open === t.id && (
                <div className="flex flex-col gap-2 border-t border-border pt-2">
                  <p className="whitespace-pre-wrap break-words text-[12.5px] text-[#D1D5DB]">{str(t.message)}</p>
                  {str(t.admin_reply) && <p className="whitespace-pre-wrap break-words rounded-[10px] bg-card px-3 py-2 text-[12.5px] text-[#6EE7B7]">উত্তর ({str(t.replied_by)}, {fmtDateTime(t.replied_at)}): {str(t.admin_reply)}</p>}
                  <Field label="উত্তর"><textarea className={inputCls} rows={3} maxLength={2000} value={reply} onChange={(e) => setReply(e.target.value)} /></Field>
                  <Field label="উত্তরের পর Status">
                    <select className={inputCls} value={next} onChange={(e) => setNext(e.target.value as TicketStatus)}>
                      {statuses.map((s) => <option key={s} value={s}>{STATUS_LABEL[s] ?? s}</option>)}
                    </select>
                  </Field>
                  <ErrorBanner message={err} />
                  <div className="flex flex-wrap gap-2">
                    <Button loading={busy} onClick={() => void send(t)} className="flex-1">উত্তর পাঠান</Button>
                    {str(t.status) !== 'closed' && <button className="btn-ghost !w-auto px-4" onClick={() => void changeStatus(t, 'closed')}>বন্ধ করুন</button>}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {list.hasMore && <LoadMoreButton onClick={list.more} loading={list.loading} />}
    </div>
  )
}

interface FaqDraft { id: string | null; question: string; answer: string; order: string; visible: boolean }
const emptyFaq: FaqDraft = { id: null, question: '', answer: '', order: '0', visible: true }

function Faqs() {
  const [items, setItems] = useState<AdminRecord[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [d, setD] = useState<FaqDraft | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(async () => {
    setLoadError(null)
    try { setItems((await adminConfigApi.faqs()).items) } catch (e) { setLoadError(errorText(e)) }
  }, [])
  useEffect(() => { void load() }, [load])

  if (loadError) return <ErrorState message={loadError} onRetry={() => void load()} />
  if (!items) return <Skeleton className="h-[80px] rounded-[12px]" />

  async function save() {
    if (!d || busy) return
    const order = Number(d.order)
    if (!d.question.trim() || !d.answer.trim()) { setErr('প্রশ্ন ও উত্তর দুটোই দিন।'); return }
    if (!Number.isInteger(order) || order < 0) { setErr('ক্রম ০ বা তার বেশি পূর্ণসংখ্যা হতে হবে।'); return }
    setBusy(true); setErr(null)
    const body = { question: d.question.trim(), answer: d.answer.trim(), display_order: order, is_visible: d.visible }
    try {
      if (d.id) await adminConfigApi.updateFaq(d.id, body); else await adminConfigApi.createFaq(body)
      toast('FAQ সংরক্ষণ হয়েছে।', 'success'); setD(null); await load()
    } catch (e) { setErr(errorText(e)) } finally { setBusy(false) }
  }
  async function remove(f: AdminRecord) {
    if (!window.confirm('এই FAQ মুছে ফেলবেন?')) return
    try { await adminConfigApi.deleteFaq(f.id); toast('FAQ মুছে ফেলা হয়েছে।', 'success'); await load() } catch (e) { toast(errorText(e), 'error') }
  }

  return (
    <div className="flex flex-col gap-2">
      {d ? (
        <Card title={d.id ? 'FAQ সম্পাদনা' : 'নতুন FAQ'}>
          <Field label="প্রশ্ন"><input className={inputCls} maxLength={300} value={d.question} onChange={(e) => setD({ ...d, question: e.target.value })} /></Field>
          <Field label="উত্তর"><textarea className={inputCls} rows={4} maxLength={3000} value={d.answer} onChange={(e) => setD({ ...d, answer: e.target.value })} /></Field>
          <Field label="ক্রম"><input className={inputCls} inputMode="numeric" value={d.order} onChange={(e) => setD({ ...d, order: e.target.value })} /></Field>
          <Toggle label="ব্যবহারকারীদের দেখানো হবে" checked={d.visible} onChange={(v) => setD({ ...d, visible: v })} />
          <ErrorBanner message={err} />
          <div className="flex gap-2">
            <button className="btn-ghost !w-auto px-5" onClick={() => setD(null)}>বাতিল</button>
            <Button loading={busy} onClick={() => void save()} className="flex-1">সংরক্ষণ করুন</Button>
          </div>
        </Card>
      ) : <button className="btn-secondary" onClick={() => { setErr(null); setD(emptyFaq) }}>+ নতুন FAQ</button>}
      {items.length === 0 ? <EmptyState icon="❓" title="কোনো FAQ নেই" /> : (
        <ul className="flex flex-col gap-2">
          {items.map((f) => (
            <li key={f.id} className="card-base flex flex-col gap-1 p-3">
              <div className="flex items-center justify-between gap-2">
                <Badge variant={f.is_visible === false ? 'gray' : 'green'}>{f.is_visible === false ? 'লুকানো' : 'দৃশ্যমান'}</Badge>
                <span className="text-[11px] text-[#6B7280]">ক্রম {num(f.display_order) ?? 0}</span>
              </div>
              <div className="text-[13px] font-medium text-white">{str(f.question)}</div>
              <div className="line-clamp-2 text-[12px] text-[#9CA3AF]">{str(f.answer)}</div>
              <div className="flex gap-2 pt-1">
                <button className="btn-ghost !w-auto px-3 !py-1.5" onClick={() => { setErr(null); setD({ id: f.id, question: str(f.question), answer: str(f.answer), order: String(num(f.display_order) ?? 0), visible: f.is_visible !== false }) }}>সম্পাদনা</button>
                <button className="btn-ghost !w-auto px-3 !py-1.5" onClick={() => void remove(f)}>মুছুন</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function Support() {
  const [tab, setTab] = useState<'tickets' | 'faq'>('tickets')
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-bold text-white">Support ও FAQ</h1>
      <div className="flex gap-2">
        <FilterChip active={tab === 'tickets'} onClick={() => setTab('tickets')}>Support Ticket</FilterChip>
        <FilterChip active={tab === 'faq'} onClick={() => setTab('faq')}>FAQ</FilterChip>
      </div>
      {tab === 'tickets' ? <Tickets /> : <Faqs />}
    </div>
  )
}
