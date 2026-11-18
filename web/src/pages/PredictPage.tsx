import clsx from 'clsx'
import { useEffect, useMemo, useState } from 'react'
import { useLineupPrediction, useLineups, usePlayers, usePredictFive } from '../api/hooks'
import type { Prediction } from '../api/types'
import { SeasonSelect, TeamSelect } from '../components/filters/Filters'
import { EstimandNotice } from '../components/prediction/EstimandNotice'
import { PredictionResult } from '../components/prediction/PredictionResult'
import { Card, CardBody, CardHeader, FilterBar, PageHeader } from '../components/ui/Card'
import { Button, Field, PossessionSelect, Segmented, Switch, TextInput } from '../components/ui/Controls'
import { EmptyState, ErrorState, LoadingBlock, Spinner } from '../components/ui/States'
import { fmtInt, fmtSigned, lastName } from '../lib/format'
import { useSeasonParam, useUrlState } from '../lib/urlState'

type Mode = 'recorded' | 'build'

function PossessionsControl({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [local, setLocal] = useState(value)
  useEffect(() => setLocal(value), [value])
  useEffect(() => {
    if (local === value) return
    const t = setTimeout(() => onChange(local), 300)
    return () => clearTimeout(t)
  }, [local, value, onChange])
  return (
    <Field label={`Post-break possessions: ${local.toLocaleString()}`} hint="Sizes the observed-rating interval. More possessions, less sampling noise." className="col-span-2 sm:!w-64">
      {(id) => (
        <input
          id={id}
          type="range"
          min={25}
          max={1000}
          step={25}
          value={local}
          onChange={(e) => setLocal(Number(e.target.value))}
          className="h-10 w-full accent-[var(--accent)]"
        />
      )}
    </Field>
  )
}

function RecordedPicker({
  season,
  teamId,
  selected,
  onSelect,
}: {
  season: string
  teamId: number
  selected?: number
  onSelect: (id: number) => void
}) {
  const [minPre, setMinPre] = useState(25)
  const [filter, setFilter] = useState('')
  const q = useLineups({ season, team_id: teamId, min_pre_poss: minPre, sort: 'pre_poss', order: 'desc', page_size: 200 })
  const items = useMemo(() => {
    const f = filter.trim().toLowerCase()
    const all = q.data?.items ?? []
    return f ? all.filter((l) => l.players.some((p) => p.player_name.toLowerCase().includes(f))) : all
  }, [q.data, filter])

  return (
    <Card>
      <CardHeader title="Choose a recorded lineup" subtitle="Five-man units this team actually used, by pre-break possessions." />
      <CardBody>
        <div className="mb-3 grid grid-cols-2 gap-3">
          <Field label="Filter by player">{(id) => <TextInput id={id} value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="e.g. Edwards" />}</Field>
          <PossessionSelect label="Min pre-break poss." value={minPre} onChange={setMinPre} presets={[0, 25, 50, 100, 200]} />
        </div>
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
        ) : !q.data ? (
          <LoadingBlock height="h-72" label="Loading lineups" />
        ) : items.length === 0 ? (
          <EmptyState title="No lineups match">Lower the possession threshold or clear the player filter.</EmptyState>
        ) : (
          <>
            <ul role="listbox" aria-label="Recorded lineups" className="max-h-[420px] divide-y divide-line overflow-y-auto rounded-md border border-line">
              {items.map((l) => (
                <li
                  key={l.lineup_id}
                  role="option"
                  aria-selected={l.lineup_id === selected}
                  tabIndex={0}
                  onClick={() => onSelect(l.lineup_id)}
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(l.lineup_id))}
                  className={clsx(
                    'flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm',
                    l.lineup_id === selected ? 'bg-accent-soft' : 'hover:bg-surface-2',
                  )}
                >
                  <span className="min-w-0 truncate text-ink">{l.players.map((p) => lastName(p.player_name)).join(' · ')}</span>
                  <span className="tabular shrink-0 text-xs text-muted">
                    {fmtInt(l.pre_break?.poss ?? 0)} poss · {fmtSigned(l.pre_break?.net_rating)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted">
              {items.length.toLocaleString()} of {q.data.total.toLocaleString()} lineups{q.data.total > 200 ? ' (the 200 most-used are listed)' : ''}. Pre-break net shown for reference.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}

function FiveBuilder({ season, teamId, selected: fromUrl, onChange }: { season: string; teamId: number; selected: number[]; onChange: (ids: number[]) => void }) {
  const q = usePlayers({ season, team_id: teamId, page_size: 200, sort: 'pre_minutes', order: 'desc' })
  // Local state answers the click immediately; the URL (updated asynchronously by the router) follows.
  const [selected, setSelected] = useState(fromUrl)
  const urlKey = fromUrl.join(',')
  useEffect(() => setSelected(urlKey ? urlKey.split(',').map(Number) : []), [urlKey])
  const update = (ids: number[]) => {
    setSelected(ids)
    onChange(ids)
  }
  const toggle = (id: number) => {
    if (selected.includes(id)) update(selected.filter((x) => x !== id))
    else if (selected.length < 5) update([...selected, id])
  }
  return (
    <Card>
      <CardHeader
        title="Build a five"
        subtitle="Pick exactly five players who played for this team this season. They need not have shared the floor."
        actions={
          selected.length > 0 && (
            <Button size="sm" variant="ghost" onClick={() => update([])}>
              Clear
            </Button>
          )
        }
      />
      <CardBody>
        <p className="mb-2 text-sm text-ink-2" aria-live="polite">
          <span className="font-semibold text-ink">{selected.length}</span> / 5 selected
        </p>
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
        ) : !q.data ? (
          <LoadingBlock height="h-72" label="Loading players" />
        ) : q.data.items.length === 0 ? (
          <EmptyState title="No players found" />
        ) : (
          <ul className="max-h-[420px] divide-y divide-line overflow-y-auto rounded-md border border-line" aria-label="Players">
            {q.data.items.map((p) => {
              const checked = selected.includes(p.player_id)
              const disabled = !checked && selected.length >= 5
              return (
                <li key={p.player_id}>
                  <label className={clsx('flex items-center gap-3 px-3 py-2 text-sm', disabled ? 'opacity-50' : 'cursor-pointer hover:bg-surface-2', checked && 'bg-accent-soft')}>
                    <input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggle(p.player_id)} className="size-4 accent-[var(--accent)]" />
                    <span className="min-w-0 flex-1 truncate text-ink">{p.player_name}</span>
                    <span className="tabular shrink-0 text-xs text-muted">
                      {fmtInt(p.pre_break?.minutes ?? 0)} pre min{p.pre_break?.on_off_net !== null && p.pre_break?.on_off_net !== undefined ? ` · on-off ${fmtSigned(p.pre_break.on_off_net)}` : ''}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}

function ResultPanel({
  query,
  hasInput,
  emptyText,
}: {
  query: { data?: Prediction; error: unknown; isFetching: boolean; refetch: () => unknown }
  hasInput: boolean
  emptyText: string
}) {
  // Without a complete selection, never show a previous (placeholder) prediction.
  if (!hasInput) return <EmptyState title="No lineup selected">{emptyText}</EmptyState>
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  if (!query.data) return <LoadingBlock label="Computing prediction" height="h-96" />
  return (
    <div className={clsx('relative', query.isFetching && 'opacity-70 transition-opacity')}>
      {query.isFetching && (
        <div className="absolute top-0 right-0">
          <Spinner label="Updating" />
        </div>
      )}
      <PredictionResult prediction={query.data} />
    </div>
  )
}

export default function PredictPage() {
  const { set, get, getNum, getAll } = useUrlState()
  const { season, seasons } = useSeasonParam()
  const teamId = getNum('team')
  const mode: Mode = get('mode') === 'build' ? 'build' : 'recorded'
  const lineupId = getNum('lineup')
  const five = getAll('five').map(Number).filter(Number.isFinite).slice(0, 5)
  const possessions = Math.min(1000, Math.max(25, getNum('poss', 100)!))
  const observed = get('observed') === '1'

  const recorded = useLineupPrediction(mode === 'recorded' ? lineupId : undefined, possessions, observed)
  const built = usePredictFive(mode === 'build' && season && teamId && five.length === 5 ? { season_id: season, team_id: teamId, player_ids: five, possessions } : undefined)

  return (
    <div>
      <PageHeader
        title="Predict a lineup’s post-break net rating"
        description="The frozen linear-regression model, trained on 2018-19 to 2023-24 and evaluated once on the held-out 2024-25 and 2025-26 seasons. Every prediction comes with the team-prior baseline and two 95% intervals."
      />

      <div className="mb-6">
        <EstimandNotice compact />
      </div>

      <FilterBar>
        <SeasonSelect seasons={seasons} value={season} onChange={(v) => set({ season: v, team: undefined, lineup: undefined, five: [] })} />
        <TeamSelect season={season} value={teamId} allowAll={false} onChange={(v) => set({ team: v, lineup: undefined, five: [] })} />
        <PossessionsControl value={possessions} onChange={(v) => set({ poss: v === 100 ? undefined : v })} />
      </FilterBar>

      {!season || !teamId ? (
        <EmptyState title="Choose a season and a team">Then pick one of the team’s recorded lineups, or build any five of its players.</EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4 lg:sticky lg:top-20 lg:self-start">
            <Segmented
              label="Lineup source"
              value={mode}
              onChange={(m) => set({ mode: m === 'build' ? 'build' : undefined })}
              options={[
                { value: 'recorded', label: 'Recorded lineup' },
                { value: 'build', label: 'Build a five' },
              ]}
            />
            {mode === 'recorded' ? (
              <>
                <RecordedPicker season={season} teamId={teamId} selected={lineupId} onSelect={(id) => set({ lineup: id })} />
                <Card>
                  <CardBody className="pt-4">
                    <Switch
                      checked={observed}
                      onChange={(v) => set({ observed: v ? 1 : undefined })}
                      label="Show what actually happened"
                      description="Fetches the realized post-break result separately, after the prediction. It is never a model input."
                    />
                  </CardBody>
                </Card>
              </>
            ) : (
              <FiveBuilder season={season} teamId={teamId} selected={five} onChange={(ids) => set({ five: ids })} />
            )}
          </div>
          <div className="min-w-0">
            {mode === 'recorded' ? (
              <ResultPanel query={recorded} hasInput={lineupId !== undefined} emptyText="Pick a recorded lineup on the left to see its prediction." />
            ) : (
              <ResultPanel query={built} hasInput={five.length === 5} emptyText={`Select ${5 - five.length} more player${5 - five.length === 1 ? '' : 's'} to see the prediction.`} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
