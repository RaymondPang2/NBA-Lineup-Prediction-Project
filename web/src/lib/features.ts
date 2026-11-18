/** Short display names for the model's features. The API's own `description` is shown alongside. */
export const FEATURE_LABELS: Record<string, string> = {
  team_off_rating_loo: 'Team ORtg (other lineups)',
  team_def_rating_loo: 'Team DRtg (other lineups)',
  p_off_rating_eb_mean: 'Players’ on-court ORtg',
  p_def_rating_eb_mean: 'Players’ on-court DRtg',
  p_net_rating_eb_mean: 'Players’ on-court net',
  p_on_off_eb_mean: 'Players’ on-off net',
  p_usage_eb_mean: 'Average usage',
  p_usage_eb_max: 'Highest usage',
  p_log_poss_mean: 'Players’ pre-break volume',
  p_team_share_min: 'Least-used player’s share',
  p_n_new_to_team: 'Players new to team',
  p_n_no_history: 'Players with no history',
  lu_log_poss: 'Lineup’s own possessions (log)',
  lu_no_history: 'Lineup has no history',
  lu_net_eb_team: 'Lineup’s shrunk net',
  lu_pair_familiarity: 'Pair familiarity',
}

export function featureLabel(feature: string): string {
  return FEATURE_LABELS[feature] ?? feature
}
