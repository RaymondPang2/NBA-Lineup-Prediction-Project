import { Link } from 'react-router'
import { Callout } from '../ui/Card'

/** The analytical contract's estimand, shown next to every prediction. */
export const ESTIMAND_TEXT =
  'A prediction is conditional: it is the expected post-All-Star-break net rating of this lineup if its coach plays it after the break. It does not predict whether, or how much, the lineup will be used. Inputs are pre-break data only.'

export function EstimandNotice({ compact = false }: { compact?: boolean }) {
  return (
    <Callout title="Conditional prediction" >
      <p data-testid="estimand-notice">
        {ESTIMAND_TEXT}
        {!compact && (
          <>
            {' '}
            The frozen model is <strong className="font-semibold text-ink">not statistically better than the team-prior baseline</strong> shown beside it (
            <Link to="/model" className="text-accent underline-offset-2 hover:underline">
              model performance
            </Link>
            ).
          </>
        )}
      </p>
    </Callout>
  )
}
