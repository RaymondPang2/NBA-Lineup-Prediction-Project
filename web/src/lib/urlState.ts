/**
 * Filters live in the URL query string, so every view is linkable and survives a reload,
 * and the browser's back button undoes a filter change.
 */
import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { useSeasons } from '../api/hooks'

type Value = string | number | boolean | null | undefined | (string | number)[]

export function useUrlState() {
  const [params, setParams] = useSearchParams()

  const get = useCallback((key: string) => params.get(key) ?? undefined, [params])
  const getNum = useCallback(
    (key: string, fallback?: number) => {
      const v = params.get(key)
      const n = v === null || v === '' ? NaN : Number(v)
      return Number.isFinite(n) ? n : fallback
    },
    [params],
  )
  const getAll = useCallback((key: string) => params.getAll(key), [params])

  const set = useCallback(
    (patch: Record<string, Value>, { push = false }: { push?: boolean } = {}) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [k, v] of Object.entries(patch)) {
            next.delete(k)
            if (Array.isArray(v)) v.forEach((x) => next.append(k, String(x)))
            else if (v !== undefined && v !== null && v !== '' && v !== false) next.set(k, String(v))
          }
          return next
        },
        { replace: !push },
      )
    },
    [setParams],
  )

  return { params, get, getNum, getAll, set }
}

/** The selected season (URL `season`, else the most recent one) plus the season list. */
export function useSeasonParam() {
  const { get } = useUrlState()
  const seasons = useSeasons()
  const list = seasons.data ?? []
  const requested = get('season')
  const latest = list.length ? list[list.length - 1].season_id : undefined
  const season = requested && list.some((s) => s.season_id === requested) ? requested : latest
  return { season, seasons: list, seasonInfo: list.find((s) => s.season_id === season), query: seasons }
}
