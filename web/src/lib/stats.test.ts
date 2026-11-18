import { describe, expect, it } from 'vitest'
import type { LineupSummary, Page } from '../api/types'
import { fixture } from '../test/fixtures'
import { histogram, pooledRatings, quantile, samplingK, samplingSd, weightedMean, wlsLine } from './stats'

describe('pooledRatings', () => {
  it('sums totals first, then divides (never averages ratings)', () => {
    const rows = [
      { pts: 120, poss: 100, opp_pts: 100, opp_poss: 100 }, // ORtg 120
      { pts: 10, poss: 10, opp_pts: 12, opp_poss: 10 }, // ORtg 100
    ]
    const r = pooledRatings(rows)!
    expect(r.off).toBeCloseTo((100 * 130) / 110, 10) // 118.18, not the mean of ratings (110)
    expect(r.def).toBeCloseTo((100 * 112) / 110, 10)
    expect(r.net).toBeCloseTo(r.off - r.def, 12)
    expect(pooledRatings([])).toBeNull()
  })

  it('reproduces the API team ratings from their totals', () => {
    const teams = fixture<{ pre_break: { pts: number; poss: number; opp_pts: number; opp_poss: number; off_rating: number; def_rating: number } }[]>('team-stats-2025-26')
    for (const t of teams) {
      const r = pooledRatings([t.pre_break])!
      expect(r.off).toBeCloseTo(t.pre_break.off_rating, 9)
      expect(r.def).toBeCloseTo(t.pre_break.def_rating, 9)
    }
  })
})

describe('samplingK', () => {
  it("recovers the backend's noise constant from real lineup sampling SDs", () => {
    const page = fixture<Page<LineupSummary>>('lineups-min')
    const k = samplingK(page.items.filter((l) => l.pre_break).map((l) => ({ sd: l.pre_break!.net_rating_sampling_sd, poss: l.pre_break!.poss, opp_poss: l.pre_break!.opp_poss })))
    // docs/api.md: K = 14,639, fitted on the development seasons
    expect(k).toBeCloseTo(14639, -1)
    expect(samplingSd(k, 100)).toBeCloseTo(17.11, 1)
  })
})

describe('histogram and summaries', () => {
  it('bins values and clamps outliers into the edge bins', () => {
    const bins = histogram([-100, -1, 0, 4.9, 5, 100], 5, -10, 10)
    expect(bins.map((b) => b.count)).toEqual([1, 1, 2, 2])
    expect(bins[0].label).toBe('< -5')
    expect(bins[3].label).toBe('≥ 5')
  })

  it('computes weighted means, quantiles and a weighted line', () => {
    expect(weightedMean([1, 3], [3, 1])).toBe(1.5)
    expect(quantile([4, 1, 3, 2], 0.5)).toBe(2.5)
    const fit = wlsLine([0, 1, 2, 3], [1, 3, 5, 7])
    expect(fit.slope).toBeCloseTo(2, 12)
    expect(fit.intercept).toBeCloseTo(1, 12)
  })
})
