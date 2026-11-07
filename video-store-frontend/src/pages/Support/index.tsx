import { useCallback, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { supportApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import { useConfigStore } from '@/store'
import { getTelegram } from '@/hooks/useTelegram'
import { SubHeader, PageWrapper } from '@/components/layout'
import { Spinner, Button, FilterChip, InlineError, toast } from '@/components/ui'
import { cx } from '@/utils'

// ─── Support ──────────────────────────────────────────────────────────────────
// FAQ and tickets come from the Backend. Terms / Privacy / direct-contact links
// are admin-controlled config values; when the Backend does not provide them the
// buttons say so instead of pretending to work.

interface FAQ { id: string; question: string; answer: string }

const MAX_SUBJECT = 200
const MAX_MESSAGE = 2000

const ISSUE_CATEGORIES = [
  { key: 'payment',   label: '💳 Payment' },
  { key: 'access',    label: '🔓 Access / Unlock' },
  { key: 'technical', label: '🛠 Technical' },
  { key: 'other',     label: 'অন্যান্য' },
]

function openExternal(url: string) {
  const tg = getTelegram()
  try {
    if (/^https?:\/\/t\.me\//i.test(url) && tg?.openTelegramLink) tg.openTelegramLink(url)
    else if (tg?.openLink) tg.openLink(url)
    else window.open(url, '_blank', 'noopener')
  } catch {
    window.open(url, '_blank', 'noopener')
  }
}

export default function SupportPage() {
  const appConfig = useConfigStore((s) => s.appConfig)

  const [faqs, setFaqs]       = useState<FAQ[]>([])
  const [faqLoading, setFaqLoading] = useState(true)
  const [faqError, setFaqError] = useState<string | null>(null)
  const [open, setOpen]       = useState<string | null>(null)

  const [mode, setMode]       = useState<'contact' | 'issue'>('contact')
  const [issueCat, setIssueCat] = useState('payment')
  const [orderRef, setOrderRef] = useState('')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [sentId, setSentId]   = useState<string | null>(null)

  const loadFaq = useCallback(async () => {
    setFaqLoading(true); setFaqError(null)
    try {
      const r = await supportApi.faq()
      setFaqs(r.data.faqs)
    } catch (e) {
      setFaqError(getErrorMessage(e, 'FAQ লোড করা যায়নি।'))
    } finally {
      setFaqLoading(false)
    }
  }, [])
  useEffect(() => { void loadFaq() }, [loadFaq])

  async function sendTicket() {
    const subj = subject.trim()
    const msg = message.trim()
    if (!subj || !msg) { toast('বিষয় ও বিস্তারিত লিখুন।', 'error'); return }
    const ref = orderRef.trim()
    const body = mode === 'issue' && ref ? `Order ID: ${ref}\n\n${msg}` : msg
    setSending(true)
    try {
      const r = await supportApi.submitTicket({
        subject: (mode === 'issue' ? '[Issue] ' : '') + subj,
        message: body.slice(0, MAX_MESSAGE),
        category: mode === 'issue' ? issueCat : 'general',
      })
      setSentId(r.data.ticket_id)
      setSubject(''); setMessage(''); setOrderRef('')
      toast('বার্তা পাঠানো হয়েছে!', 'success')
    } catch (e) {
      toast(getErrorMessage(e, 'পাঠানো যায়নি। আবার চেষ্টা করুন।'), 'error')
    } finally {
      setSending(false)
    }
  }

  const supportLink = appConfig?.support_url
    || (appConfig?.support_username ? `https://t.me/${appConfig.support_username.replace(/^@/, '')}` : null)
  const termsUrl = appConfig?.terms_url || null
  const privacyUrl = appConfig?.privacy_url || null

  return (
    <PageWrapper hasBottomNav={false}>
      <SubHeader title="❓ Support" />
      <div className="px-4 py-4 space-y-5">

        {/* FAQ */}
        <section>
          <p className="text-[11px] text-[#6B7280] font-semibold uppercase tracking-[0.4px] mb-3">সাধারণ প্রশ্ন (FAQ)</p>
          {faqLoading ? (
            <div className="flex justify-center py-6"><Spinner size={22} /></div>
          ) : faqError ? (
            <InlineError message={faqError} onRetry={() => void loadFaq()} />
          ) : faqs.length === 0 ? (
            <p className="text-[12px] text-[#6B7280]">এখনো কোনো FAQ যোগ করা হয়নি।</p>
          ) : (
            <div className="space-y-2">
              {faqs.map((faq) => (
                <div key={faq.id} className="bg-card border border-border rounded-[10px] overflow-hidden">
                  <button
                    onClick={() => setOpen(open === faq.id ? null : faq.id)}
                    aria-expanded={open === faq.id}
                    className="w-full flex items-center justify-between px-3 py-[11px] text-left"
                  >
                    <span className="text-[12px] font-medium text-white flex-1 pr-2">{faq.question}</span>
                    <motion.div animate={{ rotate: open === faq.id ? 180 : 0 }} transition={{ duration: 0.2 }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="2" strokeLinecap="round"><polyline points="6 9 12 15 18 9" /></svg>
                    </motion.div>
                  </button>
                  <AnimatePresence initial={false}>
                    {open === faq.id && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <div className="px-3 pb-3 border-t border-border">
                          <p className="text-[11px] text-[#9CA3AF] leading-[1.6] mt-2 whitespace-pre-line">{faq.answer}</p>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Contact Support / Report Issue */}
        <section>
          <p className="text-[11px] text-[#6B7280] font-semibold uppercase tracking-[0.4px] mb-3">আমাদের জানান</p>

          <div className="flex bg-card border border-border rounded-[10px] p-[3px] mb-3" role="tablist">
            {([['contact', '💬 যোগাযোগ'], ['issue', '🐞 সমস্যা জানান']] as const).map(([k, label]) => (
              <button
                key={k}
                role="tab"
                aria-selected={mode === k}
                onClick={() => { setMode(k); setSentId(null) }}
                className={cx(
                  'flex-1 py-[7px] rounded-[7px] text-[11px] font-semibold border transition-all',
                  mode === k ? 'bg-primary/15 text-primary border-primary/30' : 'text-[#6B7280] border-transparent',
                )}
              >{label}</button>
            ))}
          </div>

          {supportLink && mode === 'contact' && (
            <button
              onClick={() => openExternal(supportLink)}
              className="w-full mb-3 py-[11px] rounded-[10px] bg-primary/10 border border-primary/25 text-[12px] font-semibold text-primary"
            >
              ✈️ সরাসরি Telegram-এ যোগাযোগ
            </button>
          )}

          <div className="bg-card border border-border rounded-[11px] p-3 space-y-3">
            {mode === 'issue' && (
              <>
                <div className="flex gap-2 flex-wrap">
                  {ISSUE_CATEGORIES.map((c) => (
                    <FilterChip key={c.key} active={issueCat === c.key} onClick={() => setIssueCat(c.key)}>{c.label}</FilterChip>
                  ))}
                </div>
                <input
                  value={orderRef}
                  onChange={(e) => setOrderRef(e.target.value)}
                  placeholder="Order ID (যদি থাকে)"
                  maxLength={64}
                  className="w-full bg-surface border border-border rounded-[8px] px-3 py-[8px] text-[12px] text-white outline-none placeholder:text-[#6B7280]"
                />
              </>
            )}
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder={mode === 'issue' ? 'সমস্যার সংক্ষিপ্ত বিবরণ...' : 'বিষয়...'}
              maxLength={MAX_SUBJECT - 8}
              className="w-full bg-surface border border-border rounded-[8px] px-3 py-[8px] text-[12px] text-white outline-none placeholder:text-[#6B7280]"
            />
            <div>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="বিস্তারিত লিখুন..."
                rows={4}
                maxLength={MAX_MESSAGE}
                className="w-full bg-surface border border-border rounded-[8px] px-3 py-[8px] text-[12px] text-white outline-none placeholder:text-[#6B7280] resize-none"
              />
              <p className="text-right text-[10px] text-[#6B7280] mt-1">{message.length}/{MAX_MESSAGE}</p>
            </div>
            <Button onClick={() => void sendTicket()} loading={sending} disabled={!subject.trim() || !message.trim()}>
              {mode === 'issue' ? '📮 সমস্যা জানান' : '📮 বার্তা পাঠান'}
            </Button>
            {sentId && (
              <p className="text-[11px] text-[#6EE7B7] text-center">
                ✅ আপনার বার্তা গৃহীত হয়েছে। Ticket: <span className="font-mono">{sentId.slice(0, 8)}</span>
              </p>
            )}
          </div>
        </section>

        {/* Legal */}
        <section>
          <p className="text-[11px] text-[#6B7280] font-semibold uppercase tracking-[0.4px] mb-3">আইনি তথ্য</p>
          <div className="flex gap-2">
            <LegalButton label="📄 Terms & Conditions" url={termsUrl} />
            <LegalButton label="🔒 Privacy Policy" url={privacyUrl} />
          </div>
        </section>
      </div>
    </PageWrapper>
  )
}

function LegalButton({ label, url }: { label: string; url: string | null }) {
  if (!url) {
    return (
      <div className="flex-1 py-[10px] px-2 bg-card/50 border border-border rounded-[9px] text-center opacity-70">
        <p className="text-[11px] text-[#6B7280]">{label}</p>
        <p className="text-[9px] text-[#6B7280] mt-[2px]">এখনো প্রকাশিত হয়নি</p>
      </div>
    )
  }
  return (
    <button
      onClick={() => openExternal(url)}
      className="flex-1 py-[10px] bg-card border border-border rounded-[9px] text-[11px] text-[#9CA3AF] active:scale-[0.98] transition-transform"
    >
      {label}
    </button>
  )
}
