import clsx from 'clsx'
import type { ReactNode, ThHTMLAttributes } from 'react'
import { Button, Select } from './Controls'

export type SortOrder = 'asc' | 'desc'

/** Horizontally scrollable table container: the table scrolls, never the page. */
export function TableWrap({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="-mx-4 overflow-x-auto sm:mx-0" role="region" aria-label={label} tabIndex={0}>
      <table className="tabular w-full min-w-max border-collapse text-sm">{children}</table>
    </div>
  )
}

export function Th({ children, align = 'right', className, ...rest }: ThHTMLAttributes<HTMLTableCellElement> & { align?: 'left' | 'right' | 'center' }) {
  return (
    <th
      scope="col"
      {...rest}
      className={clsx(
        'border-b border-line-strong px-3 py-2 text-xs font-medium tracking-wide whitespace-nowrap text-muted uppercase first:pl-4 last:pr-4 sm:first:pl-3 sm:last:pr-3',
        align === 'left' ? 'text-left' : align === 'center' ? 'text-center' : 'text-right',
        className,
      )}
    >
      {children}
    </th>
  )
}

export function Td({ children, align = 'right', className }: { children: ReactNode; align?: 'left' | 'right' | 'center'; className?: string }) {
  return (
    <td
      className={clsx(
        'border-b border-line px-3 py-2.5 whitespace-nowrap first:pl-4 last:pr-4 sm:first:pl-3 sm:last:pr-3',
        align === 'left' ? 'text-left' : align === 'center' ? 'text-center' : 'text-right',
        className,
      )}
    >
      {children}
    </td>
  )
}

/** A column header that sorts. aria-sort reflects the current state for screen readers. */
export function SortTh<K extends string>({
  label,
  sortKey,
  sort,
  order,
  onSort,
  align = 'right',
  title,
  defaultOrder = 'desc',
}: {
  label: ReactNode
  sortKey: K
  sort: K
  order: SortOrder
  onSort: (key: K, order: SortOrder) => void
  align?: 'left' | 'right'
  title?: string
  defaultOrder?: SortOrder
}) {
  const active = sort === sortKey
  const next: SortOrder = active ? (order === 'desc' ? 'asc' : 'desc') : defaultOrder
  return (
    <Th align={align} aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'} title={title}>
      <button
        type="button"
        onClick={() => onSort(sortKey, next)}
        className={clsx('inline-flex items-center gap-1 uppercase hover:text-ink', active && 'text-ink', align === 'right' && 'flex-row-reverse')}
      >
        {label}
        <span aria-hidden className={clsx('text-[9px]', !active && 'opacity-30')}>
          {active ? (order === 'asc' ? '▲' : '▼') : '▼'}
        </span>
      </button>
    </Th>
  )
}

export function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  onPage,
  onPageSize,
  noun = 'rows',
}: {
  page: number
  totalPages: number
  total: number
  pageSize: number
  onPage: (p: number) => void
  onPageSize?: (n: number) => void
  noun?: string
}) {
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1
  const last = Math.min(total, page * pageSize)
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3 pt-4 text-sm text-ink-2">
      <p className="tabular">
        {first.toLocaleString()}–{last.toLocaleString()} of <span className="font-medium text-ink">{total.toLocaleString()}</span> {noun}
      </p>
      <div className="flex items-center gap-2">
        {onPageSize && (
          <label className="flex items-center gap-2">
            <span className="sr-only">Rows per page</span>
            <Select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))} className="h-8 w-20 text-sm" aria-label="Rows per page">
              {[25, 50, 100, 200].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </label>
        )}
        <Button size="sm" variant="secondary" onClick={() => onPage(page - 1)} disabled={page <= 1} aria-label="Previous page">
          ‹ Prev
        </Button>
        <span className="tabular px-1">
          {page} / {Math.max(1, totalPages)}
        </span>
        <Button size="sm" variant="secondary" onClick={() => onPage(page + 1)} disabled={page >= totalPages} aria-label="Next page">
          Next ›
        </Button>
      </div>
    </nav>
  )
}
