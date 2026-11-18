import { useState, type ReactNode } from 'react'
import { Card, CardBody, CardHeader } from '../ui/Card'
import { Segmented } from '../ui/Controls'

export interface LegendItem {
  label: string
  color: string
  shape?: 'dot' | 'line' | 'band' | 'dash'
}

export function Legend({ items }: { items: LegendItem[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2" aria-label="Legend">
      {items.map((it) => (
        <li key={it.label} className="inline-flex items-center gap-1.5">
          {it.shape === 'line' ? (
            <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ background: it.color }} />
          ) : it.shape === 'dash' ? (
            <span aria-hidden className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: it.color }} />
          ) : it.shape === 'band' ? (
            <span aria-hidden className="inline-block h-2.5 w-4 rounded-sm" style={{ background: it.color }} />
          ) : (
            <span aria-hidden className="inline-block size-2.5 rounded-full" style={{ background: it.color }} />
          )}
          {it.label}
        </li>
      ))}
    </ul>
  )
}

/**
 * Card around a chart with a Chart/Table switch. The table view carries every plotted value as text,
 * which is the accessible alternative and the relief for low-contrast series colors.
 */
export function ChartFrame({
  title,
  subtitle,
  legend,
  table,
  children,
  footer,
  actions,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  legend?: LegendItem[]
  table?: ReactNode
  children: ReactNode
  footer?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  return (
    <Card className={className}>
      <CardHeader
        title={title}
        subtitle={subtitle}
        actions={
          <>
            {actions}
            {table && (
              <Segmented
                size="sm"
                label="View"
                value={view}
                onChange={setView}
                options={[
                  { value: 'chart', label: 'Chart' },
                  { value: 'table', label: 'Table' },
                ]}
              />
            )}
          </>
        }
      />
      <CardBody>
        {legend && legend.length > 1 && view === 'chart' && (
          <div className="mb-3">
            <Legend items={legend} />
          </div>
        )}
        {view === 'chart' ? children : <div className="max-h-[420px] overflow-auto">{table}</div>}
        {footer && <div className="mt-3 text-xs text-muted">{footer}</div>}
      </CardBody>
    </Card>
  )
}

/** Themed tooltip body for Recharts' `content` prop. */
export function TooltipBox({ title, rows }: { title?: ReactNode; rows: { label: string; value: ReactNode; color?: string }[] }) {
  return (
    <div className="pointer-events-none max-w-72 rounded-md border border-line-strong bg-surface px-3 py-2 text-xs shadow-lg">
      {title && <p className="mb-1 font-semibold text-ink">{title}</p>}
      <dl className="tabular grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
        {rows.map((r) => (
          <div key={r.label} className="contents">
            <dt className="inline-flex items-center gap-1.5 text-ink-2">
              {r.color && <span aria-hidden className="inline-block size-2 rounded-full" style={{ background: r.color }} />}
              {r.label}
            </dt>
            <dd className="text-right font-medium text-ink">{r.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Chart colors as CSS variables, so charts follow the theme with no re-render. */
export const C = {
  s1: 'var(--series-1)',
  s2: 'var(--series-2)',
  s3: 'var(--series-3)',
  pos: 'var(--div-pos)',
  neg: 'var(--div-neg)',
  muted: 'var(--muted)',
  axis: 'var(--axis)',
  grid: 'var(--grid)',
  ink: 'var(--ink)',
  ink2: 'var(--ink-2)',
  surface: 'var(--surface)',
  band1: 'var(--band-1)',
  band2: 'var(--band-2)',
} as const

export const AXIS_TICK = { fontSize: 12 }
