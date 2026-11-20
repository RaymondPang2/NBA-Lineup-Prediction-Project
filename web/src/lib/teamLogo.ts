/**
 * Where team logos come from. Licensing decides the default.
 *
 * NBA and team logos are trademarks of NBA Properties, Inc. and its teams; nba.com's terms grant no licence to
 * use them without written permission. This project has no such permission, so:
 *
 *   - by default (and in any public build) NO logo image is loaded and none is bundled: <TeamLogo> draws a
 *     neutral, theme-coloured monogram of the team's abbreviation, which is factual text, not a mark;
 *   - a private/local build may opt in by setting VITE_TEAM_LOGO_URL to a URL template it is entitled to use.
 *     Placeholders: {team_id} (the NBA team ID the API already returns) and {variant} ("L" on light themes,
 *     "D" on dark themes). Example and caveats in docs/dashboard.md.
 *
 * Nothing here touches the API, the database, the model or any statistic.
 */

/** NBA franchise IDs are 1610612737–1610612766 (30 teams). Anything else gets the monogram. */
export function isNbaTeamId(id: unknown): id is number {
  return typeof id === 'number' && Number.isInteger(id) && id >= 1610612737 && id <= 1610612766
}

export type LogoVariant = 'light' | 'dark'

export function logoTemplate(raw: string | undefined = import.meta.env.VITE_TEAM_LOGO_URL): string | null {
  const t = raw?.trim()
  return t && t.includes('{team_id}') ? t : null
}

/** The image URL for a team, or null when logos are disabled or the ID is not an NBA team. */
export function teamLogoUrl(teamId: number | undefined, variant: LogoVariant, template: string | null = logoTemplate()): string | null {
  if (!template || !isNbaTeamId(teamId)) return null
  return template.replaceAll('{team_id}', String(teamId)).replaceAll('{variant}', variant === 'dark' ? 'D' : 'L')
}

/** URLs that already failed this session, so a broken logo does not flash on every re-render. */
export const failedLogoUrls = new Set<string>()

/** Whether logo images are enabled in this build at all. */
export const logosEnabled = (template: string | null = logoTemplate()): boolean => template !== null
