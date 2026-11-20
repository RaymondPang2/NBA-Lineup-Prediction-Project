import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { failedLogoUrls, isNbaTeamId, logoTemplate, logosEnabled, teamLogoUrl } from '../../lib/teamLogo'
import { TeamLogo } from './TeamLogo'

const BOS = 1610612738
const TEMPLATE = 'https://logos.example/{team_id}/{variant}.svg'

afterEach(() => {
  vi.unstubAllEnvs()
  failedLogoUrls.clear()
  document.documentElement.removeAttribute('data-theme')
})

describe('teamLogoUrl', () => {
  it('is disabled unless a template with {team_id} is configured (the licensing-safe default)', () => {
    expect(logoTemplate('')).toBeNull()
    expect(logoTemplate('https://x/logo.svg')).toBeNull()
    expect(logosEnabled(null)).toBe(false)
    expect(teamLogoUrl(BOS, 'light', null)).toBeNull()
  })

  it('maps the NBA team ID and theme into the template', () => {
    expect(teamLogoUrl(BOS, 'light', TEMPLATE)).toBe('https://logos.example/1610612738/L.svg')
    expect(teamLogoUrl(BOS, 'dark', TEMPLATE)).toBe('https://logos.example/1610612738/D.svg')
  })

  it('only accepts the 30 NBA franchise IDs', () => {
    expect(isNbaTeamId(1610612737) && isNbaTeamId(1610612766)).toBe(true)
    expect(isNbaTeamId(1610612736) || isNbaTeamId(1610612767) || isNbaTeamId(undefined)).toBe(false)
    expect(teamLogoUrl(42, 'light', TEMPLATE)).toBeNull()
  })
})

describe('TeamLogo', () => {
  it('shows a neutral monogram, not an image, when logos are disabled', () => {
    vi.stubEnv('VITE_TEAM_LOGO_URL', '')
    render(<TeamLogo teamId={BOS} abbreviation="BOS" name="Boston Celtics" />)
    expect(screen.queryByTestId('team-logo-img')).toBeNull()
    expect(screen.getByRole('img', { name: 'Boston Celtics logo' })).toHaveTextContent('BOS')
  })

  it('renders nothing inline when logos are disabled and the text already names the team', () => {
    vi.stubEnv('VITE_TEAM_LOGO_URL', '')
    const { container } = render(<TeamLogo teamId={BOS} abbreviation="BOS" whenUnavailable="hide" decorative />)
    expect(container).toBeEmptyDOMElement()
  })

  it('loads the configured image and follows the theme', () => {
    vi.stubEnv('VITE_TEAM_LOGO_URL', TEMPLATE)
    render(<TeamLogo teamId={BOS} abbreviation="BOS" name="Boston Celtics" />)
    expect(screen.getByTestId('team-logo-img')).toHaveAttribute('src', 'https://logos.example/1610612738/L.svg')
    act(() => document.documentElement.setAttribute('data-theme', 'dark'))
    return vi.waitFor(() => expect(screen.getByTestId('team-logo-img')).toHaveAttribute('src', 'https://logos.example/1610612738/D.svg'))
  })

  it('falls back to the monogram when the image fails to load', () => {
    vi.stubEnv('VITE_TEAM_LOGO_URL', TEMPLATE)
    render(<TeamLogo teamId={BOS} abbreviation="BOS" name="Boston Celtics" />)
    fireEvent.error(screen.getByTestId('team-logo-img'))
    expect(screen.queryByTestId('team-logo-img')).toBeNull()
    expect(screen.getByTestId('team-logo-fallback')).toHaveTextContent('BOS')
  })

  it('keeps table rows aligned with a generic icon when an enabled inline logo fails', () => {
    vi.stubEnv('VITE_TEAM_LOGO_URL', TEMPLATE)
    render(<TeamLogo teamId={BOS} abbreviation="BOS" whenUnavailable="hide" decorative size="xs" />)
    fireEvent.error(screen.getByTestId('team-logo-img'))
    const icon = screen.getByTestId('team-logo-fallback')
    expect(icon).toHaveAttribute('aria-hidden', 'true')
    expect(icon.querySelector('svg')).not.toBeNull()
    expect(icon).toHaveClass('size-4')
  })
})
