"""The Power BI semantic model, as data: tables, typed columns, relationships and DAX measures.

Star schema (see sql/powerbi/bi_views.sql for grains):

    dim_player 1 ──* bridge_lineup_player *──1 dim_lineup 1 ──* fact_lineup_window *──1 dim_season
                    (filter flows player → bridge → lineup:                         *──1 dim_team
                     bridge→lineup is bidirectional)                                *──1 dim_window
                                              dim_lineup 1 ──* fact_prediction   *──1 dim_season, dim_team
                                                      fact_team_window *──1 dim_season, dim_team, dim_window

dim_lineup deliberately has NO relationship to dim_season / dim_team (the facts carry those keys), so there is
exactly one filter path from every dimension to every fact: no ambiguity, no double counting. A player filter
selects a SET of lineups; each lineup's facts are then summed once, however many selected players it contains.

Every rating measure divides SUMS (aggregate first, then divide), never averages ratings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------------- tables


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str                      # int64 | double | string | dateTime
    description: str = ""
    hidden: bool = False
    sort_by: str | None = None
    format: str | None = None
    nullable: bool = False          # documented: may be blank


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    columns: tuple[Column, ...]
    source: str = "sql"             # sql: a bi.* view | python: produced by export.py | measures: host table
    hidden: bool = False

    def column(self, name: str) -> Column:
        return next(c for c in self.columns if c.name == name)


@dataclass(frozen=True)
class Relationship:
    from_table: str                 # many side
    from_column: str
    to_table: str                   # one side
    to_column: str
    both_directions: bool = False


@dataclass(frozen=True)
class Measure:
    name: str
    expression: str
    folder: str
    description: str
    format: str = "0.0"


C = Column
I, D, S, T = "int64", "double", "string", "dateTime"

TABLES: tuple[Table, ...] = (
    Table("dim_season", "One row per season (2018-19 to 2025-26). Held-out seasons were never used to train or tune the model.", (
        C("season_id", S, "Season, e.g. 2025-26", sort_by="season_order"),
        C("start_year", I, "Calendar year the season starts"),
        C("is_irregular", I, "1 = 2019-20 (bubble) or 2020-21 (72 games)"),
        C("season_role", S, "Development (training/CV) or Held-out (final test only)"),
        C("pre_break_from", T, "First day of the pre-All-Star-break window"),
        C("pre_break_to", T, "Last day of the pre-break window"),
        C("post_break_from", T, "First day of the post-break window"),
        C("post_break_to", T, "Last day of the post-break window"),
        C("season_order", I, "Sort key", hidden=True),
    )),
    Table("dim_team", "One row per NBA team.", (
        C("team_id", I, "NBA team id", hidden=True),
        C("abbreviation", S, "Three-letter code"),
        C("team_name", S, "Full team name"),
    )),
    Table("dim_player", "Players who appear in at least one lineup.", (
        C("player_id", I, "NBA player id", hidden=True),
        C("player_name", S, "Player name"),
    )),
    Table("dim_window", "The two date windows of each season, split at the All-Star break.", (
        C("window_type", S, "pre_asb or post_asb", hidden=True),
        C("window_label", S, "Pre-break / Post-break", sort_by="window_order"),
        C("window_order", I, "Sort key", hidden=True),
    )),
    Table("dim_lineup", "One row per five-man lineup (a season, a team and five players). Filtered by players through the bridge.", (
        C("lineup_id", I, "Lineup key"),
        C("season_id", S, "Season (attribute only: slice seasons with dim_season)", hidden=True),
        C("team_id", I, "Team (attribute only: slice teams with dim_team)", hidden=True),
        C("player_key", S, "The five player ids, numeric order", hidden=True),
        C("lineup_label", S, "Five last names"),
        C("lineup_players", S, "Five full names"),
        C("pre_poss", I, "Pre-break possessions (own)", format="#,0"),
        C("pre_opp_poss", I, "Pre-break opponent possessions", format="#,0"),
        C("post_poss", I, "Post-break possessions (own)", format="#,0"),
        C("post_opp_poss", I, "Post-break opponent possessions", format="#,0"),
        C("season_minutes", D, "Minutes played together, whole season", format="#,0.0"),
        C("pre_sample_tier", S, "Pre-break sample size (smaller end): 0, 1-24, 25-99, 100-299, 300+", sort_by="pre_sample_tier_order"),
        C("pre_sample_tier_order", I, "Sort key", hidden=True),
        C("in_continuation_population", I, "1 = at least 25 pre-break possessions on each end (selection analysis population)"),
        C("appears_post_break", I, "1 = any post-break possession"),
        C("continues_post_break", I, "1 = at least 25 post-break possessions (Phase 4 'continues')"),
        C("pre_poss_bin", S, "Pre-break possession bin of the selection analysis", sort_by="pre_poss_bin_order", nullable=True),
        C("pre_poss_bin_order", I, "Sort key", hidden=True, nullable=True),
        C("in_target_sample", I, "1 = at least 25 post-break possessions on each end (the model's target sample)"),
    )),
    Table("bridge_lineup_player", "Lineup ↔ player (five rows per lineup). Resolves the many-to-many relationship.", (
        C("lineup_id", I, hidden=True),
        C("player_id", I, hidden=True),
    ), hidden=False),
    Table("fact_lineup_window", "Additive totals per lineup and window. Ratings are measures, never stored.", (
        C("lineup_id", I, hidden=True),
        C("season_id", S, hidden=True),
        C("team_id", I, hidden=True),
        C("window_type", S, hidden=True),
        C("gp", I, "Games in which the lineup played", hidden=True),
        C("minutes", D, hidden=True),
        C("poss", I, "Own (offensive) possessions", hidden=True),
        C("opp_poss", I, "Opponent possessions (0 where unknown)", hidden=True),
        C("pts", I, "Points scored", hidden=True),
        C("opp_pts", I, "Points allowed", hidden=True),
        C("opp_pts_rated", I, "Points allowed where opponent possessions are known (DRtg numerator)", hidden=True),
        C("plus_minus", I, hidden=True),
    )),
    Table("fact_team_window", "Team games, wins and losses per season and window (from game logs).", (
        C("season_id", S, hidden=True),
        C("team_id", I, hidden=True),
        C("window_type", S, hidden=True),
        C("games", I, hidden=True),
        C("wins", I, hidden=True),
        C("losses", I, hidden=True),
    )),
    Table("fact_prediction", "Frozen-model predictions for every lineup that played after the break, scored from PRE-break data only; the observed post-break rating is the outcome, never an input.", (
        C("lineup_id", I, hidden=True),
        C("season_id", S, hidden=True),
        C("team_id", I, hidden=True),
        C("predicted_net", D, "Frozen linear model: expected post-break net rating, given the lineup plays", format="+0.0;-0.0;0.0"),
        C("team_prior_net", D, "Team-prior baseline (team's other lineups + constant)", format="+0.0;-0.0;0.0"),
        C("league_mean_net", D, "League-mean baseline (constant)", format="+0.0;-0.0;0.0"),
        C("eb_lineup_net", D, "Lineup history shrunk toward the team prior", format="+0.0;-0.0;0.0"),
        C("model_minus_team_prior", D, format="+0.00;-0.00;0.00"),
        C("pre_reliability", D, "Share of the lineup's pre-break net rating that is signal (0 without history)", format="0%"),
        C("pre_no_history", I, "1 = no pre-break possessions together"),
        C("observed_post_net", D, "Realized post-break net rating (outcome)", format="+0.0;-0.0;0.0", nullable=True),
        C("post_poss", I, "Post-break possessions (evaluation weight)", hidden=True),
        C("post_opp_poss", I, hidden=True),
        C("noise_var", D, "Sampling variance of the observed rating: K·(1/post_poss + 1/post_opp_poss)", hidden=True, nullable=True),
        C("in_evaluation_sample", I, "1 = at least 25 post-break possessions on each end"),
        C("is_training_season", I, "1 = season used to train the model (in-sample fitted value)"),
        C("evaluation_set", S, "Held-out test or In-sample (training season)"),
        C("predicted_decile", I, "Decile of the prediction within its season's evaluation sample (calibration)", nullable=True),
    ), source="python"),
    Table("model_parameters", "Constants of the frozen model (one row).", (
        C("k_noise", D, "Sampling-noise constant K: Var(net) = K·(1/poss + 1/opp_poss)", hidden=True),
        C("lineup_tau2", D, "Variance of true lineup quality around the team prior (reliability)", hidden=True),
        C("lineup_mu", D, hidden=True),
        C("model_sd", D, "Model error about true quality (held-out estimate)", hidden=True),
        C("z95", D, hidden=True),
        C("min_target_poss", I, hidden=True),
        C("artifact_sha256", S, "SHA-256 of the frozen model file"),
        C("frozen_at_utc", S),
        C("exported_at_utc", S),
    ), source="python"),
    Table("_Measures", "Home of every measure (no data).", (
        C("_", S, hidden=True),
    ), source="measures"),
)

RELATIONSHIPS: tuple[Relationship, ...] = (
    Relationship("fact_lineup_window", "lineup_id", "dim_lineup", "lineup_id"),
    Relationship("fact_lineup_window", "season_id", "dim_season", "season_id"),
    Relationship("fact_lineup_window", "team_id", "dim_team", "team_id"),
    Relationship("fact_lineup_window", "window_type", "dim_window", "window_type"),
    Relationship("fact_team_window", "season_id", "dim_season", "season_id"),
    Relationship("fact_team_window", "team_id", "dim_team", "team_id"),
    Relationship("fact_team_window", "window_type", "dim_window", "window_type"),
    Relationship("fact_prediction", "lineup_id", "dim_lineup", "lineup_id"),
    Relationship("fact_prediction", "season_id", "dim_season", "season_id"),
    Relationship("fact_prediction", "team_id", "dim_team", "team_id"),
    Relationship("bridge_lineup_player", "player_id", "dim_player", "player_id"),
    Relationship("bridge_lineup_player", "lineup_id", "dim_lineup", "lineup_id", both_directions=True),
)

# ---------------------------------------------------------------------------------------------- measures
# Conventions: 'fact_lineup_window' totals; window measures pin dim_window; model measures use the
# evaluation sample (>= 25 post-break possessions per end) weighted by post-break possessions, exactly as
# Phase 6 (src/nba_lineups/modeling/evaluation.py).

FLW = "fact_lineup_window"
FP = "fact_prediction"
SIGNED = "+0.0;-0.0;0.0"
SIGNED2 = "+0.00;-0.00;0.00"


def _window(measure: str, window: str) -> str:
    return f"CALCULATE ( [{measure}], dim_window[window_type] = \"{window}\" )"


def _eval_table() -> str:
    return f"FILTER ( {FP}, {FP}[in_evaluation_sample] = 1 && NOT ISBLANK ( {FP}[observed_post_net] ) )"


def _wmse(pred_col: str) -> str:
    return (f"VAR t = {_eval_table()}\n"
            f"RETURN DIVIDE ( SUMX ( t, {FP}[post_poss] * ( {FP}[observed_post_net] - {FP}[{pred_col}] ) ^ 2 ), "
            f"SUMX ( t, {FP}[post_poss] ) )")


def _wmae(pred_col: str) -> str:
    return (f"VAR t = {_eval_table()}\n"
            f"RETURN DIVIDE ( SUMX ( t, {FP}[post_poss] * ABS ( {FP}[observed_post_net] - {FP}[{pred_col}] ) ), "
            f"SUMX ( t, {FP}[post_poss] ) )")


M = Measure
MEASURES: tuple[Measure, ...] = (
    # ---- Volume
    M("Possessions", f"SUM ( {FLW}[poss] )", "1 Volume", "Own (offensive) possessions.", "#,0"),
    M("Opp Possessions", f"SUM ( {FLW}[opp_poss] )", "1 Volume", "Opponent possessions (separate denominator for DRtg).", "#,0"),
    M("Points", f"SUM ( {FLW}[pts] )", "1 Volume", "Points scored.", "#,0"),
    M("Opp Points", f"SUM ( {FLW}[opp_pts] )", "1 Volume", "Points allowed.", "#,0"),
    M("Minutes", f"SUM ( {FLW}[minutes] )", "1 Volume", "Minutes played by the lineup(s).", "#,0.0"),
    M("Lineups", f"DISTINCTCOUNT ( {FLW}[lineup_id] )", "1 Volume", "Distinct lineups with any minutes in the filter context.", "#,0"),
    M("Possessions Pre", _window("Possessions", "pre_asb"), "1 Volume", "Possessions before the break.", "#,0"),
    M("Possessions Post", _window("Possessions", "post_asb"), "1 Volume", "Possessions after the break.", "#,0"),
    # ---- Ratings (aggregate first, then divide)
    M("ORtg", f"DIVIDE ( SUM ( {FLW}[pts] ), SUM ( {FLW}[poss] ) ) * 100", "2 Ratings",
      "Offensive rating: 100 × Σ points ÷ Σ own possessions."),
    M("DRtg", f"DIVIDE ( SUM ( {FLW}[opp_pts_rated] ), SUM ( {FLW}[opp_poss] ) ) * 100", "2 Ratings",
      "Defensive rating: 100 × Σ opponent points ÷ Σ opponent possessions (lower is better)."),
    M("Net Rating", "VAR o = [ORtg]\nVAR d = [DRtg]\nRETURN IF ( NOT ISBLANK ( o ) && NOT ISBLANK ( d ), o - d )", "2 Ratings",
      "ORtg − DRtg. Blank unless both are defined.", SIGNED),
    M("Lineup Net Avg (possession-weighted)",
      "VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_lineup[lineup_id] ), \"@n\", [Net Rating], \"@w\", [Possessions] ), NOT ISBLANK ( [@n] ) )\n"
      "RETURN DIVIDE ( SUMX ( t, [@w] * [@n] ), SUMX ( t, [@w] ) )", "2 Ratings",
      "Possession-weighted average of the lineups' own net ratings. Close to, but not identical with, the pooled Net Rating.", SIGNED),
    M("Lineup Net Avg (unweighted, misleading)",
      "AVERAGEX ( FILTER ( ADDCOLUMNS ( VALUES ( dim_lineup[lineup_id] ), \"@n\", [Net Rating] ), NOT ISBLANK ( [@n] ) ), [@n] )",
      "2 Ratings", "Simple mean of lineup net ratings. Shown only to demonstrate why ratings must not be averaged: tiny samples dominate.", SIGNED),
    # ---- Pre vs post
    M("ORtg Pre", _window("ORtg", "pre_asb"), "3 Pre vs Post", "Offensive rating before the break."),
    M("ORtg Post", _window("ORtg", "post_asb"), "3 Pre vs Post", "Offensive rating after the break."),
    M("DRtg Pre", _window("DRtg", "pre_asb"), "3 Pre vs Post", "Defensive rating before the break."),
    M("DRtg Post", _window("DRtg", "post_asb"), "3 Pre vs Post", "Defensive rating after the break."),
    M("Net Rating Pre", _window("Net Rating", "pre_asb"), "3 Pre vs Post", "Net rating before the break.", SIGNED),
    M("Net Rating Post", _window("Net Rating", "post_asb"), "3 Pre vs Post", "Net rating after the break.", SIGNED),
    M("Net Change", "VAR a = [Net Rating Pre]\nVAR b = [Net Rating Post]\nRETURN IF ( NOT ISBLANK ( a ) && NOT ISBLANK ( b ), b - a )",
      "3 Pre vs Post", "Post-break minus pre-break net rating.", SIGNED),
    M("ORtg Change", "VAR a = [ORtg Pre]\nVAR b = [ORtg Post]\nRETURN IF ( NOT ISBLANK ( a ) && NOT ISBLANK ( b ), b - a )",
      "3 Pre vs Post", "Post minus pre offensive rating.", SIGNED),
    M("DRtg Change", "VAR a = [DRtg Pre]\nVAR b = [DRtg Post]\nRETURN IF ( NOT ISBLANK ( a ) && NOT ISBLANK ( b ), b - a )",
      "3 Pre vs Post", "Post minus pre defensive rating (negative = better defense).", SIGNED),
    # ---- Uncertainty and reliability
    M("K (noise constant)", "MAX ( model_parameters[k_noise] )", "4 Reliability", "Sampling-noise constant of the frozen model (≈ 14,639).", "#,0"),
    M("Net Rating SE",
      "VAR p = [Possessions]\nVAR q = [Opp Possessions]\nRETURN IF ( p > 0 && q > 0, SQRT ( [K (noise constant)] * ( 1 / p + 1 / q ) ) )",
      "4 Reliability", "Sampling standard error of the net rating: √(K·(1/poss + 1/opp_poss))."),
    M("Net Rating 95% Low", "VAR n = [Net Rating]\nVAR se = [Net Rating SE]\nRETURN IF ( NOT ISBLANK ( n ) && NOT ISBLANK ( se ), n - 1.959964 * se )",
      "4 Reliability", "Lower end of the 95% sampling interval.", SIGNED),
    M("Net Rating 95% High", "VAR n = [Net Rating]\nVAR se = [Net Rating SE]\nRETURN IF ( NOT ISBLANK ( n ) && NOT ISBLANK ( se ), n + 1.959964 * se )",
      "4 Reliability", "Upper end of the 95% sampling interval.", SIGNED),
    M("Net Change SE",
      "VAR a = CALCULATE ( [Net Rating SE], dim_window[window_type] = \"pre_asb\" )\n"
      "VAR b = CALCULATE ( [Net Rating SE], dim_window[window_type] = \"post_asb\" )\n"
      "RETURN IF ( NOT ISBLANK ( a ) && NOT ISBLANK ( b ), SQRT ( a ^ 2 + b ^ 2 ) )",
      "4 Reliability", "Standard error of the pre→post change (independent windows)."),
    M("Change Exceeds Noise",
      "VAR c = [Net Change]\nVAR se = [Net Change SE]\nRETURN IF ( NOT ISBLANK ( c ) && NOT ISBLANK ( se ), IF ( ABS ( c ) > 1.959964 * se, 1, 0 ) )",
      "4 Reliability", "1 if |change| > 1.96 SE (larger than sampling noise alone).", "0"),
    M("Reliability",
      "VAR p = [Possessions]\nVAR q = [Opp Possessions]\nVAR tau2 = MAX ( model_parameters[lineup_tau2] )\n"
      "RETURN IF ( p > 0 && q > 0, DIVIDE ( tau2, tau2 + [K (noise constant)] * ( 1 / p + 1 / q ) ) )",
      "4 Reliability", "Share of the net rating's variance that is signal (vs the team prior): τ² / (τ² + K·h). "
      "With the pre-break window in context it equals the model's per-lineup reliability.", "0%"),
    M("Lineups ≥ 100 Poss",
      "COUNTROWS ( FILTER ( VALUES ( dim_lineup[lineup_id] ), [Possessions] >= 100 && [Opp Possessions] >= 100 ) )",
      "4 Reliability", "Lineups with at least 100 possessions on each end in context.", "#,0"),
    M("Share of Possessions in Lineups ≥ 100",
      "DIVIDE ( SUMX ( FILTER ( VALUES ( dim_lineup[lineup_id] ), [Possessions] >= 100 && [Opp Possessions] >= 100 ), [Possessions] ), [Possessions] )",
      "4 Reliability", "How much of the playing time comes from lineups with a usable sample.", "0%"),
    M("Lineup Net SD (possession-weighted)",
      "VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_lineup[lineup_id] ), \"@n\", [Net Rating], \"@w\", [Possessions] ), NOT ISBLANK ( [@n] ) )\n"
      "VAR m = DIVIDE ( SUMX ( t, [@w] * [@n] ), SUMX ( t, [@w] ) )\n"
      "RETURN SQRT ( DIVIDE ( SUMX ( t, [@w] * ( [@n] - m ) ^ 2 ), SUMX ( t, [@w] ) ) )",
      "4 Reliability", "Spread of lineup net ratings. Compare with Noise SD: most of the spread at small samples is noise."),
    M("Noise SD (possession-weighted)",
      "VAR t = FILTER ( ADDCOLUMNS ( VALUES ( dim_lineup[lineup_id] ), \"@se\", [Net Rating SE], \"@w\", [Possessions] ), NOT ISBLANK ( [@se] ) )\n"
      "RETURN SQRT ( DIVIDE ( SUMX ( t, [@w] * [@se] ^ 2 ), SUMX ( t, [@w] ) ) )",
      "4 Reliability", "Spread that pure sampling noise would produce for the same lineups."),
    # ---- Team
    M("Games", "SUM ( fact_team_window[games] )", "5 Team", "Team games.", "#,0"),
    M("Wins", "SUM ( fact_team_window[wins] )", "5 Team", "Team wins.", "#,0"),
    M("Losses", "SUM ( fact_team_window[losses] )", "5 Team", "Team losses.", "#,0"),
    M("Win %", "DIVIDE ( [Wins], [Games] )", "5 Team", "Wins ÷ games.", "0.0%"),
    M("Record", "IF ( NOT ISBLANK ( [Games] ), FORMAT ( [Wins], \"0\" ) & \"–\" & FORMAT ( [Losses], \"0\" ) )", "5 Team", "W–L as text.", "General"),
    # ---- Model performance (evaluation sample, possession-weighted)
    M("Eval Lineups", f"COUNTROWS ( {_eval_table()} )", "6 Model", "Lineups in the evaluation sample (≥ 25 post-break possessions per end).", "#,0"),
    M("Eval Weight", f"SUMX ( {_eval_table()}, {FP}[post_poss] )", "6 Model", "Total post-break possessions of the evaluation sample (the weight).", "#,0"),
    M("Model RMSE", f"SQRT ( {_wmse('predicted_net')} )", "6 Model", "Possession-weighted RMSE of the frozen model.", "0.00"),
    M("Team Prior RMSE", f"SQRT ( {_wmse('team_prior_net')} )", "6 Model", "Possession-weighted RMSE of the team-prior baseline.", "0.00"),
    M("League Mean RMSE", f"SQRT ( {_wmse('league_mean_net')} )", "6 Model", "Possession-weighted RMSE of the league-mean baseline.", "0.00"),
    M("Model MAE", _wmae("predicted_net"), "6 Model", "Possession-weighted mean absolute error of the model.", "0.00"),
    M("Team Prior MAE", _wmae("team_prior_net"), "6 Model", "Possession-weighted MAE of the team prior.", "0.00"),
    M("League Mean MAE", _wmae("league_mean_net"), "6 Model", "Possession-weighted MAE of the league mean.", "0.00"),
    M("Model − Team Prior RMSE", "[Model RMSE] - [Team Prior RMSE]", "6 Model",
      "Negative = the model is more accurate than the team prior. Its 95% CI on the held-out seasons includes zero.", SIGNED2),
    M("Model − League Mean RMSE", "[Model RMSE] - [League Mean RMSE]", "6 Model", "Negative = the model beats the league mean.", SIGNED2),
    M("Skill vs Team Prior",
      f"VAR t = {_eval_table()}\nVAR w = SUMX ( t, {FP}[post_poss] )\n"
      f"VAR mseModel = DIVIDE ( SUMX ( t, {FP}[post_poss] * ( {FP}[observed_post_net] - {FP}[predicted_net] ) ^ 2 ), w )\n"
      f"VAR msePrior = DIVIDE ( SUMX ( t, {FP}[post_poss] * ( {FP}[observed_post_net] - {FP}[team_prior_net] ) ^ 2 ), w )\n"
      "RETURN IF ( msePrior > 0, 1 - DIVIDE ( mseModel, msePrior ) )",
      "6 Model", "1 − MSE(model) ÷ MSE(team prior): share of the baseline's squared error removed.", "0.0%"),
    M("Observed Variance",
      f"VAR t = {_eval_table()}\nVAR w = SUMX ( t, {FP}[post_poss] )\n"
      f"VAR m = DIVIDE ( SUMX ( t, {FP}[post_poss] * {FP}[observed_post_net] ), w )\n"
      f"RETURN DIVIDE ( SUMX ( t, {FP}[post_poss] * ( {FP}[observed_post_net] - m ) ^ 2 ), w )",
      "6 Model", "Possession-weighted variance of the observed post-break net rating (R² denominator).", "0.0"),
    M("Model R²", "VAR v = [Observed Variance]\nRETURN IF ( v > 0, 1 - DIVIDE ( [Model RMSE] ^ 2, v ) )", "6 Model",
      "1 − MSE ÷ Var(y), possession-weighted, around the evaluated rows' own mean.", "0.000"),
    M("Noise Floor RMSE",
      f"VAR t = {_eval_table()}\nRETURN SQRT ( DIVIDE ( SUMX ( t, {FP}[post_poss] * {FP}[noise_var] ), SUMX ( t, {FP}[post_poss] ) ) )",
      "6 Model", "RMSE a perfect model would still make: post-break ratings are measured over few possessions.", "0.00"),
    M("R² Ceiling", "VAR v = [Observed Variance]\nRETURN IF ( v > 0, 1 - DIVIDE ( [Noise Floor RMSE] ^ 2, v ) )", "6 Model",
      "Best R² achievable given sampling noise.", "0.000"),
    M("Mean Predicted",
      f"VAR t = {_eval_table()}\nRETURN DIVIDE ( SUMX ( t, {FP}[post_poss] * {FP}[predicted_net] ), SUMX ( t, {FP}[post_poss] ) )",
      "6 Model", "Possession-weighted mean prediction (evaluation sample).", SIGNED),
    M("Mean Team Prior",
      f"VAR t = {_eval_table()}\nRETURN DIVIDE ( SUMX ( t, {FP}[post_poss] * {FP}[team_prior_net] ), SUMX ( t, {FP}[post_poss] ) )",
      "6 Model", "Possession-weighted mean team-prior baseline (evaluation sample).", SIGNED),
    M("Mean Observed",
      f"VAR t = {_eval_table()}\nRETURN DIVIDE ( SUMX ( t, {FP}[post_poss] * {FP}[observed_post_net] ), SUMX ( t, {FP}[post_poss] ) )",
      "6 Model", "Possession-weighted mean observed post-break net rating (evaluation sample).", SIGNED),
    M("Mean Prediction Error", "VAR o = [Mean Observed]\nVAR p = [Mean Predicted]\nRETURN IF ( NOT ISBLANK ( o ) && NOT ISBLANK ( p ), o - p )",
      "6 Model", "Observed minus predicted (possession-weighted). Near 0 = unbiased in this slice.", SIGNED),
    # ---- Selection (Phase 4 definitions)
    M("Population Lineups",
      f"CALCULATE ( DISTINCTCOUNT ( {FLW}[lineup_id] ), dim_lineup[in_continuation_population] = 1, dim_window[window_type] = \"pre_asb\" )",
      "7 Selection", "Lineups with ≥ 25 pre-break possessions on each end.", "#,0"),
    M("Continuing Lineups",
      f"CALCULATE ( DISTINCTCOUNT ( {FLW}[lineup_id] ), dim_lineup[in_continuation_population] = 1, dim_lineup[continues_post_break] = 1, dim_window[window_type] = \"pre_asb\" )",
      "7 Selection", "Population lineups that played ≥ 25 possessions after the break.", "#,0"),
    M("Appearing Lineups",
      f"CALCULATE ( DISTINCTCOUNT ( {FLW}[lineup_id] ), dim_lineup[in_continuation_population] = 1, dim_lineup[appears_post_break] = 1, dim_window[window_type] = \"pre_asb\" )",
      "7 Selection", "Population lineups with any post-break possession.", "#,0"),
    M("Continuation Rate", "DIVIDE ( [Continuing Lineups], [Population Lineups] )", "7 Selection",
      "Share of pre-break lineups that keep playing (≥ 25 possessions) after the break.", "0.0%"),
    M("Appearance Rate", "DIVIDE ( [Appearing Lineups], [Population Lineups] )", "7 Selection",
      "Share of pre-break lineups seen at all after the break.", "0.0%"),
    M("Pre Net (continuing)",
      "CALCULATE ( [Net Rating Pre], dim_lineup[in_continuation_population] = 1, dim_lineup[continues_post_break] = 1 )",
      "7 Selection", "Pooled pre-break net rating of lineups that continue.", SIGNED),
    M("Pre Net (dropped)",
      "CALCULATE ( [Net Rating Pre], dim_lineup[in_continuation_population] = 1, dim_lineup[continues_post_break] = 0 )",
      "7 Selection", "Pooled pre-break net rating of lineups that do not continue.", SIGNED),
    # ---- Player filter semantics
    M("All Selected Players In Lineup",
      "VAR nSel = COUNTROWS ( ALLSELECTED ( dim_player[player_id] ) )\n"
      "VAR nAll = COUNTROWS ( ALL ( dim_player[player_id] ) )\n"
      "VAR nIn = DISTINCTCOUNT ( bridge_lineup_player[player_id] )\n"
      "RETURN IF ( nSel = nAll || nIn = nSel, 1, 0 )",
      "8 Filters", "Visual-level filter (= 1) for AND semantics: keep lineups that contain EVERY selected player. "
      "Without it a multi-player slicer means 'contains ANY selected player'.", "0"),
)


# ---------------------------------------------------------------------------------------------- helpers

def table(name: str) -> Table:
    return next(t for t in TABLES if t.name == name)


def data_tables() -> tuple[Table, ...]:
    return tuple(t for t in TABLES if t.source != "measures")


def measure(name: str) -> Measure:
    return next(m for m in MEASURES if m.name == name)
