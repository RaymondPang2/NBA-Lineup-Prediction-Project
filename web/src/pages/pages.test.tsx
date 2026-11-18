import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { LineupDetail, LineupSummary, ModelCard, ModelPerformance, Page, Prediction, TeamSeason } from '../api/types'
import { fmtSigned, lastName } from '../lib/format'
import { fixture } from '../test/fixtures'
import { renderApp } from '../test/render'
import { ORIGIN, server } from '../test/server'

const V1 = `${ORIGIN}/api/v1`
const label = (l: LineupSummary) => l.players.map((p) => lastName(p.player_name)).join(' · ')

describe('Overview', () => {
  it('shows every team of the season from the API, sortable, and reports API health', async () => {
    renderApp('/')
    const teams = fixture<TeamSeason[]>('team-stats-2025-26')
    const table = await screen.findByRole('region', { name: 'Team ratings' })
    for (const t of teams) expect(within(table).getByText(t.team_name)).toBeInTheDocument()
    expect(await screen.findByTestId('api-health')).toHaveAttribute('data-state', 'online')

    // Default sort: pre-break net, best first
    const best = [...teams].sort((a, b) => (b.pre_break.net_rating ?? 0) - (a.pre_break.net_rating ?? 0))[0]
    const firstRow = within(table).getAllByRole('row')[1]
    expect(firstRow).toHaveTextContent(best.team_name)
    await userEvent.click(within(table).getByRole('button', { name: /Pre net/ }))
    const worst = [...teams].sort((a, b) => (a.pre_break.net_rating ?? 0) - (b.pre_break.net_rating ?? 0))[0]
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent(worst.team_name)
  })

  it('focuses on a team when selected', async () => {
    renderApp('/?season=2025-26&team=1610612750')
    expect(await screen.findByRole('heading', { level: 1, name: /Minnesota Timberwolves · 2025-26/ })).toBeInTheDocument()
    expect(await screen.findByText('Most-used lineups')).toBeInTheDocument()
  })

  it('shows a helpful error when the API is unreachable', async () => {
    server.use(http.get(`${V1}/seasons`, () => HttpResponse.error()))
    renderApp('/')
    expect(await screen.findByText('Cannot reach the API')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('Lineup explorer', () => {
  it('lists real lineups, sorts on the server, and paginates', async () => {
    const page = fixture<Page<LineupSummary>>('lineups-min')
    const requests: URL[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.url.includes('/api/v1/lineups?')) requests.push(new URL(request.url))
    })
    renderApp('/lineups?season=2025-26&team=1610612750')
    expect(await screen.findByText(label(page.items[0]))).toBeInTheDocument()
    expect(screen.getByText((_, el) => el?.tagName === 'P' && el.textContent === `${page.total.toLocaleString()} lineups`)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Pre net/ }))
    const sorted = fixture<Page<LineupSummary>>('lineups-min-sorted-net')
    await waitFor(() => expect(screen.getAllByRole('row')[1]).toHaveTextContent(label(sorted.items[0])))
    expect(requests.at(-1)!.searchParams.get('sort')).toBe('pre_net')

    if (page.total_pages > 1) {
      await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
      await waitFor(() => expect(requests.at(-1)!.searchParams.get('page')).toBe('2'))
    }
    server.events.removeAllListeners()
  })

  it('sends the possession thresholds and player filters to the API', async () => {
    const requests: URL[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.url.includes('/api/v1/lineups?')) requests.push(new URL(request.url))
    })
    renderApp('/lineups?season=2025-26&team=1610612750&min_pre=100&min_post=50&player=1630162')
    await screen.findByRole('region', { name: 'Lineups' })
    const q = requests.at(-1)!.searchParams
    expect(q.get('min_pre_poss')).toBe('100')
    expect(q.get('min_post_poss')).toBe('50')
    expect(q.getAll('player_id')).toEqual(['1630162'])
    expect(await screen.findByText('Anthony Edwards')).toBeInTheDocument() // the chip resolves the name from /players/{id}
    server.events.removeAllListeners()
  })

  it('searches players by name and adds them as a filter', async () => {
    renderApp('/lineups?season=2025-26')
    const box = await screen.findByRole('combobox', { name: 'Lineups with players' })
    await waitFor(() => expect(box).toBeEnabled()) // enabled once the season list has loaded
    await userEvent.type(box, 'edw')
    const option = await screen.findByRole('option', { name: /Anthony Edwards/ })
    await userEvent.click(option)
    expect(await screen.findByRole('button', { name: 'Remove Anthony Edwards' })).toBeInTheDocument()
  })

  it('shows an empty state when nothing matches', async () => {
    renderApp('/lineups?season=2025-26&team=1610612750&min_pre=5000')
    expect(await screen.findByText('No lineups match these filters')).toBeInTheDocument()
  })
})

