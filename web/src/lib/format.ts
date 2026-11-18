/** Display formatting. Values arrive unrounded from the API; rounding happens only here. */

const DASH = '—'

export function isNum(x: number | null | undefined): x is number {
  return typeof x === 'number' && Number.isFinite(x)
}

/** A rating (points per 100 possessions), e.g. 113.3. */
export function fmtRating(x: number | null | undefined, digits = 1): string {
  return isNum(x) ? x.toFixed(digits) : DASH
}

/** A signed rating such as a net rating or a difference: +5.9, −0.2 (true minus sign), 0.0. */
export function fmtSigned(x: number | null | undefined, digits = 1): string {
  if (!isNum(x)) return DASH
  const r = Number(x.toFixed(digits))
  if (r === 0) return (0).toFixed(digits)
  return `${r > 0 ? '+' : '−'}${Math.abs(r).toFixed(digits)}`
}

export function fmtInt(x: number | null | undefined): string {
  return isNum(x) ? Math.round(x).toLocaleString('en-US') : DASH
}

export function fmtNum(x: number | null | undefined, digits = 2): string {
  return isNum(x) ? x.toFixed(digits) : DASH
}

/** A 0-1 share as a percentage. */
export function fmtPct(x: number | null | undefined, digits = 0): string {
  return isNum(x) ? `${(x * 100).toFixed(digits)}%` : DASH
}

export function fmtInterval(lo: number | null | undefined, hi: number | null | undefined, digits = 1, signed = true): string {
  const f = signed ? fmtSigned : fmtNum
  return isNum(lo) && isNum(hi) ? `${f(lo, digits)} to ${f(hi, digits)}` : DASH
}

export function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function fmtRecord(w: number | null | undefined, l: number | null | undefined): string {
  return isNum(w) && isNum(l) ? `${w}–${l}` : DASH
}

/** Five player names as a compact label: last names joined by " · ". */
export function lineupLabel(players: { player_name: string }[]): string {
  return players.map((p) => lastName(p.player_name)).join(' · ')
}

export function lastName(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length <= 1) return name
  const suffix = /^(jr\.?|sr\.?|ii|iii|iv|v)$/i
  const last = parts[parts.length - 1]
  return suffix.test(last) && parts.length > 2 ? `${parts[parts.length - 2]} ${last}` : last
}
