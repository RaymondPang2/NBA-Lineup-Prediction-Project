import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useSearchParams } from 'react-router'
import { useHealth } from '../../api/hooks'
import { isDemo, REPO_URL } from '../../lib/demo'
import { DataFreshness, StaleBanner } from './DataFreshness'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/lineups', label: 'Lineups' },
  { to: '/rankings', label: 'Rankings' },
  { to: '/predict', label: 'Predict' },
  { to: '/insights', label: 'Insights' },
  { to: '/model', label: 'Model' },
]

type Theme = 'system' | 'light' | 'dark'

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('theme')
    return t === 'light' || t === 'dark' ? t : 'system'
  } catch {
    return 'system'
  }
}

function useTheme() {
  const [theme, setTheme] = useState<Theme>(readTheme)
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try {
      if (theme === 'system') localStorage.removeItem('theme')
      else localStorage.setItem('theme', theme)
    } catch {
      /* storage unavailable: the choice lasts for this page view */
    }
  }, [theme])
  return [theme, setTheme] as const
}

function ThemeToggle() {
  const [theme, setTheme] = useTheme()
  const next: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' }
  const label = { system: 'System theme', light: 'Light theme', dark: 'Dark theme' }[theme]
  return (
    <button
      type="button"
      onClick={() => setTheme(next[theme])}
      className="inline-flex size-9 items-center justify-center rounded-md text-ink-2 hover:bg-surface-2 hover:text-ink"
      aria-label={`${label}. Switch theme`}
      title={label}
    >
      <svg viewBox="0 0 20 20" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
        {theme === 'light' ? (
          <>
            <circle cx="10" cy="10" r="3.5" />
            <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4" strokeLinecap="round" />
          </>
        ) : theme === 'dark' ? (
          <path d="M16.5 12.5A7 7 0 0 1 7.5 3.5a7 7 0 1 0 9 9Z" strokeLinejoin="round" />
        ) : (
          <>
            <rect x="2.5" y="3.5" width="15" height="10" rx="1.5" />
            <path d="M7 17h6M10 13.5V17" strokeLinecap="round" />
          </>
        )}
      </svg>
    </button>
  )
}

function HealthDot() {
  const h = useHealth()
  const ok = h.data?.status === 'ok'
  const state = h.isPending ? 'checking' : h.error ? 'offline' : ok ? 'online' : 'degraded'
  const text = {
    checking: 'Checking API…',
    offline: 'API offline',
    online: 'API online',
    degraded: `API degraded (database: ${h.data?.database}, model: ${h.data?.model})`,
  }[state]
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2" title={text} data-testid="api-health" data-state={state}>
      <span
        aria-hidden
        className={clsx(
          'inline-block size-2 rounded-full',
          state === 'online' && 'bg-[var(--good)]',
          state === 'degraded' && 'bg-[var(--warn)]',
          state === 'offline' && 'bg-[var(--bad)]',
          state === 'checking' && 'bg-[var(--muted)]',
        )}
      />
      <span className="hidden sm:inline">{state === 'degraded' ? 'API degraded' : text}</span>
      <span className="sr-only sm:hidden">{text}</span>
    </span>
  )
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const [params] = useSearchParams()
  // Carry the season across pages so the context stays put while navigating.
  const season = params.get('season')
  const withSeason = (to: string) => (season ? `${to}?season=${encodeURIComponent(season)}` : to)

  useEffect(() => {
    setMenuOpen(false)
    window.scrollTo?.({ top: 0 })
  }, [location.pathname])

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    clsx('rounded-md px-3 py-2 text-sm font-medium transition-colors', isActive ? 'bg-accent-soft text-accent' : 'text-ink-2 hover:bg-surface-2 hover:text-ink')

  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur supports-[backdrop-filter]:bg-surface/75">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
          <NavLink to={withSeason('/')} className="flex shrink-0 items-center gap-2 font-semibold tracking-tight whitespace-nowrap text-ink">
            <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
              <rect width="32" height="32" rx="7" fill="var(--accent)" />
              <circle cx="16" cy="16" r="9" fill="none" stroke="var(--accent-ink)" strokeWidth="2" />
              <path d="M7 16h18M16 7v18" stroke="var(--accent-ink)" strokeWidth="2" />
            </svg>
            <span>Lineup Lab</span>
          </NavLink>
          <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
            {NAV.map((n) => (
              <NavLink key={n.to} to={withSeason(n.to)} end={n.end} className={linkClass}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex min-w-0 items-center gap-3">
            {!isDemo() && <DataFreshness />}
            <HealthDot />
            <ThemeToggle />
            <button
              type="button"
              className="inline-flex size-9 items-center justify-center rounded-md text-ink-2 hover:bg-surface-2 md:hidden"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              onClick={() => setMenuOpen((o) => !o)}
            >
              <svg viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
                {menuOpen ? <path d="M5 5l10 10M15 5 5 15" strokeLinecap="round" /> : <path d="M3 6h14M3 10h14M3 14h14" strokeLinecap="round" />}
              </svg>
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav id="mobile-nav" aria-label="Main" className="border-t border-line px-4 py-2 md:hidden">
            <div className="flex flex-col gap-1">
              {NAV.map((n) => (
                <NavLink key={n.to} to={withSeason(n.to)} end={n.end} className={linkClass}>
                  {n.label}
                </NavLink>
              ))}
            </div>
          </nav>
        )}
      </header>
      {isDemo() ? (
        <div role="note" className="border-b border-line bg-warn-bg text-warn" data-testid="demo-banner">
          <p className="mx-auto max-w-7xl px-4 py-2 text-xs sm:px-6">
            <strong className="font-semibold">Synthetic demo data.</strong> Teams, players and statistics on this public site are fictional, generated to mirror NBA lineup
            data, because NBA statistics may only be used privately. The pipeline, frozen model and dashboard are the real ones.{' '}
            <a href={REPO_URL} className="underline underline-offset-2" target="_blank" rel="noreferrer">
              Source and real-data results on GitHub
            </a>
            .
          </p>
        </div>
      ) : (
        <StaleBanner />
      )}

      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
        <Outlet />
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto max-w-7xl space-y-1 px-4 py-6 text-xs text-muted sm:px-6">
          {isDemo() ? (
            <p data-testid="demo-footer">
              Public demo on synthetic data: every team, player and statistic is fictional. Ratings are points per 100 possessions, computed from summed totals. The
              model-performance results were measured on real NBA data (NBA.com/stats) during private, non-commercial development. Not affiliated with the NBA.
            </p>
          ) : (
          <p>
            Statistics from <a className="underline-offset-2 hover:underline" href="https://www.nba.com/stats" target="_blank" rel="noreferrer">NBA.com/stats</a> via the
            open-source nba_api client: regular seasons 2018-19 to 2025-26, plus 2026-27 season to date (refreshed daily on this machine). Ratings are points per 100 possessions, computed from summed totals. Personal, non-commercial
            educational project; NBA data is owned by the NBA.
          </p>
          )}
          <p>
            Predictions are conditional on a lineup playing after the All-Star break and are always shown with the team-prior baseline and 95% intervals.
            {!isDemo() && ' Predictions for the season in progress are provisional.'}
          </p>
        </div>
      </footer>
    </div>
  )
}