describe('Lineup detail', () => {
  it('shows pre-, post-break and season ratings with the noise test', async () => {
    const l = fixture<LineupDetail>('lineup')
    renderApp(`/lineups/${l.lineup_id}`)
    expect(await screen.findByRole('heading', { level: 1, name: l.players.map((p) => p.player_name).join(' · ') })).toBeInTheDocument()
    expect(screen.getAllByText(fmtSigned(l.pre_break!.net_rating)).length).toBeGreaterThan(0)
    expect(screen.getAllByText(fmtSigned(l.post_break!.net_rating)).length).toBeGreaterThan(0)
    expect(screen.getByText(l.change!.exceeds_noise ? 'A change larger than noise' : 'A change within noise')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /frozen-model prediction/ })).toHaveAttribute('href', `/predict?season=${l.season_id}&team=${l.team_id}&lineup=${l.lineup_id}`)
  })

  it('reports an unknown lineup', async () => {
    renderApp('/lineups/999999999')
    expect(await screen.findByText('Not found')).toBeInTheDocument()
  })
})

describe('Predict', () => {
  it('asks for a team before anything else', async () => {
    renderApp('/predict?season=2025-26')
    expect(await screen.findByText('Choose a season and a team')).toBeInTheDocument()
    expect(screen.queryByTestId('predicted-net')).not.toBeInTheDocument()
  })

  it('predicts a recorded lineup chosen from the list, with baseline and intervals', async () => {
    const pred = fixture<Prediction>('prediction-no-observed')
    renderApp('/predict?season=2025-26&team=1610612750')
    expect(await screen.findByText('No lineup selected')).toBeInTheDocument()
    const list = await screen.findByRole('listbox', { name: 'Recorded lineups' })
    const target = fixture<Page<LineupSummary>>('lineups-min').items.find((l) => l.lineup_id === pred.lineup_id)!
    await userEvent.click(within(list).getByText(label(target)))
    expect(await screen.findByTestId('predicted-net')).toHaveTextContent(fmtSigned(pred.predicted_net_rating))
    expect(screen.getByTestId('team-prior')).toHaveTextContent(fmtSigned(pred.baselines.team_prior))
    expect(screen.getByText('Prediction and uncertainty')).toBeInTheDocument()
    expect(screen.getAllByTestId('estimand-notice').length).toBeGreaterThan(0)
  })

  it('builds a hypothetical five and predicts it', async () => {
    const body = fixture<{ files: Record<string, { body?: { player_ids: number[] } }> }>('manifest').files['prediction-five'].body!
    const five = fixture<Prediction>('prediction-five')
    let sent: unknown = null
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST') sent = await request.clone().json()
    })
    renderApp('/predict?season=2025-26&team=1610612750&mode=build')
    const list = await screen.findByRole('list', { name: 'Players' })
    for (const id of body.player_ids) {
      const name = five.players.find((p) => p.player_id === id)!.player_name
      await userEvent.click(within(list).getByRole('checkbox', { name: new RegExp(name) }))
    }
    expect(await screen.findByTestId('predicted-net')).toHaveTextContent(fmtSigned(five.predicted_net_rating))
    expect(screen.getByText(/Hypothetical lineup/)).toBeInTheDocument()
    expect((sent as { player_ids: number[] }).player_ids.sort()).toEqual([...body.player_ids].sort())
    server.events.removeAllListeners()
  })
})

describe('Model performance', () => {
  it('shows the held-out verdict, every evaluation and the verified artifact', async () => {
    const perf = fixture<ModelPerformance>('model-performance')
    const card = fixture<ModelCard>('model')
    renderApp('/model')
    expect(await screen.findByTestId('conclusion')).toHaveTextContent(perf.conclusion)
    expect(screen.getByText(perf.beats_team_prior ? '✓ Beats' : '≈ Ties')).toBeInTheDocument()
    expect(await screen.findByTestId('artifact-sha')).toHaveTextContent(card.artifact_sha256)
    for (const l of card.limitations) expect(screen.getByText(l)).toBeInTheDocument()
  })
})

describe('Insights', () => {
  it('renders the distribution, noise and reliability panels from real lineups', async () => {
    renderApp('/insights?season=2025-26&team=1610612750')
    expect(await screen.findByText('Rating distribution')).toBeInTheDocument()
    expect(await screen.findAllByText('Lineups')).not.toHaveLength(0)
    expect(screen.getByText('Reliability funnel: how noise shrinks with possessions')).toBeInTheDocument()
    expect(await screen.findByText('Median reliability')).toBeInTheDocument()
  })
})

describe('Routing', () => {
  it('has a not-found page', async () => {
    renderApp('/nope')
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
  })
})
