import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useDataStatus, useModelPerformance, useSeasons } from '../../api/hooks'
import { fmtDate, fmtNum } from '../../lib/format'

function Action({ to, title, text, icon, testId }: { to: string; title: string; text: string; icon: ReactNode; testId: string }) {
  return (
    <Link
      to={to}
      data-testid={testId}
      className="group flex min-w-0 items-start gap-3 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-accent/50 hover:bg-accent-soft"
    >
      <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent group-hover:bg-surface">{icon}</span>
      <span className="min-w-0">
        <span className="flex items-center gap-1 font-semibold text-ink">
          {title}
          <span aria-hidden className="text-accent transition-transform group-hover:translate-x-0.5">
            →
          </span>
        </span>
        <span className="mt-0.5 block text-sm text-ink-2">{text}</span>
      </span>
    </Link>
  )
}

const icon = (d: string) => (
  <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={d} />
  </svg>
)

/** Landing introduction: what Lineup Lab is, why it matters, what is inside, and where to go next. Facts come from the API. */
export function Hero() {
  const seasons = useSeasons()
  const status = useDataStatus()
  const perf = useModelPerformance()
  const list = seasons.data ?? []
  const completed = list.filter((s) => s.role !== 'current')
  const current = list.find((s) => s.role === 'current')
  const lineups = list.reduce((a, s) => a + s.n_lineups, 0)
  const pooled = perf.data?.held_out.find((e) => e.evaluation === 'pooled')

  const facts: { value: string; label: string }[] = []
  if (completed.length)
    facts.push({ value: `${completed.length} seasons`, label: `${completed[0].season_id} to ${completed[completed.length - 1].season_id}${current ? `, plus ${current.season_id} to date` : ''}` })
  if (lineups) facts.push({ value: lineups.toLocaleString('en-US'), label: 'five-man lineups with pre- and post-All-Star-break stats' })
  if (pooled) facts.push({ value: `${pooled.n_lineups.toLocaleString('en-US')} lineups`, label: `held-out test of a frozen ML model (RMSE ${fmtNum(pooled.rmse_model.estimate, 2)})` })
  if (status.data?.data_cutoff) facts.push({ value: fmtDate(status.data.data_cutoff), label: `latest ${status.data.season_id} game included (${status.data.freshness === "current" ? "up to date" : "update pending"})` })

  return (
    <section aria-labelledby="hero-title" className="mb-8 rounded-2xl border border-line bg-surface p-5 sm:p-8" data-testid="hero">
      <p className="text-xs font-semibold tracking-wide text-accent uppercase">NBA five-man lineup analytics</p>
      <h1 id="hero-title" className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
        Which NBA lineups actually work, and what to expect from them next?
      </h1>
      <div className="mt-4 max-w-3xl space-y-3 text-[15px] leading-relaxed text-ink-2">
        <p>
          Coaches choose which five players share the floor, and those combinations win or lose games together. Lineup Lab measures every five-man lineup in the NBA on points scored
          and allowed per 100 possessions, before and after the All-Star break, and shows how much of each number is real signal versus small-sample luck.
        </p>
        <p>
          A machine-learning model built with <strong className="font-semibold text-ink">linear regression</strong> predicts how a lineup would perform after the All-Star break from what it did before. Every prediction is shown next to a
          simple team baseline and an honest uncertainty range.
        </p>
      </div>

      {facts.length > 0 && (
        <dl className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="hero-facts">
          {facts.map((f) => (
            <div key={f.label} className="flex min-w-0 flex-col-reverse rounded-lg bg-surface-2 px-4 py-3">
              <dt className="text-xs text-ink-2">{f.label}</dt>
              <dd className="text-lg font-semibold text-ink tabular">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-6 grid gap-3 md:grid-cols-3">
        <Action testId="cta-lineups" to="/lineups" title="Explore NBA lineups" text="Search any team or player and compare ratings before and after the break." icon={icon('M4 6h16M4 12h16M4 18h10')} />
        <Action testId="cta-rankings" to="/rankings" title="View best lineups" text="League-wide rankings by net, offense, defense or playing time, with sample sizes." icon={icon('M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4ZM7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3')} />
        <Action testId="cta-predict" to="/predict" title="Try ML predictions" text="Pick five players and see the model’s prediction, baseline and uncertainty." icon={icon('M12 3v3M12 18v3M3 12h3M18 12h3M6 6l2 2M16 16l2 2M6 18l2-2M16 8l2-2M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z')} />
      </div>
    </section>
  )
}
