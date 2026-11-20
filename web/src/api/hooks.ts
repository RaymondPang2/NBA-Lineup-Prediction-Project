/**
 * Data hooks. Every number on screen comes through one of these, from the FastAPI service.
 * Completed seasons are static, so responses are cached for the session. When the daily refresh loads new data
 * for the season in progress, useDataStatus sees a new data_version and useRefetchOnNewData invalidates the cache.
 */
import { keepPreviousData, useQueries, useQuery } from '@tanstack/react-query'
import { api, unwrap } from './client'
import type { LineupQuery, LineupSummary, Page, PlayerQuery, PredictionRequest, TeamSeason } from './types'

const STATIC = { staleTime: Infinity, gcTime: 60 * 60 * 1000 } as const

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => unwrap(api.GET('/health', { signal })),
    refetchInterval: 30_000,
    retry: false,
  })
}

export function useSeasons() {
  return useQuery({
    queryKey: ['seasons'],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/seasons', { signal })),
    ...STATIC,
  })
}

export function useTeams(season?: string) {
  return useQuery({
    queryKey: ['teams', season ?? null],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/teams', { params: { query: { season } }, signal })),
    ...STATIC,
  })
}

export function useTeamStats(season: string | undefined) {
  return useQuery({
    queryKey: ['team-stats', season],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/teams/stats', { params: { query: { season: season! } }, signal })),
    enabled: !!season,
    ...STATIC,
  })
}

/** Team stats for several seasons at once (history charts). Shares the cache with useTeamStats. */
export function useTeamStatsForSeasons(seasons: string[]) {
  return useQueries({
    queries: seasons.map((season) => ({
      queryKey: ['team-stats', season],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        unwrap(api.GET('/api/v1/teams/stats', { params: { query: { season } }, signal })),
      ...STATIC,
    })),
    combine: (results) => ({
      data: results.every((r) => r.data) ? results.map((r, i) => ({ season: seasons[i], teams: r.data as TeamSeason[] })) : undefined,
      isPending: results.some((r) => r.isPending),
      error: results.find((r) => r.error)?.error ?? null,
      refetch: () => results.forEach((r) => r.error && r.refetch()),
    }),
  })
}

export function useLineups(query: LineupQuery, enabled = true) {
  return useQuery({
    queryKey: ['lineups', query],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/lineups', { params: { query }, signal })),
    enabled,
    placeholderData: keepPreviousData,
    ...STATIC,
  })
}

/** Upper bound for chart pulls: 25 pages x 200 = 5,000 lineups. Filters keep real requests well under it. */
export const MAX_CHART_PAGES = 25

/**
 * Every lineup matching a filter, paging through /lineups 200 at a time (pages after the first in parallel).
 * Used by the distribution and reliability charts. `truncated` is true if the cap was hit.
 */
export function useAllLineups(query: Omit<LineupQuery, 'page' | 'page_size' | 'sort' | 'order'>, enabled = true) {
  return useQuery({
    queryKey: ['lineups-all', query],
    enabled,
    ...STATIC,
    queryFn: async ({ signal }) => {
      const get = (page: number) =>
        unwrap(api.GET('/api/v1/lineups', { params: { query: { ...query, page, page_size: 200, sort: 'lineup_id', order: 'asc' } }, signal }))
      const first = await get(1)
      const pages = Math.min(first.total_pages, MAX_CHART_PAGES)
      const rest = await Promise.all(Array.from({ length: Math.max(0, pages - 1) }, (_, i) => get(i + 2)))
      const items: LineupSummary[] = [first, ...rest].flatMap((p) => p.items)
      return { items, total: first.total, truncated: first.total_pages > MAX_CHART_PAGES }
    },
  })
}

export function useLineup(id: number | undefined) {
  return useQuery({
    queryKey: ['lineup', id],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/lineups/{lineup_id}', { params: { path: { lineup_id: id! } }, signal })),
    enabled: id !== undefined && Number.isFinite(id),
    ...STATIC,
  })
}

export function useLineupPrediction(id: number | undefined, possessions: number, includeObserved: boolean) {
  return useQuery({
    queryKey: ['lineup-prediction', id, possessions, includeObserved],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/lineups/{lineup_id}/prediction', {
          params: { path: { lineup_id: id! }, query: { possessions, include_observed: includeObserved } },
          signal,
        }),
      ),
    enabled: id !== undefined,
    placeholderData: keepPreviousData,
    ...STATIC,
  })
}

/**
 * Prediction for any five players of one team (POST /predictions). The endpoint is read-only and
 * deterministic, so it is cached like a GET, keyed by the sorted player ids.
 */
export function usePredictFive(body: PredictionRequest | undefined) {
  const key = body ? { ...body, player_ids: [...body.player_ids].sort((a, b) => a - b) } : null
  return useQuery({
    queryKey: ['predict-five', key],
    queryFn: ({ signal }) => unwrap(api.POST('/api/v1/predictions', { body: key!, signal })),
    enabled: !!key && key.player_ids.length === 5,
    placeholderData: keepPreviousData,
    ...STATIC,
  })
}

export function useTeamPredictions(teamId: number | undefined, season: string | undefined, minPrePoss: number) {
  return useQuery({
    queryKey: ['team-predictions', teamId, season, minPrePoss],
    enabled: teamId !== undefined && !!season,
    ...STATIC,
    queryFn: async ({ signal }) => {
      const get = (page: number) =>
        unwrap(
          api.GET('/api/v1/teams/{team_id}/predictions', {
            params: { path: { team_id: teamId! }, query: { season: season!, min_pre_poss: minPrePoss, page, page_size: 200 } },
            signal,
          }),
        )
      const first = await get(1)
      const rest = await Promise.all(Array.from({ length: Math.min(first.total_pages, 10) - 1 }, (_, i) => get(i + 2)))
      return { items: [first, ...rest].flatMap((p) => p.items), total: first.total }
    },
  })
}

export function usePlayers(query: PlayerQuery, enabled = true) {
  return useQuery({
    queryKey: ['players', query],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/players', { params: { query }, signal })),
    enabled,
    placeholderData: keepPreviousData,
    ...STATIC,
  })
}

export function useModelCard() {
  return useQuery({ queryKey: ['model'], queryFn: ({ signal }) => unwrap(api.GET('/api/v1/model', { signal })), ...STATIC })
}

export function useModelPerformance() {
  return useQuery({
    queryKey: ['model-performance'],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/model/performance', { signal })),
    ...STATIC,
  })
}

export type { Page }

export function usePlayer(playerId: number | undefined, season?: string) {
  return useQuery({
    queryKey: ['player', playerId, season ?? null],
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/players/{player_id}', { params: { path: { player_id: playerId! }, query: { season } }, signal })),
    enabled: playerId !== undefined,
    ...STATIC,
  })
}

/** Freshness of the season in progress. Polled, and refetched when the tab regains focus. */
export function useDataStatus() {
  return useQuery({
    queryKey: ['data-status'],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/data-status', { signal })),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  })
}
