import clsx from 'clsx'
import type { ReactNode } from 'react'

export function Card({ children, className, as: Tag = 'section' }: { children: ReactNode; className?: string; as?: 'section' | 'div' | 'article' }) {
  return <Tag className={clsx('min-w-0 rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]', className)}>{children}</Tag>
}

export function CardHeader({ title, subtitle, actions, id }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 px-4 pt-4 sm:px-5 sm:pt-5">
      <div className="min-w-0">
        <h2 id={id} className="text-base font-semibold text-ink">
          {title}
        </h2>
        {subtitle && <p className="mt-0.5 text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex max-w-full min-w-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx('px-4 pt-3 pb-4 sm:px-5 sm:pb-5', className)}>{children}</div>
}

export function PageHeader({ title, description, children, leading }: { title: string; description?: ReactNode; children?: ReactNode; leading?: ReactNode }) {
  return (
    <header className="mb-6">
      <div className="flex min-w-0 items-center gap-3">
        {leading}
        <h1 className="min-w-0 text-2xl font-semibold tracking-tight text-ink sm:text-[28px]">{title}</h1>
      </div>
      {description && <div className="mt-1.5 max-w-3xl text-[15px] text-ink-2">{description}</div>}
      {children && <div className="mt-4">{children}</div>}
    </header>
  )
}

/** One row of filters above the content. Wraps on narrow screens. */
export function FilterBar({ children }: { children: ReactNode }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 rounded-xl border border-line bg-surface p-3 sm:flex sm:flex-wrap sm:items-end sm:p-4 sm:[&>*]:w-44">
      {children}
    </div>
  )
}

/** KPI tile: label, a value, optional detail line. */
export function Stat({ label, value, detail, emphasis = false, testId }: { label: string; value: ReactNode; detail?: ReactNode; emphasis?: boolean; testId?: string }) {
  return (
    <div className={clsx('min-w-0 rounded-lg border px-4 py-3', emphasis ? 'border-accent/40 bg-accent-soft' : 'border-line bg-surface')}>
      <p className="text-xs font-medium tracking-wide text-muted uppercase">{label}</p>
      <p data-testid={testId} className="mt-1 text-2xl font-semibold tracking-tight text-ink">
        {value}
      </p>
      {detail && <p className="mt-0.5 text-xs text-ink-2">{detail}</p>}
    </div>
  )
}

export function Badge({ children, tone = 'neutral', title }: { children: ReactNode; tone?: 'neutral' | 'accent' | 'good' | 'warn' | 'bad'; title?: string }) {
  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap',
        tone === 'neutral' && 'bg-surface-3 text-ink-2',
        tone === 'accent' && 'bg-accent-soft text-accent',
        tone === 'good' && 'bg-good-bg text-good',
        tone === 'warn' && 'bg-warn-bg text-warn',
        tone === 'bad' && 'bg-bad-bg text-bad',
      )}
    >
      {children}
    </span>
  )
}

export function Callout({ tone = 'info', title, children, icon }: { tone?: 'info' | 'warn'; title?: ReactNode; children: ReactNode; icon?: ReactNode }) {
  return (
    <div className={clsx('flex gap-3 rounded-lg border p-4 text-sm', tone === 'info' ? 'border-accent/25 bg-info-bg' : 'border-warn/30 bg-warn-bg')}>
      <span aria-hidden className={clsx('mt-0.5 shrink-0', tone === 'info' ? 'text-accent' : 'text-warn')}>
        {icon ?? (
          <svg viewBox="0 0 20 20" className="size-5" fill="currentColor">
            {tone === 'info' ? (
              <path d="M10 1.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Zm0 4.25a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5ZM11 14.5H9V9.5h2v5Z" />
            ) : (
              <path d="M10.9 2.5a1 1 0 0 0-1.8 0L1.6 16a1 1 0 0 0 .9 1.5h15a1 1 0 0 0 .9-1.5L10.9 2.5ZM9 7h2v5H9V7Zm1 8.5a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5Z" />
            )}
          </svg>
        )}
      </span>
      <div className="min-w-0 text-ink-2">
        {title && <p className="mb-0.5 font-semibold text-ink">{title}</p>}
        {children}
      </div>
    </div>
  )
}

/** A signed difference with an arrow, so direction is never carried by color alone. */
export function Delta({ value, digits = 1, goodWhen = 'up', format }: { value: number | null | undefined; digits?: number; goodWhen?: 'up' | 'down' | 'none'; format: (x: number | null | undefined, d?: number) => string }) {
  if (value === null || value === undefined || !Number.isFinite(value)) return <span className="text-muted">—</span>
  const r = Number(value.toFixed(digits))
  const dir = r > 0 ? 'up' : r < 0 ? 'down' : 'flat'
  const tone = goodWhen === 'none' || dir === 'flat' ? 'text-ink-2' : dir === goodWhen ? 'text-good' : 'text-bad'
  return (
    <span className={clsx('tabular inline-flex items-center gap-0.5 whitespace-nowrap', tone)}>
      <span aria-hidden className="text-[10px]">{dir === 'up' ? '▲' : dir === 'down' ? '▼' : '■'}</span>
      {format(value, digits)}
    </span>
  )
}
