import type { ReactNode } from 'react'
import { ApiError } from '../../api/client'
import { Button } from './Controls'

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span role="status" aria-live="polite" className="inline-flex items-center gap-2 text-sm text-muted">
      <svg className="size-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden>
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
      {label}…
    </span>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded-md bg-surface-3 ${className}`} />
}

/** Placeholder with the shape of the content it replaces, plus an accessible status. */
export function LoadingBlock({ label = 'Loading', height = 'h-64' }: { label?: string; height?: string }) {
  return (
    <div className={`relative flex ${height} w-full items-center justify-center overflow-hidden rounded-lg bg-surface-2`}>
      <Skeleton className="absolute inset-0 rounded-lg opacity-60" />
      <div className="relative">
        <Spinner label={label} />
      </div>
    </div>
  )
}

function describe(error: unknown): { title: string; message: string; hint?: string } {
  if (error instanceof ApiError) {
    if (error.status === 0)
      return {
        title: 'Cannot reach the API',
        message: error.message,
        hint: 'Start it with: .venv/bin/uvicorn nba_lineups.api.main:app',
      }
    if (error.code === 'database_unavailable')
      return { title: 'Database unavailable', message: error.message, hint: 'Start PostgreSQL with: docker compose up -d' }
    if (error.code === 'model_unavailable') return { title: 'Model unavailable', message: error.message }
    if (error.status === 404) return { title: 'Not found', message: error.message }
    if (error.status === 504) return { title: 'The query took too long', message: error.message }
    return { title: `Request failed (${error.status})`, message: error.message }
  }
  return { title: 'Something went wrong', message: error instanceof Error ? error.message : String(error) }
}

export function ErrorState({ error, onRetry, compact = false }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const { title, message, hint } = describe(error)
  return (
    <div role="alert" className={`rounded-lg border border-bad/30 bg-bad-bg ${compact ? 'p-3' : 'p-5'}`}>
      <div className="flex items-start gap-3">
        <svg viewBox="0 0 20 20" className="mt-0.5 size-5 shrink-0 text-bad" fill="currentColor" aria-hidden>
          <path d="M10 1.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Zm0 4a1 1 0 0 1 1 1v4a1 1 0 1 1-2 0v-4a1 1 0 0 1 1-1Zm0 9.25a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5Z" />
        </svg>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-ink">{title}</p>
          <p className="mt-0.5 text-sm break-words text-ink-2">{message}</p>
          {hint && <p className="mt-1 font-mono text-xs break-all text-muted">{hint}</p>}
          {onRetry && (
            <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
              Try again
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line-strong px-6 py-10 text-center">
      <svg viewBox="0 0 24 24" className="size-8 text-muted" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" strokeLinecap="round" />
      </svg>
      <p className="mt-3 font-semibold text-ink">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-ink-2">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

/** Render a query's loading / error / data states uniformly. */
export function QueryState<T>({
  query,
  children,
  loading,
}: {
  query: { data: T | undefined; isPending: boolean; error: unknown; refetch: () => unknown }
  children: (data: T) => ReactNode
  loading?: ReactNode
}) {
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  if (query.isPending || query.data === undefined) return <>{loading ?? <LoadingBlock />}</>
  return <>{children(query.data)}</>
}
