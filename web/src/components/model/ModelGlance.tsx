import clsx from 'clsx'
import type { ModelCard, ModelPerformance } from '../../api/types'
import { featureLabel } from '../../lib/features'
import { fmtInterval, fmtNum, fmtSigned } from '../../lib/format'
import { Badge, Card, CardBody, CardHeader } from '../ui/Card'
import { Explainer } from '../ui/Explainer'
import { InfoTip } from '../ui/InfoTip'

function SeasonStrip({ card, liveSeason }: { card: ModelCard; liveSeason?: string }) {
  const items = [
    ...card.trained_seasons.map((s) => ({ s, kind: 'train' as const })),
    ...card.held_out_seasons.map((s) => ({ s, kind: 'test' as const })),
    ...(liveSeason ? [{ s: liveSeason, kind: 'live' as const }] : []),
  ]
  const style = { train: 'bg-surface-3 text-ink-2', test: 'bg-accent text-accent-ink', live: 'border border-dashed border-warn text-warn' }
  return (
    <div>
      <ol className="flex flex-wrap gap-1.5" aria-label="Seasons and their role">
        {items.map((i) => (
          <li key={i.s} className={clsx('rounded-md px-2 py-1 text-xs font-medium tabular', style[i.kind])}>
            {i.s}
          </li>
        ))}
      </ol>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        <span>
          <span className="mr-1 inline-block size-2 rounded-sm bg-surface-3 ring-1 ring-line-strong" />
          Training and model selection
        </span>
        <span>
          <span className="mr-1 inline-block size-2 rounded-sm bg-accent" />
          Held-out test, used once
        </span>
        {liveSeason && (
          <span>
            <span className="mr-1 inline-block size-2 rounded-sm border border-dashed border-warn" />
            In progress: provisional, not evaluated
          </span>
        )}
      </p>
    </div>
  )
}

