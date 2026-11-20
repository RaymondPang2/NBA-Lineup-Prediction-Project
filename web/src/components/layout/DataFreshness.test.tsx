import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { DataStatus, Prediction } from '../../api/types'
import { freshnessText, fmtUpdated, useRefetchOnNewData } from '../../lib/freshness'
import { fixture } from '../../test/fixtures'
import { renderApp } from '../../test/render'
import { ORIGIN, server } from '../../test/server'

const V1 = `${ORIGIN}/api/v1`
const status = () => fixture<DataStatus>('data-status')

describe('Last updated status', () => {
  it('shows the data cutoff, the last update and that the data is current', async () => {
    renderApp('/?season=2025-26')
    const el = await screen.findByTestId('data-freshness')
    const s = status()
    expect(el).toHaveAttribute('data-state', s.freshness)
    expect(el).toHaveTextContent(freshnessText(s).label)
    expect(el).toHaveAttribute('title', expect.stringContaining('Last updated'))
    expect(screen.queryByTestId('stale-banner')).toBeNull()
  })

  it('warns when the data is stale and says how to refresh it', async () => {
    server.use(
      http.get(`${V1}/data-status`, () =>
        HttpResponse.json({ ...status(), freshness: 'stale', stale_reason: 'data runs through 2026-11-15, expected through 2026-11-18' }),
      ),
    )
    renderApp('/?season=2025-26')
    expect(await screen.findByTestId('data-freshness')).toHaveAttribute('data-state', 'stale')
    const banner = await screen.findByTestId('stale-banner')
    expect(banner).toHaveTextContent('stale')
    expect(banner).toHaveTextContent('python -m nba_lineups.refresh')
  })

  it('hides itself when the status endpoint is unavailable (older API)', async () => {
    server.use(http.get(`${V1}/data-status`, () => HttpResponse.json({ error: { code: 'not_found', message: 'x', details: null } }, { status: 404 })))
    renderApp('/?season=2025-26')
    await screen.findByTestId('api-health')
    expect(screen.queryByTestId('data-freshness')).toBeNull()
  })

  it('formats the update time relative to today', () => {
    const now = new Date('2026-11-20T15:00:00')
    expect(fmtUpdated('2026-11-20T12:02:00Z', now)).toMatch(/^today, /)
    expect(fmtUpdated('2026-11-18T12:02:00Z', now)).toMatch(/^Nov 18, /)
  })
})

describe('Automatic refresh of the dashboard', () => {
  function Probe({ version, onFetch }: { version: number | null; onFetch: () => void }) {
    useRefetchOnNewData(version)
    useQuery({ queryKey: ['team-stats', 'x'], queryFn: () => (onFetch(), 1), staleTime: Infinity })
    return null
  }

  it('refetches cached data only when a refresh loaded a new data version', async () => {
    const client = new QueryClient()
    let fetches = 0
    const ui = (v: number | null) => (
      <QueryClientProvider client={client}>
        <Probe version={v} onFetch={() => fetches++} />
      </QueryClientProvider>
    )
    const { rerender } = render(ui(4))
    await waitFor(() => expect(fetches).toBe(1))
    rerender(ui(4))                                   // same version (no-change refresh): nothing refetched
    await new Promise((r) => setTimeout(r, 20))
    expect(fetches).toBe(1)
    rerender(ui(5))                                   // new data loaded: cached stats are refetched
    await waitFor(() => expect(fetches).toBe(2))
  })
})

describe('Season in progress', () => {
  it('lists the current season and renders its overview without post-break data', async () => {
    renderApp('/')
    expect(await screen.findByText(/Season in progress · provisional/)).toBeInTheDocument()
    expect(await screen.findByTestId('season-to-date')).toHaveTextContent('All-Star break is still ahead')
    expect(await screen.findByText('No post-break games yet')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /in progress/ })).toBeInTheDocument()
  })

  it('labels a current-season prediction provisional and still shows baseline and intervals', async () => {
    const p = fixture<Prediction>('prediction-provisional')
    expect(p.provisional).toBe(true)
    const { PredictionResult } = await import('../prediction/PredictionResult')
    const { MemoryRouter } = await import('react-router')
    render(
      <MemoryRouter>
        <PredictionResult prediction={p} />
      </MemoryRouter>,
    )
    expect(screen.getByText(/Provisional · season in progress/)).toBeInTheDocument()
    expect(screen.getByTestId('provisional-notice')).toHaveTextContent('not independently validated')
    expect(screen.getByTestId('provisional-notice')).toHaveTextContent('post-All-Star-break net rating')
    expect(screen.getByTestId('team-prior')).toBeInTheDocument()
    expect(screen.getByTestId('predicted-net')).toBeInTheDocument()
    expect(screen.getByText(/95% true-quality interval/)).toBeInTheDocument()
  })
})
