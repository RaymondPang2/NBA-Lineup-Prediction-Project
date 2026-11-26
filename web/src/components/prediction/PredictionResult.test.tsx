import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { Prediction } from '../../api/types'
import { fmtInterval, fmtSigned } from '../../lib/format'
import { fixture } from '../../test/fixtures'
import { ESTIMAND_TEXT } from './EstimandNotice'
import { isDisplayablePrediction, PredictionResult } from './PredictionResult'

const show = (p: Prediction) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <PredictionResult prediction={p} />
      </MemoryRouter>
    </QueryClientProvider>,
  )

describe('PredictionResult (real API response, lineup 281112)', () => {
  const p = fixture<Prediction>('prediction')

  it('always shows the prediction with its team-prior baseline and both 95% intervals', () => {
    show(p)
    expect(screen.getByTestId('predicted-net')).toHaveTextContent(fmtSigned(p.predicted_net_rating))
    expect(screen.getByTestId('team-prior')).toHaveTextContent(fmtSigned(p.baselines.team_prior))
    expect(screen.getByTestId('league-mean')).toHaveTextContent(fmtSigned(p.baselines.league_mean))
    const u = p.uncertainty
    expect(screen.getAllByText(fmtInterval(u.true_rating_interval_95.lo, u.true_rating_interval_95.hi)).length).toBeGreaterThan(0)
    expect(screen.getAllByText(fmtInterval(u.observed_rating_interval_95.lo, u.observed_rating_interval_95.hi)).length).toBeGreaterThan(0)
    expect(screen.getByTestId('model-vs-prior')).toHaveTextContent(fmtSigned(p.model_minus_team_prior, 1))
    // plain-English reading uses the same numbers
    const plain = screen.getByTestId('plain-english')
    expect(plain).toHaveTextContent(`about ${Math.abs(p.predicted_net_rating).toFixed(1)} points per 100 possessions`)
    expect(plain).toHaveTextContent('Not predicted: who wins a game, whether this lineup will be used, or how many minutes it will get')
  })

  it('states the conditional estimand next to the prediction', () => {
    show(p)
    expect(screen.getByTestId('estimand-notice')).toHaveTextContent(ESTIMAND_TEXT)
    expect(screen.getByTestId('estimand-notice')).toHaveTextContent(/not statistically better than the team-prior baseline/)
  })

  it('shows the realized post-break result only as a separate, labelled section', () => {
    show(p)
    const section = screen.getByText('What actually happened after the break').closest('section')!
    expect(within(section).getByText(/Never a model input/)).toBeInTheDocument()
    expect(within(section).getByText(fmtSigned(p.observed_post_break!.net_rating))).toBeInTheDocument()
  })

  it('lists every API note verbatim', () => {
    show(p)
    for (const n of p.notes) expect(screen.getByText(n)).toBeInTheDocument()
  })

  it('flags a hypothetical lineup and a held-out season', () => {
    show(fixture<Prediction>('prediction-five'))
    expect(screen.getByText(/Hypothetical lineup/)).toBeInTheDocument()
    expect(screen.getByText('Historical · held-out season')).toBeInTheDocument()
  })

  it('warns that a training-season prediction is a fitted value', () => {
    show({ ...p, season_used_for_training: true })
    expect(screen.getByText('Historical · in-sample season')).toBeInTheDocument()
    expect(screen.getByText('Fitted value, not a test')).toBeInTheDocument()
  })

  it('withholds the prediction when the baseline or uncertainty is missing', () => {
    const noPrior = { ...p, baselines: { ...p.baselines, team_prior: null } } as unknown as Prediction
    const noInterval = { ...p, uncertainty: { ...p.uncertainty, true_rating_interval_95: null } } as unknown as Prediction
    expect(isDisplayablePrediction(p)).toBe(true)
    expect(isDisplayablePrediction(noPrior)).toBe(false)
    expect(isDisplayablePrediction(noInterval)).toBe(false)
    show(noPrior)
    expect(screen.getByText('Prediction withheld')).toBeInTheDocument()
    expect(screen.queryByTestId('predicted-net')).not.toBeInTheDocument()
    expect(screen.queryByText(fmtSigned(p.predicted_net_rating))).not.toBeInTheDocument()
  })

  it('contributions add up to the prediction (intercept + sum)', () => {
    const sum = p.intercept + p.contributions.reduce((a, c) => a + c.contribution, 0)
    expect(sum).toBeCloseTo(p.predicted_net_rating, 9)
  })
})
