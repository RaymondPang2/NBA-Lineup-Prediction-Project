/**
 * Small statistics used by the charts. Inputs are always API rows; these helpers only summarise them.
 * Pooled ratings follow the project's rule: sum totals first, then divide (never average ratings).
 */

export interface Totals {
  pts: number
  poss: number
  opp_pts: number
  opp_poss: number
}

/** Pooled ORtg, DRtg and net from summed totals: 100·Σpts/Σposs − 100·Σopp_pts/Σopp_poss. */
export function pooledRatings(rows: Totals[]): { off: number; def: number; net: number } | null {
  const s = rows.reduce(
    (a, r) => ({ pts: a.pts + r.pts, poss: a.poss + r.poss, opp_pts: a.opp_pts + r.opp_pts, opp_poss: a.opp_poss + r.opp_poss }),
    { pts: 0, poss: 0, opp_pts: 0, opp_poss: 0 },
  )
  if (s.poss <= 0 || s.opp_poss <= 0) return null
  const off = (100 * s.pts) / s.poss
  const def = (100 * s.opp_pts) / s.opp_poss
  return { off, def, net: off - def }
}

export function weightedMean(values: number[], weights?: number[]): number {
  let sw = 0
  let s = 0
  values.forEach((v, i) => {
    const w = weights ? weights[i] : 1
    sw += w
    s += w * v
  })
  return sw > 0 ? s / sw : NaN
}

export function weightedSd(values: number[], weights?: number[]): number {
  const m = weightedMean(values, weights)
  let sw = 0
  let s = 0
  values.forEach((v, i) => {
    const w = weights ? weights[i] : 1
    sw += w
    s += w * (v - m) ** 2
  })
  return sw > 0 ? Math.sqrt(s / sw) : NaN
}

/** Linear-interpolated quantile of an unsorted array (q in 0..1). */
export function quantile(values: number[], q: number): number {
  if (values.length === 0) return NaN
  const s = [...values].sort((a, b) => a - b)
  const pos = (s.length - 1) * q
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  return s[lo] + (s[hi] - s[lo]) * (pos - lo)
}

export interface Bin {
  x0: number
  x1: number
  mid: number
  count: number
  label: string
}

/**
 * Fixed-width histogram. Values outside [lo, hi) are clamped into the edge bins so no lineup disappears;
 * the edge bins' labels say so ("≤ −40", "≥ 40").
 */
export function histogram(values: number[], width: number, lo: number, hi: number): Bin[] {
  const n = Math.max(1, Math.round((hi - lo) / width))
  const bins: Bin[] = Array.from({ length: n }, (_, i) => {
    const x0 = lo + i * width
    const x1 = x0 + width
    const label = i === 0 ? `< ${x1}` : i === n - 1 ? `≥ ${x0}` : `${x0} to ${x1}`
    return { x0, x1, mid: (x0 + x1) / 2, count: 0, label }
  })
  for (const v of values) {
    if (!Number.isFinite(v)) continue
    const i = Math.min(n - 1, Math.max(0, Math.floor((v - lo) / width)))
    bins[i].count += 1
  }
  return bins
}

/**
 * The sampling-noise constant K behind the API's net_rating_sampling_sd = sqrt(K·(1/poss + 1/opp_poss)).
 * Recovered from the API's own per-lineup values (median), so the funnel band uses exactly the backend's model.
 */
export function samplingK(rows: { sd: number | null | undefined; poss: number; opp_poss: number }[]): number {
  const ks = rows
    .filter((r) => typeof r.sd === 'number' && r.poss > 0 && r.opp_poss > 0)
    .map((r) => (r.sd as number) ** 2 / (1 / r.poss + 1 / r.opp_poss))
  return quantile(ks, 0.5)
}

/** Sampling SD of a net rating after n possessions on each end. */
export function samplingSd(k: number, n: number): number {
  return Math.sqrt((2 * k) / n)
}

/** Weighted least-squares line y = a + b·x. */
export function wlsLine(xs: number[], ys: number[], ws?: number[]): { intercept: number; slope: number } {
  const mx = weightedMean(xs, ws)
  const my = weightedMean(ys, ws)
  let sxy = 0
  let sxx = 0
  xs.forEach((x, i) => {
    const w = ws ? ws[i] : 1
    sxy += w * (x - mx) * (ys[i] - my)
    sxx += w * (x - mx) ** 2
  })
  const slope = sxx > 0 ? sxy / sxx : NaN
  return { slope, intercept: my - slope * mx }
}

/** Log-spaced points between a and b (inclusive), for drawing smooth curves on a log axis. */
export function logSpace(a: number, b: number, n: number): number[] {
  const la = Math.log(a)
  const lb = Math.log(b)
  return Array.from({ length: n }, (_, i) => Math.exp(la + ((lb - la) * i) / (n - 1)))
}
