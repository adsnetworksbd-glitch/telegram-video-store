import { useState, useEffect, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cx, formatCountdown } from '@/utils'

// Re-exported so layout/pages can import UI helpers from one place.
export { cx }

// ─── Spinner ──────────────────────────────────────────────────────────────────
export function Spinner({ size = 24, className = '' }: { size?: number; className?: string }) {
  return (
    <div
      className={cx('border-2 border-border border-t-primary rounded-full animate-spin', className)}
      style={{ width: size, height: size }}
    />
  )
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={cx('skeleton', className)} />
}

// ─── Badge ────────────────────────────────────────────────────────────────────
interface BadgeProps {
  children: ReactNode
  variant?: 'blue' | 'purple' | 'green' | 'orange' | 'red' | 'gray'
  className?: string
}
export function Badge({ children, variant = 'blue', className = '' }: BadgeProps) {
  const styles = {
    blue:   'bg-primary/15 text-primary-light border border-primary/25',
    purple: 'bg-secondary/15 text-secondary-light border border-secondary/25',
    green:  'bg-success/12 text-[#6EE7B7] border border-success/25',
    orange: 'bg-warning/10 text-[#FCD34D] border border-warning/20',
    red:    'bg-danger/10 text-[#FCA5A5] border border-danger/20',
    gray:   'bg-card text-[#9CA3AF] border border-border',
  }
  return (
    <span className={cx('inline-flex items-center gap-1 text-[10px] font-semibold px-[7px] py-[3px] rounded-[5px]', styles[variant], className)}>
      {children}
    </span>
  )
}

// ─── Quality Badge ────────────────────────────────────────────────────────────
export function QualityBadge({ quality }: { quality: string }) {
  const color = quality === '4K' || quality === 'FHD'
    ? 'bg-primary/85'
    : quality === 'HD'
    ? 'bg-secondary/85'
    : 'bg-success/80'
  return (
    <span className={cx('text-[9px] font-bold px-[5px] py-[2px] rounded-[4px] text-white', color)}>
      {quality}
    </span>
  )
}

// ─── Empty State ──────────────────────────────────────────────────────────────
interface EmptyStateProps {
  icon?: string
  title: string
  description?: string
  action?: ReactNode
}
export function EmptyState({ icon = '📭', title, description, action }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-16 px-6 text-center"
    >
      <div className="text-4xl mb-4">{icon}</div>
      <div className="text-[15px] font-semibold text-white mb-2">{title}</div>
      {description && <div className="text-[13px] text-[#9CA3AF] mb-4">{description}</div>}
      {action}
    </motion.div>
  )
}

// ─── Error State ──────────────────────────────────────────────────────────────
interface ErrorStateProps {
  message?: string
  onRetry?: () => void
}
export function ErrorState({ message = 'কিছু একটা সমস্যা হয়েছে।', onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <div className="text-4xl mb-4">⚠️</div>
      <div className="text-[14px] text-[#9CA3AF] mb-4">{message}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-5 py-2 rounded-[10px] bg-primary/15 border border-primary/25 text-primary text-[13px] font-medium"
        >
          আবার চেষ্টা করুন
        </button>
      )}
    </div>
  )
}

// ─── Divider ──────────────────────────────────────────────────────────────────
export function Divider({ label }: { label?: string }) {
  if (!label) return <div className="h-px bg-border my-4" />
  return (
    <div className="flex items-center gap-3 my-4 px-4">
      <div className="flex-1 h-px bg-border" />
      <span className="text-[11px] text-[#6B7280]">{label}</span>
      <div className="flex-1 h-px bg-border" />
    </div>
  )
}

// ─── Progress Bar ─────────────────────────────────────────────────────────────
export function ProgressBar({ value, max, className = '' }: { value: number; max: number; className?: string }) {
  const pct = Math.min(100, Math.round((value / max) * 100))
  return (
    <div className={cx('h-[6px] bg-card rounded-full overflow-hidden', className)}>
      <motion.div
        className="h-full rounded-full bg-gradient-blue"
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.4 }}
      />
    </div>
  )
}

// ─── Countdown Timer ─────────────────────────────────────────────────────────

interface CountdownProps {
  expiresAt: string
  onExpire?: () => void
  className?: string
}
export function Countdown({ expiresAt, onExpire, className = '' }: CountdownProps) {
  const [secs, setSecs] = useState(() => {
    const diff = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000))
    return diff
  })

  useEffect(() => {
    if (secs <= 0) { onExpire?.(); return }
    const t = setTimeout(() => setSecs(s => s - 1), 1000)
    return () => clearTimeout(t)
  }, [secs, onExpire])

  return (
    <span className={cx('font-bold tabular-nums', className)}>
      {formatCountdown(secs)}
    </span>
  )
}

