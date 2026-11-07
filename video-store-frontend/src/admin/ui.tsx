import type { ReactNode } from 'react'
import { cx } from '@/components/ui'

export const inputCls =
  'w-full rounded-[12px] border border-border bg-card px-3.5 py-2.5 text-[14px] text-white ' +
  'placeholder:text-[#6B7280] outline-none focus:border-primary disabled:opacity-60'

export function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-[#9CA3AF]">{label}</span>
      {children}
      {help && <span className="text-[11px] text-[#6B7280]">{help}</span>}
    </label>
  )
}

export function Toggle({
  label, help, checked, onChange,
}: { label: string; help?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between gap-3 rounded-[12px] border border-border bg-card px-3.5 py-2.5 text-left disabled:opacity-60"
    >
      <span className="flex flex-col">
        <span className="text-[13px] font-medium text-white">{label}</span>
        {help && <span className="text-[11px] text-[#6B7280]">{help}</span>}
      </span>
      <span className={cx('relative h-[22px] w-[40px] shrink-0 rounded-full transition-colors', checked ? 'bg-primary' : 'bg-[#374151]')}>
        <span className={cx('absolute top-[2px] h-[18px] w-[18px] rounded-full bg-white transition-all', checked ? 'left-[20px]' : 'left-[2px]')} />
      </span>
    </button>
  )
}

export function Card({ title, children, className = '' }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cx('card-base p-4 flex flex-col gap-3', className)}>
      {title && <h2 className="text-[14px] font-bold text-white">{title}</h2>}
      {children}
    </section>
  )
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="rounded-[10px] border border-danger/30 bg-danger/15 px-3 py-2 text-[12.5px] text-[#FCA5A5]">
      {message}
    </p>
  )
}

/** Image with a graceful fallback (a broken thumbnail URL must not break the page). */
export function Thumb({ url, className = '' }: { url: string; className?: string }) {
  return url ? (
    <img
      src={url}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      className={cx('object-cover bg-card2', className)}
      onError={(e) => { e.currentTarget.style.visibility = 'hidden' }}
    />
  ) : (
    <div className={cx('flex items-center justify-center bg-card2 text-[18px]', className)}>🎬</div>
  )
}
