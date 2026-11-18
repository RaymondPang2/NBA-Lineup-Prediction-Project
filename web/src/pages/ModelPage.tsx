import { useState } from 'react'
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useModelCard, useModelPerformance } from '../api/hooks'
import type { Coefficient, EvaluationSummary, ModelCard, ModelPerformance } from '../api/types'
import { C, ChartFrame, TooltipBox } from '../components/charts/ChartFrame'
import { DotWhisker } from '../components/charts/DotWhisker'
import { EstimandNotice } from '../components/prediction/EstimandNotice'
import { Badge, Callout, Card, CardBody, CardHeader, PageHeader, Stat } from '../components/ui/Card'
import { Segmented } from '../components/ui/Controls'
import { ErrorState, LoadingBlock } from '../components/ui/States'
import { TableWrap, Td, Th } from '../components/ui/Table'
import { axisTicks } from '../lib/axis'
import { featureLabel } from '../lib/features'
import { useWidth } from '../lib/useWidth'
import { fmtInt, fmtInterval, fmtNum, fmtSigned } from '../lib/format'

function evalLabel(e: string): string {
  if (e === 'pooled') return 'Held-out, pooled'
  if (/^\d{4}-\d{2}$/.test(e)) return `Held-out ${e}`
  return 'Development CV'
}

function allEvaluations(p: ModelPerformance): EvaluationSummary[] {
  return [p.development_cv, ...p.held_out]
}

function est(e: { estimate: number; lo: number; hi: number } | null | undefined, digits = 2, signed = false) {
  if (!e) return '—'
  const f = signed ? fmtSigned : fmtNum
  return `${f(e.estimate, digits)} (${fmtInterval(e.lo, e.hi, digits, signed)})`
}

function Verdict({ p }: { p: ModelPerformance }) {
  return (
    <Card className="overflow-hidden">
      <div className="grid gap-px bg-line sm:grid-cols-2">
        <div className="bg-surface p-5">
          <div className="flex items-center gap-2">
            <Badge tone={p.beats_team_prior ? 'good' : 'warn'}>{p.beats_team_prior ? '✓ Beats' : '≈ Ties'}</Badge>
            <h2 className="font-semibold text-ink">vs the team-prior baseline</h2>
          </div>
          <p className="mt-2 text-sm text-ink-2">
            {p.beats_team_prior
              ? 'The model’s held-out error is significantly lower than the team prior’s.'
              : 'Not statistically better: the 95% interval for the RMSE difference includes zero. The team’s own pre-break strength explains almost everything the model can.'}
          </p>
        </div>
        <div className="bg-surface p-5">
          <div className="flex items-center gap-2">
            <Badge tone={p.beats_league_mean ? 'good' : 'warn'}>{p.beats_league_mean ? '✓ Beats' : '≈ Ties'}</Badge>
            <h2 className="font-semibold text-ink">vs the league mean</h2>
          </div>
          <p className="mt-2 text-sm text-ink-2">
            {p.beats_league_mean ? 'Significantly better than predicting the same league-average rating for every lineup.' : 'Not distinguishable from a constant.'}
          </p>
        </div>
      </div>
      <p className="border-t border-line bg-surface-2 px-5 py-3 text-sm text-ink-2" data-testid="conclusion">
        <span className="font-medium text-ink">Pre-registered conclusion: </span>
        {p.conclusion}
      </p>
    </Card>
  )
}

