/** Symmetric integer ticks for a diverging axis [-lim, lim]; every other one when space is tight. */
export function axisTicks(lim: number, narrow = false): number[] {
  const step = narrow && lim > 2 ? 2 : 1
  const out: number[] = []
  for (let t = -Math.floor(lim / step) * step; t <= lim; t += step) out.push(t)
  return out
}
