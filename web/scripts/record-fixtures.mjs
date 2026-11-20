#!/usr/bin/env node
/**
 * Record test fixtures from the LIVE API, so component tests render real NBA data, never invented values.
 *
 *   npm run fixtures            # API at http://127.0.0.1:8000 (override with API_ORIGIN=...)
 *
 * Writes src/test/fixtures/*.json plus manifest.json (the request behind each file and when it was recorded).
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ORIGIN = (process.env.API_ORIGIN ?? 'http://127.0.0.1:8000').replace(/\/+$/, '')
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'test', 'fixtures')
const SEASON = '2025-26'
const MIN = 1610612750 // Minnesota Timberwolves
const LINEUP = 281112 // MIN 2025-26: Gobert, Randle, DiVincenzo, Edwards, McDaniels (the docs/api.md example)

mkdirSync(OUT, { recursive: true })
const manifest = { recorded_at: new Date().toISOString(), origin: ORIGIN, files: {} }

async function call(path, init) {
  const res = await fetch(`${ORIGIN}${path}`, init)
  const body = await res.json()
  return { status: res.status, body }
}

async function record(name, path, init, expectStatus = 200) {
  const { status, body } = await call(path, init)
  if (status !== expectStatus) throw new Error(`${path}: expected HTTP ${expectStatus}, got ${status}: ${JSON.stringify(body).slice(0, 200)}`)
  writeFileSync(join(OUT, `${name}.json`), JSON.stringify(body, null, 1) + '\n')
  manifest.files[name] = { method: init?.method ?? 'GET', path, status, ...(init?.body ? { body: JSON.parse(init.body) } : {}) }
  return body
}

const post = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

const seasons = await record('seasons', '/api/v1/seasons')
await record('health', '/health')
await record('teams', `/api/v1/teams?season=${SEASON}`)
for (const s of seasons) await record(`team-stats-${s.season_id}`, `/api/v1/teams/stats?season=${s.season_id}`)
await record('lineups-min', `/api/v1/lineups?season=${SEASON}&team_id=${MIN}&min_pre_poss=25&page_size=50`)
await record('lineups-min-sorted-net', `/api/v1/lineups?season=${SEASON}&team_id=${MIN}&min_pre_poss=25&sort=pre_net&order=desc&page_size=50`)
await record('lineups-empty', `/api/v1/lineups?season=${SEASON}&team_id=${MIN}&min_pre_poss=5000&page_size=50`)
await record('lineup', `/api/v1/lineups/${LINEUP}`)
await record('lineup-not-found', '/api/v1/lineups/999999999', undefined, 404)
await record('prediction', `/api/v1/lineups/${LINEUP}/prediction?possessions=100&include_observed=true`)
await record('prediction-no-observed', `/api/v1/lineups/${LINEUP}/prediction?possessions=100`)
const players = await record('players-min', `/api/v1/players?season=${SEASON}&team_id=${MIN}&page_size=200&sort=pre_minutes&order=desc`)
await record('players-search', `/api/v1/players?season=${SEASON}&search=edw&page_size=12&sort=pre_minutes&order=desc`)
await record('player-edwards', `/api/v1/players/1630162?season=${SEASON}`)

// A hypothetical five: the first combination of MIN players that never shared the floor as a unit.
const ids = players.items.map((p) => p.player_id).slice(0, 10)
let hypothetical = null
outer: for (let a = 0; a < ids.length; a++)
  for (let b = a + 1; b < ids.length; b++)
    for (let c = b + 1; c < ids.length; c++)
      for (let d = c + 1; d < ids.length; d++)
        for (let e = d + 1; e < ids.length; e++) {
          const five = [ids[a], ids[b], ids[c], ids[d], ids[e]]
          const { status, body } = await call('/api/v1/predictions', post({ season_id: SEASON, team_id: MIN, player_ids: five, possessions: 100 }))
          if (status === 200 && body.lineup_id === null) {
            hypothetical = five
            break outer
          }
        }
if (!hypothetical) throw new Error('no hypothetical five found')
await record('prediction-five', '/api/v1/predictions', post({ season_id: SEASON, team_id: MIN, player_ids: hypothetical, possessions: 100 }))
await record('team-predictions', `/api/v1/teams/${MIN}/predictions?season=${SEASON}&min_pre_poss=25&page=1&page_size=200`)
await record('model', '/api/v1/model')
await record('model-performance', '/api/v1/model/performance')
// Season in progress (2026-27): freshness and one provisional prediction
await record('data-status', '/api/v1/data-status')
const current = seasons.find((s) => s.role === 'current')
if (current) {
  const top = await record('lineups-current', `/api/v1/lineups?season=${current.season_id}&sort=pre_poss&order=desc&page_size=1`)
  await record('prediction-provisional', `/api/v1/lineups/${top.items[0].lineup_id}/prediction?possessions=100`)
}

writeFileSync(join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 1) + '\n')
console.log(`recorded ${Object.keys(manifest.files).length} fixtures from ${ORIGIN} into ${OUT}`)
