import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/render'
import { isDemo } from './demo'

afterEach(() => vi.unstubAllEnvs())

describe('public demo build', () => {
  it('is off unless VITE_DEMO_MODE=1', () => {
    expect(isDemo(undefined)).toBe(false)
    expect(isDemo('0')).toBe(false)
    expect(isDemo('1')).toBe(true)
  })

  it('labels every page as synthetic and hides the real-data freshness status', async () => {
    vi.stubEnv('VITE_DEMO_MODE', '1')
    renderApp('/?season=2025-26')
    expect(await screen.findByTestId('demo-banner')).toHaveTextContent('Synthetic demo data')
    expect(screen.getByTestId('demo-banner')).toHaveTextContent('fictional')
    expect(screen.getByTestId('demo-footer')).toHaveTextContent('every team, player and statistic is fictional')
    expect(await screen.findByTestId('hero-demo-note')).toHaveTextContent('synthetic')
    await screen.findByTestId('api-health')
    expect(screen.queryByTestId('data-freshness')).toBeNull()
  })

  it('says the model results are real on the model page', async () => {
    vi.stubEnv('VITE_DEMO_MODE', '1')
    renderApp('/model')
    expect(await screen.findByTestId('model-demo-note')).toHaveTextContent('measured on actual NBA seasons')
  })

  it('shows nothing demo-related in the normal build', async () => {
    renderApp('/?season=2025-26')
    await screen.findByTestId('hero')
    expect(screen.queryByTestId('demo-banner')).toBeNull()
    expect(screen.queryByTestId('hero-demo-note')).toBeNull()
  })
})
