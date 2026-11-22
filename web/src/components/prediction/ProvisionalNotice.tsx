import { Link } from 'react-router'
import type { SeasonProgress } from '../../api/types'
import { fmtDate } from '../../lib/format'
import { Callout } from '../ui/Card'

/**
 * Shown with every prediction for the season in progress (Prediction Lab and Rankings). The numbers come from the
 * API; the accuracy statement summarizes docs/partial_window_audit.md (frozen model, partial pre-break window).
 */
export function ProvisionalNotice({ seasonId, cutoff, progress, ranking = false }: { seasonId: string; cutoff?: string | null; progress?: SeasonProgress | null; ranking?: boolean }) {
  return (
    <Callout tone="warn" title={`PROVISIONAL · ${seasonId} in progress`}>
      <span data-testid="provisional-notice" className="block space-y-1.5">
        <span className="block">
          Inputs are {seasonId}’s pre-All-Star-break games through <strong className="font-semibold text-ink">{cutoff ? fmtDate(cutoff) : 'the data cutoff'}</strong>
          {progress && progress.fraction != null && progress.typical_full_window != null ? (
            <>
              {' '}
              — about {Math.round(progress.team_games_mean)} of a typical {Math.round(progress.typical_full_window)} pre-break games per team (
              {Math.round(progress.fraction * 100)}%)
            </>
          ) : progress ? (
            <> — about {Math.round(progress.team_games_mean)} pre-break games per team so far</>
          ) : null}
          . Nothing after the cutoff is used, and no future or post-break statistics are estimated.
        </span>
        <span className="block">
          <strong className="font-semibold text-ink">Incomplete pre-break information reduces accuracy.</strong> The frozen model was developed on completed pre-break
          windows. On a partial window it reads players’ smaller possession counts partly as a weaker role, so {ranking ? 'these predictions' : 'this prediction'} run about 2
          points low on average{ranking ? ' (the rank order is largely unaffected)' : ''}, and the 95% intervals are likely too narrow. In a held-out backtest at this
          volume the model no longer beat the team-prior baseline, so treat the baseline as at least as good (
          <Link to="/model" className="text-accent underline-offset-2 hover:underline">
            model performance
          </Link>
          ). The target is unchanged: the expected post-All-Star-break net rating if the lineup plays after the break.
        </span>
      </span>
    </Callout>
  )
}