// ─── Button ───────────────────────────────────────────────────────────────────
// Thin wrapper over the .btn-* classes in index.css.
interface ButtonProps {
  children: ReactNode
  variant?: 'primary' | 'secondary' | 'success' | 'ghost'
  loading?: boolean
  disabled?: boolean
  onClick?: () => void
  type?: 'button' | 'submit'
  className?: string
}
// Literal class names (not `btn-${variant}`) so Tailwind's content scan keeps them.
const BUTTON_CLASS = {
  primary:   'btn-primary',
  secondary: 'btn-secondary',
  success:   'btn-success',
  ghost:     'btn-ghost',
} as const

export function Button({
  children, variant = 'primary', loading = false, disabled = false,
  onClick, type = 'button', className = '',
}: ButtonProps) {
  return (
    <motion.button
      type={type}
      whileTap={{ scale: 0.98 }}
      disabled={disabled || loading}
      onClick={onClick}
      className={cx(BUTTON_CLASS[variant], (disabled || loading) && 'opacity-60 pointer-events-none', className)}
    >
      {loading && <Spinner size={16} />}
      {children}
    </motion.button>
  )
}

// ─── Section Header ───────────────────────────────────────────────────────────
interface SectionHeaderProps {
  title: string
  actionLabel?: string
  onAction?: () => void
}
export function SectionHeader({ title, actionLabel = 'সব দেখুন →', onAction }: SectionHeaderProps) {
  return (
    <div className="flex items-center justify-between px-4 mb-3">
      <h2 className="text-[15px] font-semibold text-white">{title}</h2>
      {onAction && (
        <button onClick={onAction} className="text-[12px] text-primary font-medium">
          {actionLabel}
        </button>
      )}
    </div>
  )
}

// ─── Filter Chip ──────────────────────────────────────────────────────────────
interface FilterChipProps {
  active: boolean
  onClick: () => void
  children: ReactNode
}
export function FilterChip({ active, onClick, children }: FilterChipProps) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        'px-3 py-[5px] rounded-[20px] text-[11px] font-medium border whitespace-nowrap flex-shrink-0',
        active
          ? 'bg-primary/12 border-primary/40 text-primary'
          : 'bg-card border-border text-[#6B7280]',
      )}
    >
      {children}
    </button>
  )
}

// ─── Load More ────────────────────────────────────────────────────────────────
export function LoadMoreButton({ onClick, loading }: { onClick: () => void; loading: boolean }) {
  return (
    <div className="px-4 mt-4">
      <button
        onClick={onClick}
        disabled={loading}
        className="w-full py-[11px] rounded-[12px] border border-border bg-card text-[#9CA3AF] text-[13px] font-medium disabled:opacity-50"
      >
        {loading ? 'লোড হচ্ছে...' : 'আরও দেখুন'}
      </button>
    </div>
  )
}

// ─── Inline (section-level) error ─────────────────────────────────────────────
export function InlineError({ message = 'লোড করা যায়নি।', onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div className="mx-4 flex items-center justify-between gap-3 bg-danger/8 border border-danger/20 rounded-[10px] px-3 py-[10px]">
      <span className="text-[12px] text-[#FCA5A5]">{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="text-[12px] text-primary font-medium flex-shrink-0">
          আবার চেষ্টা করুন
        </button>
      )}
    </div>
  )
}

// ─── Confirm Sheet (bottom sheet) ─────────────────────────────────────────────
interface ConfirmSheetProps {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  cancelLabel?: string
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}
export function ConfirmSheet({
  open, title, children, confirmLabel, cancelLabel = 'বাতিল', loading = false, onConfirm, onCancel,
}: ConfirmSheetProps) {
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[60] flex items-end" role="dialog" aria-modal="true" aria-label={title}>
          <motion.div
            className="absolute inset-0 bg-black/60"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={loading ? undefined : onCancel}
          />
          <motion.div
            className="relative w-full bg-surface border-t border-border rounded-t-[18px] px-4 pt-4 space-y-3"
            style={{ paddingBottom: 'calc(16px + var(--app-safe-bottom))' }}
            initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }}
            transition={{ type: 'tween', duration: 0.22 }}
          >
            <h3 className="text-[15px] font-bold text-white">{title}</h3>
            {children}
            <div className="flex gap-2 pt-1">
              <button onClick={onCancel} disabled={loading} className="btn-ghost !w-auto px-5 disabled:opacity-50">{cancelLabel}</button>
              <Button onClick={onConfirm} loading={loading} className="flex-1">{confirmLabel}</Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}

// ─── Toast notification (simple) ─────────────────────────────────────────────
let _toastFn: ((msg: string, type?: 'success' | 'error' | 'info') => void) | null = null

export function setToastFn(fn: typeof _toastFn) { _toastFn = fn }
export function toast(msg: string, type: 'success' | 'error' | 'info' = 'info') {
  _toastFn?.(msg, type)
}