function RmseBars({ rows }: { rows: { label: string; value: number; lo: number; hi: number; strong?: boolean }[] }) {
  const max = Math.ceil(Math.max(...rows.map((r) => r.hi)) / 5) * 5
  return (
    <figure data-testid="rmse-comparison">
      <figcaption className="mb-3 text-sm text-ink-2">
        Typical prediction error on the two held-out seasons, in net-rating points (possession-weighted RMSE, axis from 0). <strong className="font-semibold text-ink">Lower is better.</strong>
      </figcaption>
      <div className="space-y-2.5">
        {rows.map((r) => (
          <div key={r.label} className="grid grid-cols-[8.5rem_1fr_3.5rem] items-center gap-3 sm:grid-cols-[11rem_1fr_4rem]">
            <span className={clsx('text-sm', r.strong ? 'font-semibold text-ink' : 'text-ink-2')}>{r.label}</span>
            <span className="relative h-6 rounded bg-surface-2" aria-hidden>
              <span className={clsx('absolute inset-y-0 left-0 rounded', r.strong ? 'bg-[var(--series-1)]' : 'bg-[var(--axis)]')} style={{ width: `${(r.value / max) * 100}%` }} />
            </span>
            <span className={clsx('text-right text-sm tabular', r.strong ? 'font-semibold text-ink' : 'text-ink')} data-testid={`rmse-${r.label}`}>
              {fmtNum(r.value, 2)}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">
        Scale 0 to {max} points. 95% intervals: {rows.map((r) => `${r.label} ${fmtInterval(r.lo, r.hi, 2, false)}`).join(' · ')}.
      </p>
    </figure>
  )
}

/** Plain-English summary of what the model does, how it was tested and what it achieved, from the API's verified numbers. */
export function ModelGlance({ perf, card, liveSeason }: { perf: ModelPerformance; card: ModelCard; liveSeason?: string }) {
  const pooled = perf.held_out.find((e) => e.evaluation === 'pooled')!
  const vsPrior = pooled.model_minus_team_prior
  const vsLeague = pooled.model_minus_league_mean!
  const sel = card.selection
  const cv = sel.rmse_weighted ?? {}
  const trained = `${card.trained_seasons[0]} to ${card.trained_seasons[card.trained_seasons.length - 1]}`

  return (
    <div className="space-y-6" data-testid="model-glance">
      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="What the model predicts" />
          <CardBody className="space-y-2 text-sm leading-relaxed text-ink-2">
            <p>
              The <strong className="font-semibold text-ink">expected net rating</strong> of a five-player lineup <strong className="font-semibold text-ink">after the All-Star break</strong>,
              using only what happened before it.
            </p>
            <p>
              <InfoTip term="net">Net rating</InfoTip> = points scored minus points allowed per 100 possessions. +6 means outscoring opponents by about 6 points per 100 possessions.
            </p>
            <p className="text-xs text-muted">It does not predict game winners, whether a lineup will be used, or how many minutes it gets.</p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="How it was tested" />
          <CardBody className="space-y-3 text-sm text-ink-2">
            <p>
              Built and tuned on {trained} only. Then frozen, and tested once on <InfoTip term="heldout">two seasons it never saw</InfoTip>.
            </p>
            <SeasonStrip card={card} liveSeason={liveSeason} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="The result" />
          <CardBody className="space-y-3 text-sm text-ink-2">
            <p className="flex items-start gap-2">
              <Badge tone={perf.beats_league_mean ? 'good' : 'warn'}>{perf.beats_league_mean ? '✓ Better' : '≈ Tie'}</Badge>
              <span data-testid="verdict-league">
                {perf.beats_league_mean ? 'Statistically significantly better' : 'Not significantly better'} than the <strong className="font-semibold text-ink">league-average</strong> baseline (
                {fmtSigned(vsLeague.estimate, 2)} RMSE, 95% CI {fmtInterval(vsLeague.lo, vsLeague.hi, 2)}).
              </span>
            </p>
            <p className="flex items-start gap-2">
              <Badge tone={perf.beats_team_prior ? 'good' : 'warn'}>{perf.beats_team_prior ? '✓ Better' : '≈ Tie'}</Badge>
              <span data-testid="verdict-team-prior">
                {perf.beats_team_prior ? 'Statistically significantly better' : <>Did <strong className="font-semibold text-ink">not</strong> statistically significantly outperform</>} the{' '}
                <strong className="font-semibold text-ink">team-prior</strong> baseline ({fmtSigned(vsPrior.estimate, 2)} RMSE, 95% CI {fmtInterval(vsPrior.lo, vsPrior.hi, 2)}).
              </span>
            </p>
            <p className="text-xs text-muted">
              <InfoTip term="baseline">Baselines</InfoTip> are simple benchmarks. Knowing a team’s overall strength already explains most of what can be predicted.
            </p>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Held-out test results"
          subtitle={`${pooled.n_lineups.toLocaleString('en-US')} lineups from ${card.held_out_seasons.join(' and ')} that played at least 25 possessions on each end after the break`}
        />
        <CardBody>
          <RmseBars
            rows={[
              { label: 'Linear regression', value: pooled.rmse_model.estimate, lo: pooled.rmse_model.lo, hi: pooled.rmse_model.hi, strong: true },
              { label: 'Team-prior baseline', value: pooled.rmse_team_prior.estimate, lo: pooled.rmse_team_prior.lo, hi: pooled.rmse_team_prior.hi },
              { label: 'League-average baseline', value: pooled.rmse_league_mean.estimate, lo: pooled.rmse_league_mean.lo, hi: pooled.rmse_league_mean.hi },
            ]}
          />
          <p className="mt-4 rounded-lg bg-surface-2 px-4 py-3 text-sm text-ink-2" data-testid="conclusion">
            <span className="font-medium text-ink">Pre-registered conclusion: </span>
            {perf.conclusion}
          </p>
        </CardBody>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Explainer title="What RMSE and R² mean" testId="explain-metrics">
          <p>
            <strong className="text-ink">RMSE</strong> is the typical size of a miss: {fmtNum(pooled.rmse_model.estimate, 1)} means predictions are usually off by about that many net-rating points.
            It is weighted by possessions, so lineups that played more count more.
          </p>
          <p>
            <strong className="text-ink">R²</strong> is the share of the variation in actual results the predictions explain: {fmtNum(pooled.r2_model.estimate, 3)} here. That sounds low, but
            even a perfect model could reach only about {fmtNum(pooled.r2_ceiling.estimate, 2)}, because post-break ratings over a few hundred possessions are mostly sampling noise.
          </p>
        </Explainer>
        <Explainer title="Why the seasons were split by time" testId="explain-chronological">
          <p>
            Every model was trained on earlier seasons and checked on later ones (expanding-window cross-validation), never the reverse. Shuffling seasons would let the model learn
            from the future, for example league-wide scoring trends, and look better than it really is.
          </p>
          <p>
            Inputs come only from before the All-Star break; post-break results are used only as the answer key. {card.held_out_seasons.join(' and ')} stayed locked until the model was
            frozen (its file hash is recorded, and the API re-verifies it).
          </p>
        </Explainer>
        <Explainer title="Why linear regression, not ridge or random forest" testId="explain-selection">
          <p>
            All three were compared with nested cross-validation on {trained}. Cross-validated RMSE:{' '}
            {Object.entries(cv)
              .map(([k, v]) => `${k === 'forest' ? 'random forest' : k} ${fmtNum(v, 2)}`)
              .join(', ')}
            .
          </p>
          <p>
            The rule, fixed before any result was seen: choose the <em>simplest</em> model within one standard error of the best. Linear regression was both the best and the simplest,
            and its coefficients can be read directly. The more flexible models found no extra signal to exploit.
          </p>
        </Explainer>
        <Explainer title="Why uncertainty and sample size matter" testId="explain-uncertainty">
          <p>
            A lineup’s rating over a few hundred possessions is dominated by luck: even a perfect model would still miss by about {fmtNum(pooled.rmse_noise_floor.estimate, 1)} points (the
            noise floor), compared with the model’s {fmtNum(pooled.rmse_model.estimate, 1)}.
          </p>
          <p>
            That is why every prediction is shown with a 95% interval and the team-prior baseline, and why rankings carry sample sizes. A +40 rating over 20 possessions says much less
            than +10 over 500.
          </p>
        </Explainer>
        <Explainer title="What goes into a prediction (feature engineering)" testId="explain-features">
          <p>
            {card.features_used.length} inputs, all computed from pre-break data: {card.features_used.map((f) => featureLabel(f).toLowerCase()).join('; ')}.
          </p>
          <p>
            Players’ ratings are shrunk toward a typical value in proportion to how little they played (empirical Bayes), so a hot streak over 50 possessions does not dominate.
          </p>
        </Explainer>
        <Explainer title="Provisional predictions for the season in progress" testId="explain-provisional">
          <p>
            {liveSeason ?? 'The current season'} is scored with the same frozen model from the games played so far. It was never evaluated on partial seasons, so those predictions are
            labelled provisional. An audit found they run about 2 points low early in the season and, at that stage, do not beat the team-prior baseline.
          </p>
        </Explainer>
      </div>
    </div>
  )
}
