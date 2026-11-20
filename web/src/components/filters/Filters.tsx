import clsx from 'clsx'
import { useEffect, useId, useRef, useState } from 'react'
import { usePlayer, usePlayers, useTeams } from '../../api/hooks'
import type { Season } from '../../api/types'
import { logosEnabled } from '../../lib/teamLogo'
import { Field, SelectField, TextInput } from '../ui/Controls'
import { TeamLogo } from '../ui/TeamLogo'

export function seasonLabel(s: Season): string {
  const tags = [s.role === 'held_out' ? 'held-out' : null, s.is_irregular ? 'irregular' : null].filter(Boolean)
  return tags.length ? `${s.season_id} (${tags.join(', ')})` : s.season_id
}

export function SeasonSelect({ seasons, value, onChange }: { seasons: Season[]; value: string | undefined; onChange: (v: string) => void }) {
  if (!value) return <SelectField label="Season" value="" options={[{ value: '', label: 'Loading…' }]} onChange={() => {}} disabled />
  return (
    <SelectField
      label="Season"
      value={value}
      onChange={onChange}
      options={[...seasons].reverse().map((s) => ({ value: s.season_id, label: seasonLabel(s) }))}
    />
  )
}

/** Teams that recorded lineups in the season. `allowAll` adds an "All teams" option (value 0). */
export function TeamSelect({
  season,
  value,
  onChange,
  allowAll = true,
  label = 'Team',
}: {
  season: string | undefined
  value: number | undefined
  onChange: (v: number | undefined) => void
  allowAll?: boolean
  label?: string
}) {
  const teams = useTeams(season)
  const list = [...(teams.data ?? [])].sort((a, b) => a.team_name.localeCompare(b.team_name))
  const options = [
    ...(allowAll ? [{ value: 0, label: 'All teams' }] : value === undefined ? [{ value: 0, label: 'Select a team…' }] : []),
    ...list.map((t) => ({ value: t.team_id, label: `${t.team_name} (${t.abbreviation})` })),
  ]
  const current = list.find((t) => t.team_id === value)
  return (
    <SelectField
      label={label}
      value={value ?? 0}
      disabled={teams.isPending}
      leading={current && logosEnabled() ? <TeamLogo teamId={current.team_id} abbreviation={current.abbreviation} size="sm" whenUnavailable="hide" decorative /> : undefined}
      options={teams.isPending ? [{ value: 0, label: 'Loading teams…' }] : options}
      onChange={(v) => onChange(v === 0 ? undefined : v)}
    />
  )
}

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function PlayerChip({ playerId, season, onRemove }: { playerId: number; season?: string; onRemove: () => void }) {
  const p = usePlayer(playerId, season)
  const name = p.data?.player_name ?? (p.isPending ? '…' : `#${playerId}`)
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft py-0.5 pr-1 pl-2.5 text-xs font-medium text-accent">
      {name}
      <button type="button" onClick={onRemove} aria-label={`Remove ${name}`} className="rounded-full px-1 hover:bg-accent/15">
        ×
      </button>
    </span>
  )
}

/**
 * Search players by name (GET /players?search=) and add up to `max` of them as filters.
 * Keyboard: ↑/↓ to move, Enter to add, Escape to close.
 */
export function PlayerPicker({
  season,
  teamId,
  selected,
  onChange,
  max = 5,
  label = 'Players',
}: {
  season: string | undefined
  teamId?: number
  selected: number[]
  onChange: (ids: number[]) => void
  max?: number
  label?: string
}) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const search = useDebounced(text.trim())
  const listId = useId()
  const box = useRef<HTMLDivElement>(null)
  const enabled = !!season && search.length >= 2
  const results = usePlayers({ season: season!, team_id: teamId, search, page_size: 12, sort: 'pre_minutes', order: 'desc' }, enabled)
  const items = enabled ? (results.data?.items ?? []).filter((p) => !selected.includes(p.player_id)) : []
  const full = selected.length >= max

  useEffect(() => {
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const add = (id: number) => {
    if (!selected.includes(id) && !full) onChange([...selected, id])
    setText('')
    setOpen(false)
    setActive(0)
  }

  return (
    <Field label={label} hint={full ? `Up to ${max} players` : undefined} className="col-span-2 sm:!w-72">
      {(id) => (
        <div ref={box} className="relative">
          <TextInput
            id={id}
            role="combobox"
            aria-expanded={open && items.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            placeholder={full ? `${max} players selected` : season ? 'Search by name…' : 'Choose a season'}
            disabled={full || !season}
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setOpen(true)
              setActive(0)
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActive((a) => Math.min(a + 1, items.length - 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActive((a) => Math.max(a - 1, 0))
              } else if (e.key === 'Enter' && items[active]) {
                e.preventDefault()
                add(items[active].player_id)
              } else if (e.key === 'Escape') setOpen(false)
            }}
          />
          {open && enabled && (
            <ul id={listId} role="listbox" className="absolute z-30 mt-1 max-h-72 w-full min-w-64 overflow-auto rounded-md border border-line-strong bg-surface py-1 shadow-lg">
              {results.isPending && <li className="px-3 py-2 text-sm text-muted">Searching…</li>}
              {results.error && <li className="px-3 py-2 text-sm text-bad">Search failed</li>}
              {!results.isPending && !results.error && items.length === 0 && <li className="px-3 py-2 text-sm text-muted">No players match “{search}”</li>}
              {items.map((p, i) => (
                <li
                  key={`${p.player_id}-${p.team_id}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    add(p.player_id)
                  }}
                  onMouseEnter={() => setActive(i)}
                  className={clsx('flex cursor-pointer items-center justify-between gap-3 px-3 py-1.5 text-sm', i === active && 'bg-surface-2')}
                >
                  <span className="truncate text-ink">{p.player_name}</span>
                  <span className="shrink-0 text-xs text-muted">{p.team_abbreviation}</span>
                </li>
              ))}
            </ul>
          )}
          {selected.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {selected.map((pid) => (
                <PlayerChip key={pid} playerId={pid} season={season} onRemove={() => onChange(selected.filter((x) => x !== pid))} />
              ))}
            </div>
          )}
        </div>
      )}
    </Field>
  )
}
