import { Link } from 'react-router'
import type { Prediction } from '../../api/types'
import { fmtDate, fmtInt, fmtInterval, fmtPct, fmtSigned, isNum } from '../../lib/format'
import { useSeasons, useTeams } from '../../api/hooks'
import { ChartFrame } from '../charts/ChartFrame'
import { Badge, Callout, Card, CardBody, CardHeader, Stat } from '../ui/Card'
import { isDemo } from '../../lib/demo'
import { InfoTip } from '../ui/InfoTip'
import { TeamLogo } from '../ui/TeamLogo'
import { ContributionsChart, ContributionsTable } from './ContributionsChart'
import { EstimandNotice } from './EstimandNotice'
import { ProvisionalNotice } from './ProvisionalNotice'
import { IntervalChart } from './IntervalChart'

/**
 * A prediction is only displayable with its team-prior baseline and both uncertainty intervals.
 * The schema already requires them; this also guards against null/NaN values at runtime.
 */
export function isDisplayablePrediction(p: Prediction | undefined | null): p is Prediction {
  if (!p) return false
  const u = p.uncertainty
  return (
    isNum(p.predicted_net_rating) &&
    isNum(p.baselines?.team_prior) &&
    isNum(u?.model_sd) &&
    isNum(u?.total_sd) &&
    isNum(u?.true_rating_interval_95?.lo) &&
    isNum(u?.true_rating_interval_95?.hi) &&
    isNum(u?.observed_rating_interval_95?.lo) &&
    isNum(u?.observed_rating_interval_95?.hi)
  )
}

