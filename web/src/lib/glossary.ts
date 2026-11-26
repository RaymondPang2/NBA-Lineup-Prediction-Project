/** Plain-English definitions shown by <InfoTip>. Short on purpose: one or two sentences each. */
export const GLOSSARY = {
  ortg: {
    term: 'Offensive rating (ORtg)',
    text: 'Points a lineup scores per 100 of its possessions. Higher is better.',
  },
  drtg: {
    term: 'Defensive rating (DRtg)',
    text: 'Points a lineup allows per 100 opponent possessions. Lower is better.',
  },
  net: {
    term: 'Net rating',
    text: 'Offensive rating minus defensive rating: how many points a lineup outscores opponents by per 100 possessions. +5 is very good; 0 is even.',
  },
  poss: {
    term: 'Possessions',
    text: 'One trip down the floor that ends in a shot, turnover or free throws. Ratings are per 100 possessions so lineups with different playing time can be compared.',
  },
  rmse: {
    term: 'RMSE (root-mean-square error)',
    text: 'The typical size of a prediction miss, in net-rating points. Lower is better. Weighted by possessions, so lineups that played more count more.',
  },
  r2: {
    term: 'R²',
    text: 'The share of the variation in actual results that predictions explain (0 = none, 1 = all). Here even a perfect model is capped low, because short samples are mostly noise.',
  },
  heldout: {
    term: 'Held-out seasons',
    text: '2024-25 and 2025-26 were locked away until the model was finished, then used once to test it, like an exam the model never studied for.',
  },
  baseline: {
    term: 'Baseline models',
    text: 'Simple benchmarks a model must beat. League average: predict the same rating for every lineup. Team prior: predict the team’s own pre-break rating from its other lineups.',
  },
  interval: {
    term: '95% interval',
    text: 'The range that should contain the true value 95% of the time. The true-quality interval covers the lineup’s real strength; the observed interval also includes the luck of a short sample.',
  },
  noise: {
    term: 'Sampling noise',
    text: 'Random variation from measuring over few possessions. A net rating measured over 20 possessions has a chance-alone standard deviation of about 38 points; over 500 possessions, about 8.',
  },
  features: {
    term: 'Feature engineering',
    text: 'Turning raw pre-break totals into model inputs: team strength without this lineup, players’ shrunk on-court ratings and usage, and how much the lineup has played together.',
  },
  provisional: {
    term: 'Provisional prediction',
    text: '2026-27 is still in progress. Its predictions use only the games played so far, before the model has the full pre-break sample it was built on, so they are not independently validated.',
  },
  reliability: {
    term: 'Reliability',
    text: 'The share of a lineup’s rating (relative to its team) that is real signal rather than sampling noise. Low reliability means the number is mostly luck.',
  },
} as const

export type GlossaryKey = keyof typeof GLOSSARY
