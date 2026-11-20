import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { LineupRanking, PredictionRanking } from '../api/types'
import { fmtSigned, lastName } from '../lib/format'
import { fixture } from '../test/fixtures'
import { renderApp } from '../test/render'
import { ORIGIN, server } from '../test/server'

const V1 = `${ORIGIN}/api/v1`

describe('Rankings: actual results', () => {
  it('is in the main navigation and lists the API ranking with rank, team, players and ratings', async () => {
    renderApp('/rankings?season=2025-26')
    expect(screen.getAllByRole('link', { name: 'Rankings' }).length).toBeGreaterThan(0)
    const r = fixture<LineupRanking>('rank-lineups')
    const table = await screen.findByRole('region', { name: 'Lineup ranking' })
    const rows = within(table).getAllByTestId('rank-row')
    expect(rows).toHaveLength(r.items.length)
    const first = r.items[0]
    expect(rows[0]).toHaveTextContent(String(first.rank))
    expect(rows[0]).toHaveTextContent(first.team_abbreviation)
    expect(rows[0]).toHaveTextContent(fmtSigned(first.net_rating))
    for (const p of first.players) expect(rows[0]).toHaveTextContent(lastName(p.player_name))
    const link = within(rows[0]).getAllByRole('link').find((a) => a.getAttribute('href') === `/lineups/${first.lineup_id}`)
    expect(link).toBeTruthy()
    expect(screen.getByTestId('ranking-summary')).toHaveTextContent('Full season')
    expect(screen.getByTestId('ranking-summary')).toHaveTextContent(`${r.total.toLocaleString()} lineups`)
  })

  it('re-ranks by a column header and remembers it in the URL', async () => {
    renderApp('/rankings?season=2025-26')
    const table = await screen.findByRole('region', { name: 'Lineup ranking' })
    await userEvent.click(within(table).getByRole('button', { name: /DRtg/ }))
    await waitFor(() => expect(screen.getByTestId('ranking-summary')).toHaveTextContent('Best defensive rating'))
    expect(screen.getByRole('radio', { name: 'Defense' })).toHaveAttribute('aria-checked', 'true')
  })

  it('warns about small samples below 100 possessions', async () => {
    renderApp('/rankings?season=2025-26&min=25')
    expect(await screen.findByText('Small samples can top this ranking')).toBeInTheDocument()
  })

  it('explains an unavailable post-break window instead of showing an empty table', async () => {
    renderApp('/rankings?window=post')
    expect(await screen.findByText('No post-break games yet')).toBeInTheDocument()
  })

  it('shows API errors with a retry', async () => {
    server.use(http.get(`${V1}/rankings/lineups`, () => HttpResponse.error()))
    renderApp('/rankings?season=2025-26')
    expect(await screen.findByText('Cannot reach the API')).toBeInTheDocument()
  })
})

describe('Rankings: model predictions', () => {
  it('shows prediction, baseline, interval and the verdict and uncertainty disclosures', async () => {
    renderApp('/rankings?season=2025-26&mode=predicted')
    const r = fixture<PredictionRanking>('rank-predictions')
    const table = await screen.findByRole('region', { name: 'Prediction ranking' })
    const row = within(table).getAllByTestId('rank-row')[0]
    const top = r.items[0]
    expect(row).toHaveTextContent(fmtSigned(top.predicted_net_rating))
    expect(row).toHaveTextContent(fmtSigned(top.team_prior))
    expect(row).toHaveTextContent(fmtSigned(top.model_minus_team_prior))
    expect(screen.getByTestId('estimand-notice')).toHaveTextContent('not statistically better than the team-prior baseline')
    expect(screen.getByTestId('estimand-notice')).toHaveTextContent('does not predict whether, or how much, the lineup will be used')
    expect(screen.getByTestId('uncertainty-notice')).toHaveTextContent(`±${r.interval_half_width.toFixed(1)}`)
    expect(screen.getByTestId('uncertainty-notice')).toHaveTextContent('Only recorded lineups are ranked')
    expect(screen.getByText('Recorded lineup')).toBeInTheDocument()
    expect(screen.queryByText('In-sample season')).toBeNull()                   // 2025-26 is held out, not training
  })

  it('labels the season in progress provisional', async () => {
    renderApp('/rankings?mode=predicted')
    expect(await screen.findByTestId('provisional-notice')).toHaveTextContent('not independently validated')
  })
})
