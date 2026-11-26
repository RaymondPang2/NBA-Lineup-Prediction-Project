import { expect, test } from '@playwright/test'
import { apiGet, signed } from './api'

type Team = { team_name: string; pre_break: { net_rating: number } }
type Prediction = { predicted_net_rating: number; baselines: { team_prior: number }; uncertainty: { true_rating_interval_95: { lo: number; hi: number } } }
type Lineup = { lineup_id: number; players: { player_name: string }[]; pre_break: { net_rating: number; poss: number } }

test.beforeEach(async ({ page }) => {
  page.on('pageerror', (e) => {
    throw e
  })
})

test('overview: live team table and API health', async ({ page, request }) => {
  const teams = await apiGet<Team[]>(request, '/teams/stats?season=2025-26')
  await page.goto('/?season=2025-26')
  await expect(page.getByTestId('api-health')).toHaveAttribute('data-state', 'online')
  const table = page.getByRole('region', { name: 'Team ratings' })
  await expect(table.getByRole('row')).toHaveCount(teams.length + 1)
  const best = [...teams].sort((a, b) => b.pre_break.net_rating - a.pre_break.net_rating)[0]
  await expect(table.getByRole('row').nth(1)).toContainText(best.team_name)
  await expect(table.getByRole('row').nth(1)).toContainText(signed(best.pre_break.net_rating))
  // Selecting a team focuses the page and shows its history
  await table.getByRole('button', { name: new RegExp(best.team_name) }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(best.team_name)
  await expect(page.getByText('Most-used lineups')).toBeVisible()
})

test('explorer: sort, paginate and filter by player against the live API', async ({ page, request }) => {
  const top = await apiGet<{ items: Lineup[]; total: number }>(request, '/lineups?season=2025-26&min_pre_poss=25&sort=pre_net&order=desc&page_size=50')
  await page.goto('/lineups?season=2025-26')
  await page.getByRole('button', { name: /Pre net/ }).click()
  await expect(page).toHaveURL(/sort=pre_net/)
  const firstRow = page.getByRole('region', { name: 'Lineups' }).getByRole('row').nth(1)
  await expect(firstRow).toContainText(signed(top.items[0].pre_break.net_rating))
  await expect(page.getByText(`${top.total.toLocaleString('en-US')} lineups`, { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Next page' }).click()
  await expect(page).toHaveURL(/page=2/)

  const search = page.getByRole('combobox', { name: 'Lineups with players' })
  await search.fill('Gilgeous')
  await page.getByRole('option', { name: /Shai Gilgeous-Alexander/ }).click()
  await expect(page.getByRole('button', { name: 'Remove Shai Gilgeous-Alexander' })).toBeVisible()
  await expect(page).toHaveURL(/player=1628983/)
  const rows = page.getByRole('region', { name: 'Lineups' }).getByRole('row')
  await expect(rows.nth(1)).toContainText('Gilgeous-Alexander')
})

test('lineup detail shows the API values and links to the prediction', async ({ page, request }) => {
  const l = await apiGet<{ pre_break: { net_rating: number }; post_break: { net_rating: number } }>(request, '/lineups/281112')
  await page.goto('/lineups/281112')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Anthony Edwards')
  await expect(page.getByText(signed(l.pre_break.net_rating)).first()).toBeVisible()
  await expect(page.getByText(signed(l.post_break.net_rating)).first()).toBeVisible()
  await page.getByRole('link', { name: /frozen-model prediction/ }).click()
  await expect(page).toHaveURL(/\/predict\?season=2025-26&team=1610612750&lineup=281112/)
  await expect(page.getByTestId('predicted-net')).toBeVisible()
})

test('predict: recorded lineup shows prediction, baseline, intervals and estimand', async ({ page, request }) => {
  const p = await apiGet<Prediction>(request, '/lineups/281112/prediction?possessions=100')
  await page.goto('/predict?season=2025-26&team=1610612750')
  await page.getByRole('listbox', { name: 'Recorded lineups' }).getByRole('option').first().click()
  await expect(page.getByTestId('predicted-net')).toHaveText(signed(p.predicted_net_rating))
  await expect(page.getByTestId('team-prior')).toHaveText(signed(p.baselines.team_prior))
  await expect(page.getByText(`${signed(p.uncertainty.true_rating_interval_95.lo)} to ${signed(p.uncertainty.true_rating_interval_95.hi)}`).first()).toBeVisible()
  await expect(page.getByTestId('estimand-notice').first()).toContainText('if its coach plays it after the break')
  await expect(page.getByRole('img', { name: /Prediction .* with 95% intervals/ })).toBeVisible()

  // The realized result appears only on request
  await expect(page.getByText('What actually happened after the break')).toHaveCount(0)
  await page.getByRole('switch', { name: /Show what actually happened/ }).click()
  await expect(page.getByText('What actually happened after the break')).toBeVisible()
})

test('predict: build a hypothetical five', async ({ page }) => {
  await page.goto('/predict?season=2025-26&team=1610612750&mode=build')
  const boxes = page.getByRole('list', { name: 'Players' }).getByRole('checkbox')
  for (const i of [0, 2, 4, 6, 8]) await boxes.nth(i).check()
  await expect(page.getByTestId('predicted-net')).toBeVisible()
  await expect(page.getByTestId('team-prior')).toBeVisible()
  await expect(page.getByText(/Recorded lineup #|Hypothetical lineup/)).toBeVisible()
})

test('insights: charts render from live data', async ({ page }) => {
  await page.goto('/insights?season=2025-26')
  await expect(page.getByText('Rating distribution')).toBeVisible()
  await expect(page.locator('.recharts-bar-rectangle').first()).toBeVisible()
  await expect(page.getByText('Inside the noise band')).toBeVisible()
  await expect(page.getByText('Fitted slope')).toBeVisible()
  await expect(page.getByText('Median reliability')).toBeVisible()
  // Table view carries the same data as text
  await page.getByRole('radiogroup', { name: 'View' }).first().getByRole('radio', { name: 'Table' }).click()
  await expect(page.getByRole('region', { name: 'Histogram bins' })).toBeVisible()
})

test('model page: verdict and verified artifact hash', async ({ page, request }) => {
  const perf = await apiGet<{ conclusion: string }>(request, '/model/performance')
  const card = await apiGet<{ artifact_sha256: string }>(request, '/model')
  await page.goto('/model')
  await expect(page.getByTestId('conclusion')).toContainText(perf.conclusion)
  await expect(page.getByTestId('artifact-sha')).toHaveText(card.artifact_sha256)
  await expect(page.getByText('✓ verified now')).toBeVisible()
})

test('season in progress: default season, last-updated status and a provisional prediction', async ({ page, request }) => {
  const status = await apiGet<{ season_id: string; data_cutoff: string; freshness: string }>(request, '/data-status')
  const top = await apiGet<{ items: { lineup_id: number; team_id: number }[] }>(request, `/lineups?season=${status.season_id}&sort=pre_poss&order=desc&page_size=1`)
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 2, name: /League overview/ })).toContainText(status.season_id)
  await expect(page.getByTestId('data-freshness')).toHaveAttribute('data-state', status.freshness)
  await expect(page.getByText('Season in progress · provisional')).toBeVisible()
  const l = top.items[0]
  await page.goto(`/predict?season=${status.season_id}&team=${l.team_id}&lineup=${l.lineup_id}`)
  await expect(page.getByTestId('provisional-notice')).toBeVisible()
  await expect(page.getByTestId('team-prior')).toBeVisible()
  await expect(page.getByTestId('predicted-net')).toBeVisible()
})

test('rankings: global ranking from the live API, re-rank, and navigate to a lineup', async ({ page, request }) => {
  type R = { items: { rank: number; lineup_id: number; net_rating: number; def_rating: number }[]; total: number }
  const net = await apiGet<R>(request, '/rankings/lineups?season=2025-26&window=season&metric=net&min_poss=100&page_size=25')
  const def = await apiGet<R>(request, '/rankings/lineups?season=2025-26&window=season&metric=def&min_poss=100&page_size=25')
  await page.goto('/rankings?season=2025-26')
  const rows = page.getByRole('region', { name: 'Lineup ranking' }).getByTestId('rank-row')
  await expect(rows).toHaveCount(25)
  await expect(rows.first()).toContainText(signed(net.items[0].net_rating))
  await page.getByRole('radio', { name: /Best defense/ }).click()
  await expect(page).toHaveURL(/metric=def/)
  await expect(rows.first()).toContainText(def.items[0].def_rating.toFixed(1))
  await page.getByRole('button', { name: 'Next page' }).click()
  await expect(rows.first()).toContainText('26')
  await rows.first().getByRole('link').first().click()
  await expect(page).toHaveURL(/\/lineups\/\d+$/)
})

test('rankings: predictions keep the baseline, intervals and the provisional label', async ({ page, request }) => {
  const status = await apiGet<{ season_id: string }>(request, '/data-status')
  type P = { items: { predicted_net_rating: number; team_prior: number }[] }
  const r = await apiGet<P>(request, `/rankings/predictions?season=${status.season_id}&min_pre_poss=50&page_size=10`)
  await page.goto(`/rankings?mode=predicted&top=10`)
  const rows = page.getByRole('region', { name: 'Prediction ranking' }).getByTestId('rank-row')
  await expect(rows).toHaveCount(r.items.length)
  await expect(rows.first()).toContainText(signed(r.items[0].predicted_net_rating))
  await expect(rows.first()).toContainText(signed(r.items[0].team_prior))
  await expect(page.getByTestId('provisional-notice')).toBeVisible()
  await expect(page.getByTestId('estimand-notice')).toContainText('not statistically better than the team-prior baseline')
})

test('predict: provisional 2026-27 prediction for a hypothetical five, with cutoff and accuracy caveat', async ({ page, request }) => {
  const status = await apiGet<{ season_id: string; data_cutoff: string }>(request, '/data-status')
  await page.goto(`/predict?season=${status.season_id}&team=1610612744&mode=build`)
  const boxes = page.getByRole('list', { name: 'Players' }).getByRole('checkbox')
  for (const i of [0, 2, 4, 6, 8]) await boxes.nth(i).check()
  await expect(page.getByTestId('predicted-net')).toBeVisible()
  await expect(page.getByTestId('team-prior')).toBeVisible()
  const notice = page.getByTestId('provisional-notice')
  await expect(notice).toContainText('Incomplete pre-break information reduces accuracy')
  await expect(notice).toContainText('pre-break games per team')
  await expect(page.getByText(/^PROVISIONAL · /)).toBeVisible()
})

test('landing page: the three main actions navigate, and the facts come from the API', async ({ page, request }) => {
  const seasons = await apiGet<{ n_lineups: number }[]>(request, '/seasons')
  await page.goto('/')
  await expect(page.getByTestId('hero-facts')).toContainText(seasons.reduce((a, s) => a + s.n_lineups, 0).toLocaleString('en-US'))
  for (const [cta, url, heading] of [
    ['cta-lineups', /\/lineups$/, 'Lineup explorer'],
    ['cta-rankings', /\/rankings$/, 'Lineup rankings'],
    ['cta-predict', /\/predict$/, 'Predict a lineup'],
  ] as const) {
    await page.goto('/')
    await page.getByTestId(cta).click()
    await expect(page).toHaveURL(url)
    await expect(page.getByRole('heading', { level: 1 })).toContainText(heading)
  }
})

test('model page: headline RMSE comparison equals the verified held-out results', async ({ page, request }) => {
  type E = { estimate: number }
  const perf = await apiGet<{ held_out: { evaluation: string; rmse_model: E; rmse_team_prior: E; rmse_league_mean: E }[] }>(request, '/model/performance')
  const pooled = perf.held_out.find((e) => e.evaluation === 'pooled')!
  await page.goto('/model')
  await expect(page.getByTestId('rmse-Linear regression')).toHaveText(pooled.rmse_model.estimate.toFixed(2))
  await expect(page.getByTestId('rmse-Team-prior baseline')).toHaveText(pooled.rmse_team_prior.estimate.toFixed(2))
  await expect(page.getByTestId('rmse-League-average baseline')).toHaveText(pooled.rmse_league_mean.estimate.toFixed(2))
  await expect(page.getByTestId('verdict-team-prior')).toContainText('not statistically significantly outperform')
  await page.getByTestId('explain-selection').locator('summary').click()
  await expect(page.getByTestId('explain-selection')).toContainText('simplest')
})
