import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import type { DataStatus } from '../api/types'
import { fmtDate } from './format'

/** "today, 7:02 AM" / "Nov 19, 7:02 AM" in the viewer's time zone. */
export function fmtUpdated(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  if (d.toDateString() === now.toDateString()) return `today, ${time}`
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}, ${time}`
}

export const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

/**
 * When a refresh loads new data (data_version changes), drop every cached API response so each page refetches
 * the new numbers. No reload and no rebuild; the first observed version is only remembered.
 */
export function useRefetchOnNewData(version: number | null | undefined) {
  const client = useQueryClient()
  const seen = useRef<number | null | undefined>(undefined)
  useEffect(() => {
    if (version === undefined) return
    if (seen.current !== undefined && seen.current !== version) {
      client.invalidateQueries({ predicate: (q) => !['health', 'data-status'].includes(String(q.queryKey[0])) })
    }
    seen.current = version
  }, [version, client])
}

export function freshnessText(s: DataStatus): { label: string; detail: string } {
  if (!s.data_cutoff || !s.last_updated_at) return { label: 'Not refreshed yet', detail: s.stale_reason ?? 'No successful refresh yet.' }
  const label = `Data through ${shortDate(s.data_cutoff)}`
  const detail =
    `${s.season_id} season to date: every game through ${fmtDate(s.data_cutoff)}. Last updated ${fmtUpdated(s.last_updated_at)}. ` +
    (s.freshness === 'current' ? 'Current.' : `Stale: ${s.stale_reason ?? 'the scheduled refresh has not run'}.`)
  return { label, detail }
}