function Dl({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="tabular divide-y divide-line text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-ink-2">{k}</dt>
          <dd className="text-right font-medium text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function PredictionResult({ prediction }: { prediction: Prediction }) {
  const teams = useTeams(prediction.season_id)
  const seasons = useSeasons()
  if (!isDisplayablePrediction(prediction)) {
    return (
      <Callout tone="warn" title="Prediction withheld">
        The API response is missing the team-prior baseline or the uncertainty intervals, so the prediction is not shown on its own.
      </Callout>
    )
  }
  const p = prediction
  const u = p.uncertainty
  const teamName = teams.data?.find((t) => t.team_id === p.team_id)?.team_name
  const preWindow = seasons.data?.find((x) => x.season_id === p.season_id)?.windows.find((w) => w.window_type === 'pre_asb')
  const inputsThrough = p.provisional ? (p.data_cutoff ?? preWindow?.date_to) : preWindow?.date_to
  const obs = p.observed_post_break
  const observedNet = obs && isNum(obs.net_rating) ? obs.net_rating : null

  return (
    <div className="space-y-5" data-testid="prediction-result">
      <div className="flex flex-wrap items-center gap-2">
        <TeamLogo teamId={p.team_id} abbreviation={p.team_abbreviation} size="md" decorative />
        <h2 className="text-lg font-semibold text-ink" data-testid="prediction-team">
          {teamName ? `${teamName} (${p.team_abbreviation})` : p.team_abbreviation} · {p.season_id}
        </h2>
        {isDemo() ? (
          <Badge tone="warn" title="Fictional teams and players: the public demo's synthetic data">
            Synthetic demo data
          </Badge>
        ) : p.provisional ? (
          <Badge tone="warn" title="Season in progress: season-to-date inputs, not independently validated">
            Provisional · season in progress
          </Badge>
        ) : p.season_used_for_training ? (
          <Badge tone="warn" title="This season's post-break results were training labels">
            Historical · in-sample season
          </Badge>
        ) : (
          <Badge tone="accent" title="Never used for training or tuning">
            Historical · held-out season
          </Badge>
        )}
        {p.lineup_id !== null && p.lineup_id !== undefined ? (
          <Link to={`/lineups/${p.lineup_id}`} className="text-sm text-accent hover:underline">
            Recorded lineup #{p.lineup_id} ›
          </Link>
        ) : (
          <Badge>Hypothetical lineup (never played together)</Badge>
        )}
      </div>
      {inputsThrough && (
        <p className="-mt-3 text-sm text-ink-2" data-testid="inputs-through">
          Inputs: {p.season_id} pre-All-Star-break games through <span className="font-medium text-ink">{fmtDate(inputsThrough)}</span>
          {p.provisional ? ' (latest data cutoff)' : ''}. Nothing after that date is used.
        </p>
      )}

      <ul className="flex flex-wrap gap-1.5" aria-label="Players">
        {p.players.map((pl) => (
          <li key={pl.player_id} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface-2 px-2.5 py-0.5 text-sm text-ink">
            {pl.player_name}
            {pl.new_to_team && <Badge tone="warn">new to team</Badge>}
            {!pl.has_pre_break_data && <Badge tone="warn">no pre-break data</Badge>}
          </li>
        ))}
      </ul>

      <EstimandNotice />

      {p.provisional && <ProvisionalNotice seasonId={p.season_id} cutoff={p.data_cutoff} progress={p.season_progress} />}

      {p.season_used_for_training && (
        <Callout tone="warn" title="Fitted value, not a test">
          {p.season_id} was a training season: its post-break results were labels the model learned from. Judge accuracy on the held-out seasons 2024-25 and 2025-26.
        </Callout>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          emphasis
          label="Predicted net rating"
          testId="predicted-net"
          value={fmtSigned(p.predicted_net_rating)}
          detail={`95% interval ${fmtInterval(u.true_rating_interval_95.lo, u.true_rating_interval_95.hi)}`}
        />
        <Stat label="Team-prior baseline" testId="team-prior" value={fmtSigned(p.baselines.team_prior)} detail="The team’s rating from its other lineups" />
        <Stat label="Prediction − baseline" testId="model-vs-prior" value={fmtSigned(p.model_minus_team_prior, 1)} detail="What the model adds to the team’s strength" />
        <Stat label="League average" testId="league-mean" value={fmtSigned(p.baselines.league_mean)} detail="Average post-break net of training lineups" />
      </div>

      <div className="rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm leading-relaxed text-ink-2" data-testid="plain-english">
        <p className="font-medium text-ink">In plain English</p>
        <p className="mt-1">
          A predicted net rating of <strong className="font-semibold text-ink">{fmtSigned(p.predicted_net_rating)}</strong> means this lineup is expected to{' '}
          {p.predicted_net_rating >= 0 ? 'outscore opponents' : 'be outscored'} by about {Math.abs(p.predicted_net_rating).toFixed(1)} points per 100 possessions if it plays after the
          All-Star break. From the team’s overall strength alone you would expect {fmtSigned(p.baselines.team_prior)}; the model adjusts that by {fmtSigned(p.model_minus_team_prior)}.
          Its true quality most likely lies between {fmtSigned(u.true_rating_interval_95.lo)} and {fmtSigned(u.true_rating_interval_95.hi)} (95%), so treat small differences between
          lineups as noise.
        </p>
        <p className="mt-2 text-xs text-muted">
          Not predicted: who wins a game, whether this lineup will be used, or how many minutes it will get.
        </p>
        <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
          <span className="text-muted">Terms:</span>
          <InfoTip term="net">Net rating</InfoTip>
          <InfoTip term="baseline">Team-prior baseline</InfoTip>
          <InfoTip term="interval">95% interval</InfoTip>
          <InfoTip term="noise">Sampling noise</InfoTip>
          {p.provisional && <InfoTip term="provisional">Provisional</InfoTip>}
        </p>
      </div>

      <Card>
        <CardHeader
          title="Prediction and uncertainty"
          subtitle="Net rating, points per 100 possessions. Both intervals are 95% Normal approximations."
        />
        <CardBody>
          <IntervalChart prediction={p} observed={observedNet} />
          <div className="mt-4 grid gap-4 text-sm text-ink-2 md:grid-cols-2">
            <p>
              <strong className="font-semibold text-ink">True-quality interval</strong> ({fmtInterval(u.true_rating_interval_95.lo, u.true_rating_interval_95.hi)}): where the lineup’s
              underlying post-break quality plausibly lies, given the model’s error (SD {u.model_sd.toFixed(2)}).
            </p>
            <p>
              <strong className="font-semibold text-ink">Observed-rating interval</strong> ({fmtInterval(u.observed_rating_interval_95.lo, u.observed_rating_interval_95.hi)}): the
              rating you might actually see after {u.possessions.toLocaleString()} possessions per end. Sampling noise (SD {u.sampling_sd.toFixed(2)}) dominates at typical sample sizes.
            </p>
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Uncertainty" subtitle="Two independent sources" />
          <CardBody>
            <Dl
              rows={[
                ['Model SD (about true quality)', u.model_sd.toFixed(2)],
                [`Sampling SD at ${u.possessions.toLocaleString()} poss.`, u.sampling_sd.toFixed(2)],
                ['Total SD', u.total_sd.toFixed(2)],
                ['True quality, 95%', fmtInterval(u.true_rating_interval_95.lo, u.true_rating_interval_95.hi)],
                ['Observed rating, 95%', fmtInterval(u.observed_rating_interval_95.lo, u.observed_rating_interval_95.hi)],
              ]}
            />
            <p className="mt-3 text-xs text-muted">{u.method}</p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Pre-break evidence" subtitle="The only inputs the model sees" />
          <CardBody>
            <Dl
              rows={[
                ['Lineup possessions (own / opponent)', `${fmtInt(p.pre_break.poss)} / ${fmtInt(p.pre_break.opp_poss)}`],
                ['Lineup pre-break net rating', fmtSigned(p.pre_break.net_rating)],
                ['Reliability of that rating', fmtPct(p.pre_break.reliability)],
                ['Team net rating, other lineups', fmtSigned(p.pre_break.team_net_rating_excluding_lineup)],
                ['Model intercept (average lineup)', fmtSigned(p.intercept, 2)],
              ]}
            />
            <p className="mt-3 text-xs text-muted">
              Reliability is the share of the raw rating’s variance that is signal rather than sampling noise. Low reliability is why the model shrinks a lineup’s own record toward its team.
            </p>
          </CardBody>
        </Card>
      </div>

      {obs && (
        <Card>
          <CardHeader
            title="What actually happened after the break"
            subtitle="Fetched separately, after the prediction. Never a model input."
          />
          <CardBody>
            {observedNet === null ? (
              <p className="text-sm text-ink-2">This lineup did not play after the break, so it is outside the conditional estimand and has no realized rating.</p>
            ) : (
              <Dl
                rows={[
                  ['Post-break possessions (own / opponent)', `${fmtInt(obs.poss)} / ${fmtInt(obs.opp_poss)}`],
                  ['Realized post-break net rating', fmtSigned(observedNet)],
                  ['Prediction error (realized − predicted)', fmtSigned(observedNet - p.predicted_net_rating)],
                  ['Inside the observed 95% interval for that sample?', withinObserved(p, obs.poss, obs.opp_poss ?? obs.poss, observedNet)],
                  ['In the held-out evaluation sample', obs.in_evaluation_sample ? 'Yes (≥ 25 poss. per end)' : 'No'],
                ]}
              />
            )}
          </CardBody>
        </Card>
      )}

      <ChartFrame
        title="Why this prediction"
        subtitle="Each feature’s contribution relative to an average training lineup (the intercept). Prediction = intercept + sum of contributions."
        table={<ContributionsTable contributions={p.contributions} />}
      >
        <ContributionsChart contributions={p.contributions} />
      </ChartFrame>

      <Card>
        <CardHeader title="Notes from the API" subtitle="Returned with every prediction" />
        <CardBody>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
            {p.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </div>
  )
}

/** Compare the realized rating with an interval sized for the possessions it was actually measured over. */
function withinObserved(p: Prediction, poss: number, oppPoss: number, net: number): string {
  if (poss <= 0 || oppPoss <= 0) return '—'
  // sampling_sd = sqrt(K·2/N) at N = uncertainty.possessions, so K = sampling_sd²·N/2 (the backend's K).
  const k = (p.uncertainty.sampling_sd ** 2 * p.uncertainty.possessions) / 2
  const sd = Math.sqrt(p.uncertainty.model_sd ** 2 + k * (1 / poss + 1 / oppPoss))
  const lo = p.predicted_net_rating - 1.959964 * sd
  const hi = p.predicted_net_rating + 1.959964 * sd
  return `${net >= lo && net <= hi ? 'Yes' : 'No'} (${fmtInterval(lo, hi)} at ${fmtInt(poss)} poss.)`
}