function MetricsTable({ evals }: { evals: EvaluationSummary[] }) {
  const rows: [string, (e: EvaluationSummary) => string][] = [
    ['Lineups', (e) => fmtInt(e.n_lineups)],
    ['RMSE · model', (e) => est(e.rmse_model)],
    ['RMSE · team prior', (e) => est(e.rmse_team_prior)],
    ['RMSE · league mean', (e) => est(e.rmse_league_mean)],
    ['RMSE · noise floor', (e) => est(e.rmse_noise_floor)],
    ['Model − team prior', (e) => est(e.model_minus_team_prior, 2, true)],
    ['Model − league mean', (e) => est(e.model_minus_league_mean, 2, true)],
    ['R² · model', (e) => est(e.r2_model, 3)],
    ['R² · ceiling', (e) => est(e.r2_ceiling, 3)],
    ['Calibration slope', (e) => est(e.calibration_slope)],
  ]
  return (
    <TableWrap label="All evaluation metrics">
      <thead>
        <tr>
          <Th align="left">Metric (95% CI)</Th>
          {evals.map((e) => (
            <Th key={e.evaluation}>{evalLabel(e.evaluation)}</Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, f]) => (
          <tr key={label}>
            <Td align="left" className="text-ink-2">
              {label}
            </Td>
            {evals.map((e) => (
              <Td key={e.evaluation} className="text-ink">
                {f(e)}
              </Td>
            ))}
          </tr>
        ))}
      </tbody>
    </TableWrap>
  )
}

