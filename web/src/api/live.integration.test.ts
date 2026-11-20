/**
 * Frontend-backend integration against the LIVE FastAPI service (npm run test:integration).
 * Uses the app's own typed client, so a schema drift or a broken endpoint fails here.
 *   API_BASE_URL (default http://127.0.0.1:8000/api/v1)
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { pooledRatings } from '../lib/stats'
import { ApiError, createApi, unwrap } from './client'
import { apiOrigin } from './config'
import type { LineupSummary } from './types'

const ORIGIN = apiOrigin(process.env.API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1')
const api = createApi(ORIGIN, (input: Request) => fetch(input))
const Z = 1.959964
const SEASON = '2025-26'
const MIN = 1610612750

beforeAll(async () => {
  const res = await fetch(`${ORIGIN}/health`).catch(() => null)
  if (!res?.ok) throw new Error(`API not reachable at ${ORIGIN}. Start it: .venv/bin/uvicorn nba_lineups.api.main:app`)
})

describe('contract', () => {
  it('the committed openapi.json (source of the TypeScript types) equals the live schema', async () => {
    const committed = JSON.parse(readFileSync(join(process.cwd(), 'openapi.json'), 'utf8'))
    const live = await (await fetch(`${ORIGIN}/openapi.json`)).json()
    expect(live).toEqual(committed)
  })

  it('the API is healthy and serves the frozen model', async () => {
    const h = await unwrap(api.GET('/health'))
    expect(h).toMatchObject({ status: 'ok', database: 'ok', model: 'ok' })
    const card = await unwrap(api.GET('/api/v1/model'))
    expect(card.artifact_verified).toBe(true)
    expect(card.artifact_sha256).toBe(h.model_artifact_sha256)
    expect(card.name).toBe('linear')
  })

  it('allows the dashboard origin through CORS', async () => {
    const res = await fetch(`${ORIGIN}/api/v1/seasons`, {
      method: 'OPTIONS',
      headers: { Origin: 'http://localhost:5173', 'Access-Control-Request-Method': 'GET' },
    })
    expect(res.status).toBe(200)
    expect(res.headers.get('access-control-allow-origin')).toBe('http://localhost:5173')
  })

  it('errors arrive in the shape the UI parses', async () => {
    const err = await unwrap(api.GET('/api/v1/lineups/{lineup_id}', { params: { path: { lineup_id: 999999999 } } })).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(404)
    expect(err.code).toBe('not_found')
  })
})

describe('data used by each page', () => {
  it('seasons 2018-19 to 2025-26 plus the season in progress, with the two held-out seasons marked', async () => {
    const seasons = await unwrap(api.GET('/api/v1/seasons'))
    expect(seasons.map((s) => s.season_id).slice(0, 8)).toEqual(['2018-19', '2019-20', '2020-21', '2021-22', '2022-23', '2023-24', '2024-25', '2025-26'])
    expect(seasons.filter((s) => s.role === 'held_out').map((s) => s.season_id)).toEqual(['2024-25', '2025-26'])
    expect(seasons.slice(8).every((s) => s.role === 'current')).toBe(true)
  })

  it('rankings: global server-side order matches /lineups, and page 2 continues it', async () => {
    const q = { season: SEASON, window: 'pre' as const, metric: 'net' as const, min_poss: 100 }
    const r1 = await unwrap(api.GET('/api/v1/rankings/lineups', { params: { query: { ...q, page: 1, page_size: 25 } } }))
    const r2 = await unwrap(api.GET('/api/v1/rankings/lineups', { params: { query: { ...q, page: 2, page_size: 25 } } }))
    const lu = await unwrap(api.GET('/api/v1/lineups', { params: { query: { season: SEASON, min_pre_poss: 100, sort: 'pre_net', order: 'desc', page_size: 50 } } }))
    expect(r1.total).toBe(lu.total)
    const ranked = [...r1.items, ...r2.items].map((i) => i.net_rating)
    expect(ranked).toEqual(lu.items.map((i) => i.pre_break!.net_rating))
    expect(r2.items[0].rank).toBeGreaterThan(r1.items[24].rank - 1)
  })

  it('data status: cutoff, freshness and a version clients can watch', async () => {
    const s = await unwrap(api.GET('/api/v1/data-status'))
    expect(['current', 'stale', 'unknown']).toContain(s.freshness)
    if (s.data_cutoff) {
      expect(s.last_updated_at).toBeTruthy()
      expect(typeof s.data_version).toBe('number')
      const seasons = await unwrap(api.GET('/api/v1/seasons'))
      const cur = seasons.find((x) => x.season_id === s.season_id)!
      expect(cur.windows.every((w) => w.date_to <= s.data_cutoff!)).toBe(true)
    }
  })

  it('overview: team ratings are reproducible from summed totals', async () => {
    const teams = await unwrap(api.GET('/api/v1/teams/stats', { params: { query: { season: SEASON } } }))
    expect(teams).toHaveLength(30)
    for (const t of teams) {
      const r = pooledRatings([t.pre_break])!
      expect(r.off).toBeCloseTo(t.pre_break.off_rating!, 9)
      expect(r.net).toBeCloseTo(t.pre_break.net_rating!, 9)
    }
  })

  it('explorer: server-side filters, sorting and pagination behave as the table assumes', async () => {
    const q = { season: SEASON, team_id: MIN, min_pre_poss: 50, sort: 'pre_net' as const, order: 'desc' as const, page_size: 10 }
    const p1 = await unwrap(api.GET('/api/v1/lineups', { params: { query: { ...q, page: 1 } } }))
    const p2 = await unwrap(api.GET('/api/v1/lineups', { params: { query: { ...q, page: 2 } } }))
    expect(p1.total).toBeGreaterThan(10)
    const nets = [...p1.items, ...p2.items].map((l) => l.pre_break!.net_rating!)
    expect(nets).toEqual([...nets].sort((a, b) => b - a))
    expect(new Set([...p1.items, ...p2.items].map((l) => l.lineup_id)).size).toBe(20)
    for (const l of [...p1.items, ...p2.items]) {
      expect(l.team_id).toBe(MIN)
      expect(l.pre_break!.poss).toBeGreaterThanOrEqual(50)
      expect(l.pre_break!.opp_poss).toBeGreaterThanOrEqual(50)
    }
  })

  it('explorer: player filter returns only lineups containing every chosen player', async () => {
    const ids = [1630162, 1630183] // Edwards, McDaniels
    const page = await unwrap(api.GET('/api/v1/lineups', { params: { query: { season: SEASON, player_id: ids, page_size: 50 } } }))
    expect(page.total).toBeGreaterThan(0)
    for (const l of page.items) for (const id of ids) expect(l.players.map((p) => p.player_id)).toContain(id)
  })

  it('player search finds players by name', async () => {
    const page = await unwrap(api.GET('/api/v1/players', { params: { query: { season: SEASON, search: 'edw' } } }))
    expect(page.items.some((p) => p.player_name === 'Anthony Edwards')).toBe(true)
  })

  it('charts: paging through every lineup at a threshold returns each lineup once', async () => {
    const first = await unwrap(api.GET('/api/v1/lineups', { params: { query: { season: SEASON, min_pre_poss: 100, page_size: 200, sort: 'lineup_id', order: 'asc', page: 1 } } }))
    const rest = await Promise.all(
      Array.from({ length: first.total_pages - 1 }, (_, i) =>
        unwrap(api.GET('/api/v1/lineups', { params: { query: { season: SEASON, min_pre_poss: 100, page_size: 200, sort: 'lineup_id', order: 'asc', page: i + 2 } } })),
      ),
    )
    const all: LineupSummary[] = [first, ...rest].flatMap((p) => p.items)
    expect(all).toHaveLength(first.total)
    expect(new Set(all.map((l) => l.lineup_id)).size).toBe(first.total)
  })
})

describe('predictions as the UI displays them', () => {
  const check = (p: Awaited<ReturnType<typeof getPrediction>>) => {
    // Never displayable without baseline and uncertainty
    expect(Number.isFinite(p.baselines.team_prior)).toBe(true)
    expect(p.model_minus_team_prior).toBeCloseTo(p.predicted_net_rating - p.baselines.team_prior, 9)
    const u = p.uncertainty
    expect(u.true_rating_interval_95.lo).toBeCloseTo(p.predicted_net_rating - Z * u.model_sd, 3)
    expect(u.true_rating_interval_95.hi).toBeCloseTo(p.predicted_net_rating + Z * u.model_sd, 3)
    expect(u.observed_rating_interval_95.hi).toBeCloseTo(p.predicted_net_rating + Z * u.total_sd, 3)
    expect(u.total_sd).toBeCloseTo(Math.sqrt(u.model_sd ** 2 + u.sampling_sd ** 2), 9)
    // The contributions chart explains the number exactly
    expect(p.intercept + p.contributions.reduce((a, c) => a + c.contribution, 0)).toBeCloseTo(p.predicted_net_rating, 9)
    // The conditional estimand travels with every response
    expect(p.notes.join(' ')).toMatch(/GIVEN that its coach plays it after the break/)
  }
  const getPrediction = (id: number, possessions = 100, include_observed = false) =>
    unwrap(api.GET('/api/v1/lineups/{lineup_id}/prediction', { params: { path: { lineup_id: id }, query: { possessions, include_observed } } }))

  it('recorded lineup 281112 matches the documented example', async () => {
    const p = await getPrediction(281112, 100, true)
    check(p)
    expect(p.predicted_net_rating).toBeCloseTo(5.894, 2)
    expect(p.baselines.team_prior).toBeCloseTo(6.113, 2)
    expect(p.season_used_for_training).toBe(false)
    expect(p.observed_post_break?.poss).toBe(319)
  })

  it('the possessions slider only changes the observed-rating interval', async () => {
    const a = await getPrediction(281112, 100)
    const b = await getPrediction(281112, 800)
    expect(b.predicted_net_rating).toBe(a.predicted_net_rating)
    expect(b.uncertainty.model_sd).toBe(a.uncertainty.model_sd)
    expect(b.uncertainty.sampling_sd).toBeLessThan(a.uncertainty.sampling_sd)
  })

  it('a hypothetical five is predicted with team and player information only', async () => {
    const players = await unwrap(api.GET('/api/v1/players', { params: { query: { season: SEASON, team_id: MIN, page_size: 10 } } }))
    const ids = players.items.slice(0, 10).map((p) => p.player_id)
    let found = false
    for (let i = 0; i < 6 && !found; i++) {
      const five = ids.slice(i, i + 5)
      const p = await unwrap(api.POST('/api/v1/predictions', { body: { season_id: SEASON, team_id: MIN, player_ids: five, possessions: 100 } }))
      check(p)
      if (p.lineup_id === null) {
        expect(p.pre_break.poss).toBe(0)
        found = true
      }
    }
    expect(found).toBe(true)
  })

  it('a recorded five sent through POST equals the GET prediction', async () => {
    const get = await getPrediction(281112)
    const post = await unwrap(api.POST('/api/v1/predictions', { body: { season_id: SEASON, team_id: MIN, player_ids: get.players.map((p) => p.player_id), possessions: 100 } }))
    expect(post.lineup_id).toBe(281112)
    expect(post.predicted_net_rating).toBeCloseTo(get.predicted_net_rating, 12)
  })

  it('team predictions carry per-lineup reliability for the reliability chart', async () => {
    const page = await unwrap(api.GET('/api/v1/teams/{team_id}/predictions', { params: { path: { team_id: MIN }, query: { season: SEASON, min_pre_poss: 25, page_size: 50 } } }))
    expect(page.items.length).toBeGreaterThan(0)
    for (const p of page.items) {
      expect(p.pre_break.reliability).toBeGreaterThanOrEqual(0)
      expect(p.pre_break.reliability).toBeLessThanOrEqual(1)
      check(p)
    }
  })
})

describe('model performance page', () => {
  it('reports development CV, both held-out seasons and the pooled result', async () => {
    const perf = await unwrap(api.GET('/api/v1/model/performance'))
    expect(perf.held_out.map((e) => e.evaluation)).toEqual(['2024-25', '2025-26', 'pooled'])
    const pooled = perf.held_out[2]
    // beats_team_prior must agree with its own confidence interval
    expect(perf.beats_team_prior).toBe(pooled.model_minus_team_prior.hi < 0)
    expect(perf.beats_league_mean).toBe(pooled.model_minus_league_mean!.hi < 0)
  })
})
