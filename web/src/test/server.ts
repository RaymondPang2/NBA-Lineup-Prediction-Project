/**
 * Mock Service Worker for component tests: answers the app's API calls with responses recorded from the
 * real API. Anything not covered gets the backend's own 404 error shape, so no request is silently invented.
 */
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { LineupSummary, Page } from '../api/types'
import { fixture } from './fixtures'

export const ORIGIN = 'http://127.0.0.1:8000'
const V1 = `${ORIGIN}/api/v1`

const notFound = (message: string) => HttpResponse.json({ error: { code: 'not_found', message, details: null } }, { status: 404 })

export const handlers = [
  http.get(`${ORIGIN}/health`, () => HttpResponse.json(fixture('health'))),
  http.get(`${V1}/seasons`, () => HttpResponse.json(fixture('seasons'))),
  http.get(`${V1}/data-status`, () => HttpResponse.json(fixture('data-status'))),
  http.get(`${V1}/teams`, () => HttpResponse.json(fixture('teams'))),
  http.get(`${V1}/teams/stats`, ({ request }) => {
    const season = new URL(request.url).searchParams.get('season')
    try {
      return HttpResponse.json(fixture(`team-stats-${season}`))
    } catch {
      return notFound(`season ${season} not found`)
    }
  }),
  http.get(`${V1}/teams/:teamId/predictions`, () => HttpResponse.json(fixture('team-predictions'))),
  http.get(`${V1}/lineups`, ({ request }) => {
    const q = new URL(request.url).searchParams
    if (Number(q.get('min_pre_poss')) >= 5000) return HttpResponse.json(fixture('lineups-empty'))
    if (q.get('sort') === 'pre_net') return HttpResponse.json(fixture('lineups-min-sorted-net'))
    const base = fixture<Page<LineupSummary>>('lineups-min')
    // Echo the requested page size/page so pagination behaves; the rows themselves are the recorded ones.
    return HttpResponse.json({ ...base, page: Number(q.get('page') ?? 1) })
  }),
  http.get(`${V1}/lineups/:id/prediction`, ({ params, request }) => {
    const lineup = fixture<{ lineup_id: number }>('lineup')
    if (Number(params.id) !== lineup.lineup_id) return notFound(`lineup ${params.id} not found`)
    const observed = new URL(request.url).searchParams.get('include_observed') === 'true'
    return HttpResponse.json(fixture(observed ? 'prediction' : 'prediction-no-observed'))
  }),
  http.get(`${V1}/lineups/:id`, ({ params }) => {
    const lineup = fixture<{ lineup_id: number }>('lineup')
    if (Number(params.id) === lineup.lineup_id) return HttpResponse.json(lineup)
    return HttpResponse.json(fixture('lineup-not-found'), { status: 404 })
  }),
  http.get(`${V1}/players`, ({ request }) => {
    const q = new URL(request.url).searchParams
    return HttpResponse.json(fixture(q.get('search') ? 'players-search' : 'players-min'))
  }),
  http.get(`${V1}/players/:id`, () => HttpResponse.json(fixture('player-edwards'))),
  http.post(`${V1}/predictions`, () => HttpResponse.json(fixture('prediction-five'))),
  http.get(`${V1}/model`, () => HttpResponse.json(fixture('model'))),
  http.get(`${V1}/model/performance`, () => HttpResponse.json(fixture('model-performance'))),
]

export const server = setupServer(...handlers)