function CoefficientChart({ coefficients }: { coefficients: Coefficient[] }) {
  const data = [...coefficients].sort((a, b) => Math.abs(b.coefficient) - Math.abs(a.coefficient)).map((c) => ({ ...c, label: featureLabel(c.feature) }))
  const lim = Math.ceil(Math.max(1, ...data.map((d) => Math.abs(d.coefficient))))
  const { ref, width } = useWidth<HTMLDivElement>()
  const narrow = width < 520
  return (
    <div ref={ref} className="min-w-0" style={{ height: 36 + data.length * 30 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }} barCategoryGap={6}>
          <XAxis type="number" domain={[-lim, lim]} ticks={axisTicks(lim, narrow)} tickFormatter={(v: number) => fmtSigned(v, 0)} tickLine={false} />
          <YAxis type="category" dataKey="label" width={narrow ? 128 : 200} tickLine={false} axisLine={false} interval={0} tick={{ fontSize: narrow ? 11 : 12 }} />
          <ReferenceLine x={0} stroke={C.axis} />
          <Tooltip
            cursor={{ fill: 'var(--surface-2)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const d = payload[0].payload as Coefficient & { label: string }
              return (
                <TooltipBox
                  title={d.label}
                  rows={[
                    { label: 'Per 1 SD of feature', value: fmtSigned(d.coefficient, 2) },
                    { label: 'Training mean', value: fmtNum(d.training_mean, 2) },
                    { label: 'Training SD', value: fmtNum(d.training_sd, 2) },
                  ]}
                />
              )
            }}
          />
          <Bar dataKey="coefficient" radius={4} isAnimationActive={false}>
            {data.map((d) => (
              <Cell key={d.feature} fill={d.coefficient >= 0 ? C.pos : C.neg} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function CardDetails({ card }: { card: ModelCard }) {
  const dropped = card.features_in.filter((f) => !card.features_used.includes(f))
  const selection = card.selection as { rule?: string; chosen?: string; rmse_weighted?: Record<string, number>; se_of_difference_from_best?: Record<string, number> }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <ChartFrame
        title="Standardized coefficients"
        subtitle="Change in predicted net rating per one-SD increase in each feature (training scale). Blue raises the prediction, red lowers it."
        table={
          <TableWrap label="Coefficients">
            <thead>
              <tr>
                <Th align="left">Feature</Th>
                <Th>Coef. / SD</Th>
                <Th>Training mean</Th>
                <Th>Training SD</Th>
              </tr>
            </thead>
            <tbody>
              {card.coefficients.map((c) => (
                <tr key={c.feature}>
                  <Td align="left">
                    <span className="text-ink">{featureLabel(c.feature)}</span>
                    <span className="block max-w-sm text-xs whitespace-normal text-muted">{c.description}</span>
                  </Td>
                  <Td>{fmtSigned(c.coefficient, 2)}</Td>
                  <Td>{fmtNum(c.training_mean, 2)}</Td>
                  <Td>{fmtNum(c.training_sd, 2)}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        }
        footer={dropped.length ? `Pruned for collinearity (VIF) before fitting: ${dropped.map(featureLabel).join(', ')}.` : undefined}
      >
        <CoefficientChart coefficients={card.coefficients} />
      </ChartFrame>

      <div className="space-y-6">
        <Card>
          <CardHeader title="Model selection" subtitle={selection.rule ? `Rule: ${selection.rule}` : undefined} />
          <CardBody>
            {selection.rmse_weighted && (
              <TableWrap label="Candidate models">
                <thead>
                  <tr>
                    <Th align="left">Candidate</Th>
                    <Th>Dev. RMSE</Th>
                    <Th>SE of gap to best</Th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(selection.rmse_weighted).map(([name, rmse]) => (
                    <tr key={name}>
                      <Td align="left">
                        <span className="capitalize">{name}</span> {name === selection.chosen && <Badge tone="accent">chosen</Badge>}
                      </Td>
                      <Td>{fmtNum(rmse, 3)}</Td>
                      <Td>{fmtNum(selection.se_of_difference_from_best?.[name], 3)}</Td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            )}
            <p className="mt-3 text-xs text-muted">
              Linear regression, ridge and a random forest were compared with nested, expanding-window cross-validation on 2018-19 to 2023-24 only. Within one standard error of
              the best, the simplest model wins.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Frozen artifact" />
          <CardBody>
            <dl className="space-y-2 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <dt className="text-ink-2">Model</dt>
                <dd className="font-medium text-ink">{card.label}</dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <dt className="text-ink-2">Frozen</dt>
                <dd className="text-ink">{new Date(card.frozen_at_utc).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })} UTC</dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <dt className="text-ink-2">Trained on</dt>
                <dd className="text-ink">
                  {card.trained_seasons[0]} to {card.trained_seasons[card.trained_seasons.length - 1]}
                </dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <dt className="text-ink-2">Held out</dt>
                <dd className="text-ink">{card.held_out_seasons.join(', ')}</dd>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <dt className="text-ink-2">Sample weight</dt>
                <dd className="text-ink">{card.sample_weight}</dd>
              </div>
              <div>
                <dt className="flex items-center gap-2 text-ink-2">
                  Artifact SHA-256 {card.artifact_verified ? <Badge tone="good">✓ verified now</Badge> : <Badge tone="bad">✗ mismatch</Badge>}
                </dt>
                <dd className="mt-1 font-mono text-xs break-all text-ink" data-testid="artifact-sha">
                  {card.artifact_sha256}
                </dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-muted">The API re-hashes the model file and fingerprints its in-memory coefficients on every request to this page.</p>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function UseLists({ card }: { card: ModelCard }) {
  const lists: { title: string; items: string[]; tone: 'good' | 'bad' | 'warn' }[] = [
    { title: 'Appropriate use', items: card.appropriate_use, tone: 'good' },
    { title: 'Not for', items: card.not_for, tone: 'bad' },
    { title: 'Limitations', items: card.limitations, tone: 'warn' },
  ]
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      {lists.map((l) => (
        <Card key={l.title}>
          <CardHeader title={l.title} />
          <CardBody>
            <ul className="space-y-2 text-sm text-ink-2">
              {l.items.map((it) => (
                <li key={it} className="flex gap-2">
                  <span aria-hidden className={l.tone === 'good' ? 'text-good' : l.tone === 'bad' ? 'text-bad' : 'text-warn'}>
                    {l.tone === 'good' ? '✓' : l.tone === 'bad' ? '✗' : '!'}
                  </span>
                  <span>{it}</span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ))}
    </div>
  )
}

export default function ModelPage() {
  const perf = useModelPerformance()
  const card = useModelCard()
  const [evalKey, setEvalKey] = useState('pooled')

  return (
    <div>
      <PageHeader
        title="Model performance"
        description="How the frozen model compares with simple baselines, measured once on seasons it never saw. Errors are possession-weighted RMSE in net-rating points; intervals are 95% team-season cluster bootstrap CIs."
      />

      {perf.error ? (
        <ErrorState error={perf.error} onRetry={() => perf.refetch()} />
      ) : !perf.data ? (
        <LoadingBlock height="h-96" label="Loading evaluation" />
      ) : (
        (() => {
          const p = perf.data
          const evals = allEvaluations(p)
          const sel = evals.find((e) => e.evaluation === evalKey) ?? evals[evals.length - 1]
          const methodRows = [
            { label: 'Model', e: sel.rmse_model },
            { label: 'Team prior', e: sel.rmse_team_prior },
            { label: 'League mean', e: sel.rmse_league_mean },
            { label: 'Noise floor', e: sel.rmse_noise_floor },
          ]
          return (
            <div className="space-y-6">
              <Verdict p={p} />

              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold text-ink">{evalLabel(sel.evaluation)}</h2>
                <Segmented
                  label="Evaluation"
                  value={sel.evaluation}
                  onChange={setEvalKey}
                  options={evals.map((e) => ({ value: e.evaluation, label: e.evaluation === 'pooled' ? 'Pooled' : /^\d/.test(e.evaluation) ? e.evaluation : 'Dev CV' }))}
                />
              </div>

              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label="Model RMSE" value={fmtNum(sel.rmse_model.estimate, 2)} detail={`95% CI ${fmtInterval(sel.rmse_model.lo, sel.rmse_model.hi, 2, false)} · ${fmtInt(sel.n_lineups)} lineups`} />
                <Stat
                  label="Model − team prior"
                  value={fmtSigned(sel.model_minus_team_prior.estimate, 2)}
                  detail={`95% CI ${fmtInterval(sel.model_minus_team_prior.lo, sel.model_minus_team_prior.hi, 2)} · negative = model better`}
                />
                <Stat
                  label="Model − league mean"
                  value={fmtSigned(sel.model_minus_league_mean?.estimate, 2)}
                  detail={sel.model_minus_league_mean ? `95% CI ${fmtInterval(sel.model_minus_league_mean.lo, sel.model_minus_league_mean.hi, 2)}` : undefined}
                />
                <Stat label="R², model vs ceiling" value={`${fmtNum(sel.r2_model.estimate, 3)} / ${fmtNum(sel.r2_ceiling.estimate, 3)}`} detail="Ceiling = best possible given sampling noise" />
              </div>

              <div className="grid gap-6 lg:grid-cols-2">
                <ChartFrame
                  title="Prediction error by method"
                  subtitle="Possession-weighted RMSE with 95% CI. The noise floor is the error a perfect model would still make, because post-break ratings are measured over few possessions."
                  table={
                    <TableWrap label="RMSE by method">
                      <thead>
                        <tr>
                          <Th align="left">Method</Th>
                          <Th>RMSE</Th>
                          <Th>95% CI</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {methodRows.map((m) => (
                          <tr key={m.label}>
                            <Td align="left">{m.label}</Td>
                            <Td>{fmtNum(m.e.estimate, 2)}</Td>
                            <Td>{fmtInterval(m.e.lo, m.e.hi, 2, false)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </TableWrap>
                  }
                >
                  <DotWhisker
                    format={(v) => fmtNum(v, 1)}
                    series={[{ key: 'rmse', label: 'RMSE', color: 'var(--series-1)' }]}
                    rows={methodRows.map((m) => ({ label: m.label, values: { rmse: { v: m.e.estimate, lo: m.e.lo, hi: m.e.hi } } }))}
                  />
                </ChartFrame>

                <ChartFrame
                  title="Paired difference from each baseline"
                  subtitle="Model RMSE minus baseline RMSE, with 95% CI. Left of zero: the model is better. An interval crossing zero is a tie."
                  legend={[
                    { label: 'vs team prior', color: 'var(--series-1)' },
                    { label: 'vs league mean', color: 'var(--series-2)' },
                  ]}
                  table={
                    <TableWrap label="Paired differences">
                      <thead>
                        <tr>
                          <Th align="left">Evaluation</Th>
                          <Th>vs team prior</Th>
                          <Th>vs league mean</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {evals.map((e) => (
                          <tr key={e.evaluation}>
                            <Td align="left">{evalLabel(e.evaluation)}</Td>
                            <Td>{est(e.model_minus_team_prior, 2, true)}</Td>
                            <Td>{est(e.model_minus_league_mean, 2, true)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </TableWrap>
                  }
                >
                  <DotWhisker
                    zeroLine
                    format={(v) => fmtSigned(v, 1)}
                    series={[
                      { key: 'prior', label: 'vs team prior', color: 'var(--series-1)' },
                      { key: 'league', label: 'vs league mean', color: 'var(--series-2)' },
                    ]}
                    rows={evals.map((e) => ({
                      label: e.evaluation === 'pooled' ? 'Pooled' : /^\d/.test(e.evaluation) ? e.evaluation : 'Dev CV',
                      values: {
                        prior: { v: e.model_minus_team_prior.estimate, lo: e.model_minus_team_prior.lo, hi: e.model_minus_team_prior.hi },
                        league: e.model_minus_league_mean
                          ? { v: e.model_minus_league_mean.estimate, lo: e.model_minus_league_mean.lo, hi: e.model_minus_league_mean.hi }
                          : { v: null },
                      },
                    }))}
                  />
                </ChartFrame>
              </div>

              <ChartFrame
                title="Explained variance and calibration"
                subtitle="R² of the model against the ceiling that sampling noise allows, and the calibration slope (1 = well calibrated; above 1 = predictions too conservative)."
                legend={[
                  { label: 'Model R²', color: 'var(--series-1)' },
                  { label: 'R² ceiling', color: 'var(--series-2)' },
                ]}
                table={<MetricsTable evals={evals} />}
              >
                <div className="grid gap-6 md:grid-cols-2">
                  <div>
                  <h3 className="mb-2 text-sm font-medium text-ink">R²: model vs ceiling</h3>
                  <DotWhisker
                    format={(v) => fmtNum(v, 2)}
                    series={[
                      { key: 'model', label: 'Model R²', color: 'var(--series-1)' },
                      { key: 'ceiling', label: 'R² ceiling', color: 'var(--series-2)' },
                    ]}
                    rows={evals.map((e) => ({
                      label: e.evaluation === 'pooled' ? 'Pooled' : /^\d/.test(e.evaluation) ? e.evaluation : 'Dev CV',
                      values: {
                        model: { v: e.r2_model.estimate, lo: e.r2_model.lo, hi: e.r2_model.hi },
                        ceiling: { v: e.r2_ceiling.estimate, lo: e.r2_ceiling.lo, hi: e.r2_ceiling.hi },
                      },
                    }))}
                  />
                  </div>
                  <div>
                  <h3 className="mb-2 text-sm font-medium text-ink">Calibration slope (line at 1 = perfect)</h3>
                  <DotWhisker
                    format={(v) => fmtNum(v, 1)}
                    reference={{ value: 1, label: 'perfect calibration' }}
                    series={[{ key: 'slope', label: 'Calibration slope', color: 'var(--series-1)' }]}
                    rows={evals
                      .filter((e) => e.calibration_slope)
                      .map((e) => ({
                        label: e.evaluation === 'pooled' ? 'Pooled' : /^\d/.test(e.evaluation) ? e.evaluation : 'Dev CV',
                        values: { slope: { v: e.calibration_slope!.estimate, lo: e.calibration_slope!.lo, hi: e.calibration_slope!.hi } },
                      }))}
                  />
                  </div>
                </div>
              </ChartFrame>

              <Card>
                <CardHeader title="All metrics" subtitle={`Weighting: ${p.weighting}`} />
                <CardBody>
                  <MetricsTable evals={evals} />
                </CardBody>
              </Card>
            </div>
          )
        })()
      )}

      <div className="mt-6 space-y-6">
        <Callout title="Why a tie with the team prior is the honest result">
          Post-break lineup ratings are measured over a few dozen to a few hundred possessions, so most of their variation is sampling noise (compare each RMSE with the noise
          floor). Once a team’s overall strength is known, there is little lineup-specific signal left to predict. The model is still useful for ranking lineups within a team and for
          giving a noise-aware expectation, but not for claims that a lineup “is” +X.
        </Callout>
        <EstimandNotice compact />
        {card.error ? (
          <ErrorState error={card.error} onRetry={() => card.refetch()} />
        ) : !card.data ? (
          <LoadingBlock height="h-96" label="Loading model card" />
        ) : (
          <>
            <CardDetails card={card.data} />
            <UseLists card={card.data} />
          </>
        )}
      </div>
    </div>
  )
}
