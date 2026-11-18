import { describe, expect, it } from 'vitest'
import { fmtInterval, fmtPct, fmtRating, fmtRecord, fmtSigned, lastName, lineupLabel } from './format'

describe('format', () => {
  it('signs net ratings with a true minus and never shows -0.0', () => {
    expect(fmtSigned(5.894)).toBe('+5.9')
    expect(fmtSigned(-0.2185, 2)).toBe('−0.22')
    expect(fmtSigned(-0.04)).toBe('0.0')
    expect(fmtSigned(null)).toBe('—')
    expect(fmtSigned(Number.NaN)).toBe('—')
  })

  it('formats ratings, shares, records and intervals', () => {
    expect(fmtRating(113.32206)).toBe('113.3')
    expect(fmtPct(0.482)).toBe('48%')
    expect(fmtRecord(42, 14)).toBe('42–14')
    expect(fmtInterval(-12.82, 24.61)).toBe('−12.8 to +24.6')
    expect(fmtInterval(undefined, 1)).toBe('—')
  })

  it('shortens player names, keeping suffixes', () => {
    expect(lastName('Shai Gilgeous-Alexander')).toBe('Gilgeous-Alexander')
    expect(lastName('Jaren Jackson Jr.')).toBe('Jackson Jr.')
    expect(lastName('Nenê')).toBe('Nenê')
    expect(lineupLabel([{ player_name: 'Rudy Gobert' }, { player_name: 'Anthony Edwards' }])).toBe('Gobert · Edwards')
  })
})
