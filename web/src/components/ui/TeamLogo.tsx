import clsx from 'clsx'
import { useState } from 'react'
import { failedLogoUrls, teamLogoUrl } from '../../lib/teamLogo'
import { useResolvedTheme } from '../../lib/useResolvedTheme'

/**
 * One team mark, used everywhere a team is identified (selectors, headers, ranking and lineup tables).
 *
 * Image when logos are enabled (VITE_TEAM_LOGO_URL, see lib/teamLogo.ts); otherwise, or when the image fails,
 * a fallback that never uses a team's marks:
 *   - `whenUnavailable="monogram"` (headers): a neutral badge with the team abbreviation;
 *   - `whenUnavailable="hide"` (inline next to text that already names the team): nothing while logos are
 *     disabled, so tables and selects look exactly as before; a generic icon if an enabled logo fails, so
 *     rows stay aligned.
 * Sizes are fixed boxes, so every mark lines up whatever the image's aspect ratio.
 */

const SIZE = {
  xs: { box: 'size-4', text: 'text-[6px]' },
  sm: { box: 'size-5', text: 'text-[7px]' },
  md: { box: 'size-8', text: 'text-[10px]' },
  lg: { box: 'size-11', text: 'text-[13px]' },
} as const

export type TeamLogoSize = keyof typeof SIZE

function GenericTeamIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" className={className} aria-hidden>
      <circle cx="10" cy="10" r="7.5" />
      <path d="M2.5 10h15M10 2.5v15M5 4.4c2 1.6 2.9 3.5 2.9 5.6S7 14 5 15.6M15 4.4c-2 1.6-2.9 3.5-2.9 5.6s.9 4 2.9 5.6" />
    </svg>
  )
}

export function TeamLogo({
  teamId,
  abbreviation,
  name,
  size = 'sm',
  whenUnavailable = 'monogram',
  decorative = false,
  className,
}: {
  teamId: number | undefined
  abbreviation?: string
  /** Full team name, for the accessible label. */
  name?: string
  size?: TeamLogoSize
  whenUnavailable?: 'monogram' | 'hide'
  /** True when adjacent text already names the team: the mark is hidden from screen readers. */
  decorative?: boolean
  className?: string
}) {
  const theme = useResolvedTheme()
  const url = teamLogoUrl(teamId, theme)
  const [failed, setFailed] = useState<string | null>(null)
  const s = SIZE[size]
  const label = `${name ?? abbreviation ?? 'Team'} logo`
  const a11y = decorative ? { 'aria-hidden': true as const } : { role: 'img' as const, 'aria-label': label }
  const box = clsx('inline-flex shrink-0 items-center justify-center align-middle', s.box, className)

  if (url && failed !== url && !failedLogoUrls.has(url)) {
    return (
      <img
        src={url}
        alt={decorative ? '' : label}
        aria-hidden={decorative || undefined}
        loading="lazy"
        decoding="async"
        draggable={false}
        data-testid="team-logo-img"
        className={clsx(box, 'object-contain')}
        onError={() => {
          failedLogoUrls.add(url)
          setFailed(url)
        }}
      />
    )
  }

  const enabledButBroken = url !== null
  if (whenUnavailable === 'hide' && !enabledButBroken) return null

  if (whenUnavailable === 'monogram' && abbreviation) {
    return (
      <span
        {...a11y}
        data-testid="team-logo-fallback"
        className={clsx(box, s.text, 'rounded-full bg-surface-3 font-semibold tracking-tight text-ink-2 ring-1 ring-line-strong select-none')}
      >
        <span aria-hidden>{abbreviation.slice(0, 3)}</span>
      </span>
    )
  }

  return (
    <span {...a11y} data-testid="team-logo-fallback" className={clsx(box, 'text-muted')}>
      <GenericTeamIcon className="size-full" />
    </span>
  )
}
