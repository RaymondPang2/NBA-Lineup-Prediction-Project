import clsx from 'clsx'
import { useDataStatus } from '../../api/hooks'
import { freshnessText, fmtUpdated, shortDate, useRefetchOnNewData } from '../../lib/freshness'

/** Compact "Last updated" status for the header. */
export function DataFreshness() {
  const q = useDataStatus()
  useRefetchOnNewData(q.data?.data_version)
  if (q.isPending || q.error || !q.data) return null
  const s = q.data
  const { label, detail } = freshnessText(s)
  const state = s.freshness
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-ink-2" title={detail} data-testid="data-freshness" data-state={state}>
      <span
        aria-hidden
        className={clsx(
          'inline-block size-2 shrink-0 rounded-full',
          state === 'current' && 'bg-[var(--good)]',
          state === 'stale' && 'bg-[var(--warn)]',
          state === 'unknown' && 'bg-[var(--muted)]',
        )}
      />
      <span className="truncate">
        <span className="hidden lg:inline">{state === 'stale' ? 'Stale · ' : ''}</span>
        <span className="sm:hidden">{s.data_cutoff ? shortDate(s.data_cutoff) : label}</span>
        <span className="hidden sm:inline">{label}</span>
        {s.last_updated_at && <span className="hidden lg:inline"> · updated {fmtUpdated(s.last_updated_at)}</span>}
      </span>
      <span className="sr-only">{detail}</span>
    </span>
  )
}

/** A slim bar under the header while the data is stale, with what to do about it. */
export function StaleBanner() {
  const q = useDataStatus()
  const s = q.data
  if (!s || s.freshness !== 'stale') return null
  return (
    <div role="status" className="border-b border-line bg-warn-bg text-warn" data-testid="stale-banner">
      <p className="mx-auto max-w-7xl px-4 py-2 text-xs sm:px-6">
        <strong className="font-semibold">{s.season_id} data is stale.</strong> {s.stale_reason} Refresh from a terminal with{' '}
        <code className="rounded bg-surface/60 px-1 font-mono">{s.refresh_command}</code>.
      </p>
    </div>
  )
}
