"""The five report pages, as data: every visual's type, position, fields and title.

The PBIR generator (project.py) turns this into Power BI report files; docs/powerbi.md is written from the
same specification, so the documented layout and the generated report cannot drift apart.
Canvas: 1280 x 720 (16:9).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# A field is ("col", table, column) or ("measure", measure name).
Field = tuple


def col(table: str, column: str) -> Field:
    return ("col", table, column)


def mea(name: str) -> Field:
    return ("measure", name)


@dataclass(frozen=True)
class Visual:
    name: str
    type: str                                   # slicer | card | tableEx | clusteredBarChart | clusteredColumnChart | lineChart | scatterChart | textbox
    x: int
    y: int
    w: int
    h: int
    roles: dict[str, list[Field]] = field(default_factory=dict)
    title: str | None = None
    sort: tuple[Field, str] | None = None       # (field, "Ascending" | "Descending")
    text: tuple[str, ...] = ()                  # textbox paragraphs; the first is the heading
    dropdown: bool = False                      # slicer style
    searchable: bool = False


@dataclass(frozen=True)
class Page:
    name: str
    display_name: str
    purpose: str
    visuals: tuple[Visual, ...]


def _header(title: str, subtitle: str) -> Visual:
    return Visual("header", "textbox", 24, 12, 760, 64, text=(title, subtitle))


def _slicer(name: str, f: Field, x: int, title: str, w: int = 150, searchable: bool = False) -> Visual:
    return Visual(name, "slicer", x, 16, w, 56, roles={"Values": [f]}, title=title, dropdown=True, searchable=searchable)


SEASON = col("dim_season", "season_id")
TEAM = col("dim_team", "team_name")

PAGES: tuple[Page, ...] = (
    Page("TeamOverview", "1 Team Overview",
         "Team efficiency and records, before and after the All-Star break. Team ratings are pooled from summed lineup totals.",
         (
             _header("Team Overview", "Team ratings pooled from lineup totals (points ÷ possessions × 100); W–L from game logs."),
             _slicer("slicerSeason", SEASON, 820, "Season"),
             _slicer("slicerWindow", col("dim_window", "window_label"), 980, "Window"),
             Visual("cardNet", "card", 24, 88, 200, 96, {"Values": [mea("Net Rating")]}, "Net rating"),
             Visual("cardOrtg", "card", 236, 88, 200, 96, {"Values": [mea("ORtg")]}, "Offensive rating"),
             Visual("cardDrtg", "card", 448, 88, 200, 96, {"Values": [mea("DRtg")]}, "Defensive rating"),
             Visual("cardWinPct", "card", 660, 88, 200, 96, {"Values": [mea("Win %")]}, "Win %"),
             Visual("cardLineups", "card", 872, 88, 200, 96, {"Values": [mea("Lineups")]}, "Lineups used"),
             Visual("cardPoss", "card", 1084, 88, 172, 96, {"Values": [mea("Possessions")]}, "Possessions"),
             Visual("barNetPrePost", "clusteredBarChart", 24, 196, 410, 508,
                    {"Category": [col("dim_team", "abbreviation")], "Y": [mea("Net Rating Pre"), mea("Net Rating Post")]},
                    "Net rating, pre- vs post-break", sort=(mea("Net Rating Pre"), "Descending")),
             Visual("scatterOffDef", "scatterChart", 446, 196, 400, 300,
                    {"Category": [col("dim_team", "abbreviation")], "X": [mea("ORtg")], "Y": [mea("DRtg")]},
                    "Offense vs defense (lower DRtg is better)"),
             Visual("tableTeams", "tableEx", 446, 508, 810, 196,
                    {"Values": [TEAM, mea("Record"), mea("Win %"), mea("ORtg Pre"), mea("DRtg Pre"), mea("Net Rating Pre"),
                                mea("Net Rating Post"), mea("Net Change")]},
                    "Team table", sort=(mea("Net Rating Pre"), "Descending")),
             Visual("lineWinPct", "lineChart", 858, 196, 398, 300,
                    {"Category": [SEASON], "Y": [mea("Net Rating Pre"), mea("Net Rating Post")]},
                    "Net rating by season (pre vs post)"),
         )),
    Page("LineupAnalysis", "2 Lineup Analysis",
         "Interactive lineup rankings with player, team, season and sample-size filters. A player filter keeps lineups that contain that player; each lineup is counted once.",
         (
             _header("Lineup Analysis", "Select players to find their lineups. Ratings are shown with their sampling error and reliability."),
             _slicer("slicerSeason", SEASON, 800, "Season", 120),
             _slicer("slicerTeam", TEAM, 930, "Team", 160, searchable=True),
             _slicer("slicerWindow", col("dim_window", "window_label"), 1100, "Window", 156),
             Visual("slicerPlayer", "slicer", 24, 88, 220, 400, {"Values": [col("dim_player", "player_name")]}, "Players (search)",
                    searchable=True),
             Visual("slicerTier", "slicer", 24, 500, 220, 204, {"Values": [col("dim_lineup", "pre_sample_tier")]},
                    "Pre-break sample size"),
             Visual("cardLineups", "card", 256, 88, 240, 88, {"Values": [mea("Lineups")]}, "Lineups"),
             Visual("cardPoss", "card", 508, 88, 240, 88, {"Values": [mea("Possessions")]}, "Possessions"),
             Visual("cardNet", "card", 760, 88, 240, 88, {"Values": [mea("Net Rating")]}, "Net rating (pooled)"),
             Visual("cardRel", "card", 1012, 88, 244, 88, {"Values": [mea("Reliability")]}, "Reliability"),
             Visual("tableLineups", "tableEx", 256, 188, 1000, 316,
                    {"Values": [col("dim_lineup", "lineup_label"), mea("Minutes"), mea("Possessions"), mea("ORtg"), mea("DRtg"),
                                mea("Net Rating"), mea("Net Rating SE"), mea("Reliability"), mea("Net Change")]},
                    "Lineup rankings (sort any column)", sort=(mea("Possessions"), "Descending")),
             Visual("scatterPossNet", "scatterChart", 256, 516, 1000, 188,
                    {"Category": [col("dim_lineup", "lineup_label")], "X": [mea("Possessions")], "Y": [mea("Net Rating")]},
                    "Net rating vs possessions: small samples fan out"),
         )),
    Page("Reliability", "3 Statistical Reliability",
         "How sample size drives uncertainty: most lineups play few possessions, and their ratings are mostly noise.",
         (
             _header("Statistical Reliability", "Sampling SE = √(K·(1/poss + 1/opp_poss)); reliability = τ² ÷ (τ² + SE²)."),
             _slicer("slicerSeason", SEASON, 820, "Season"),
             _slicer("slicerWindow", col("dim_window", "window_label"), 980, "Window"),
             Visual("cardK", "card", 24, 88, 300, 88, {"Values": [mea("K (noise constant)")]}, "Noise constant K"),
             Visual("card100", "card", 336, 88, 300, 88, {"Values": [mea("Lineups ≥ 100 Poss")]}, "Lineups with ≥ 100 possessions"),
             Visual("cardShare", "card", 648, 88, 300, 88, {"Values": [mea("Share of Possessions in Lineups ≥ 100")]},
                    "Share of possessions in those lineups"),
             Visual("cardRel", "card", 960, 88, 296, 88, {"Values": [mea("Reliability")]}, "Reliability (pooled)"),
             Visual("colTierCount", "clusteredColumnChart", 24, 188, 400, 250,
                    {"Category": [col("dim_lineup", "pre_sample_tier")], "Y": [mea("Lineups")]}, "Lineups by pre-break sample size"),
             Visual("colTierPoss", "clusteredColumnChart", 436, 188, 400, 250,
                    {"Category": [col("dim_lineup", "pre_sample_tier")], "Y": [mea("Possessions")]}, "Possessions by sample size"),
             Visual("colTierSpread", "clusteredColumnChart", 848, 188, 408, 250,
                    {"Category": [col("dim_lineup", "pre_sample_tier")],
                     "Y": [mea("Lineup Net SD (possession-weighted)"), mea("Noise SD (possession-weighted)")]},
                    "Spread of lineup net ratings vs pure noise"),
             Visual("colTierAvg", "clusteredColumnChart", 24, 450, 610, 254,
                    {"Category": [col("dim_lineup", "pre_sample_tier")],
                     "Y": [mea("Lineup Net Avg (unweighted, misleading)"), mea("Lineup Net Avg (possession-weighted)")]},
                    "Why ratings must not be averaged: small-sample bias"),
             Visual("scatterFunnel", "scatterChart", 646, 450, 610, 254,
                    {"Category": [col("dim_lineup", "lineup_label")], "X": [mea("Possessions")], "Y": [mea("Net Rating SE")]},
                    "Sampling error falls with possessions"),
         )),
    Page("ModelPerformance", "4 Model Performance",
         "The frozen linear model against its baselines, possession-weighted, on lineups with ≥ 25 post-break possessions per end.",
         (
             _header("Model Performance", "Judge accuracy on the held-out seasons (2024-25, 2025-26). Training seasons show in-sample fitted values."),
             _slicer("slicerEvalSet", col("fact_prediction", "evaluation_set"), 820, "Evaluation set", 220),
             _slicer("slicerSeason", SEASON, 1050, "Season", 206),
             Visual("cardModelRmse", "card", 24, 88, 200, 88, {"Values": [mea("Model RMSE")]}, "Model RMSE"),
             Visual("cardPriorRmse", "card", 236, 88, 200, 88, {"Values": [mea("Team Prior RMSE")]}, "Team-prior RMSE"),
             Visual("cardDiff", "card", 448, 88, 200, 88, {"Values": [mea("Model − Team Prior RMSE")]}, "Model − team prior"),
             Visual("cardFloor", "card", 660, 88, 200, 88, {"Values": [mea("Noise Floor RMSE")]}, "Noise floor RMSE"),
             Visual("cardR2", "card", 872, 88, 190, 88, {"Values": [mea("Model R²")]}, "Model R²"),
             Visual("cardCeiling", "card", 1074, 88, 182, 88, {"Values": [mea("R² Ceiling")]}, "R² ceiling"),
             Visual("colRmseBySeason", "clusteredColumnChart", 24, 188, 610, 260,
                    {"Category": [SEASON], "Y": [mea("Model RMSE"), mea("Team Prior RMSE"), mea("League Mean RMSE"), mea("Noise Floor RMSE")]},
                    "RMSE by season: model vs baselines vs noise floor"),
             Visual("lineCalibration", "lineChart", 646, 188, 610, 260,
                    {"Category": [col("fact_prediction", "predicted_decile")], "Y": [mea("Mean Predicted"), mea("Mean Observed")]},
                    "Calibration: predicted vs observed by prediction decile"),
             Visual("scatterPredObs", "scatterChart", 24, 460, 610, 244,
                    {"Category": [col("dim_lineup", "lineup_label")], "X": [mea("Mean Predicted")], "Y": [mea("Mean Observed")]},
                    "Predicted vs observed (each dot a lineup)"),
             Visual("notes", "textbox", 646, 460, 610, 244, text=(
                 "Limitations",
                 "Conditional estimand: the prediction is the expected post-break net rating IF the coach plays the lineup after the break.",
                 "Not statistically better than the team-prior baseline on the held-out seasons (RMSE difference −0.08, 95% CI −0.29 to +0.12).",
                 "The target is dominated by sampling noise: compare every RMSE with the noise floor.",
                 "Training seasons (2018-19 to 2023-24) show in-sample fitted values, not test results.",
             )),
         )),
    Page("SelectionBias", "5 Selection Bias",
         "Which pre-break lineups keep playing after the break? The post-break sample is selected, not random.",
         (
             _header("Selection Bias", "Population: lineups with ≥ 25 pre-break possessions per end. Continues: ≥ 25 possessions after the break."),
             _slicer("slicerSeason", SEASON, 820, "Season"),
             _slicer("slicerTeam", TEAM, 980, "Team", 276, searchable=True),
             Visual("cardPop", "card", 24, 88, 240, 88, {"Values": [mea("Population Lineups")]}, "Pre-break lineups (≥ 25 poss)"),
             Visual("cardCont", "card", 276, 88, 240, 88, {"Values": [mea("Continuation Rate")]}, "Continue after the break"),
             Visual("cardApp", "card", 528, 88, 240, 88, {"Values": [mea("Appearance Rate")]}, "Appear at all"),
             Visual("cardNetCont", "card", 780, 88, 236, 88, {"Values": [mea("Pre Net (continuing)")]}, "Pre-break net: continued"),
             Visual("cardNetDrop", "card", 1028, 88, 228, 88, {"Values": [mea("Pre Net (dropped)")]}, "Pre-break net: dropped"),
             Visual("colByPoss", "clusteredColumnChart", 24, 188, 610, 270,
                    {"Category": [col("dim_lineup", "pre_poss_bin")], "Y": [mea("Continuation Rate"), mea("Appearance Rate")]},
                    "Continuation by pre-break possessions"),
             Visual("lineBySeason", "lineChart", 646, 188, 610, 270,
                    {"Category": [SEASON], "Y": [mea("Continuation Rate")]}, "Continuation rate by season"),
             Visual("tableBins", "tableEx", 24, 470, 830, 234,
                    {"Values": [col("dim_lineup", "pre_poss_bin"), mea("Population Lineups"), mea("Continuing Lineups"),
                                mea("Continuation Rate"), mea("Pre Net (continuing)"), mea("Pre Net (dropped)")]},
                    "Continuation by sample size"),
             Visual("notes", "textbox", 866, 470, 390, 234, text=(
                 "Why it matters",
                 "Coaches keep lineups that played more and looked better. Post-break results therefore describe a selected sample.",
                 "That is why every prediction is conditional on the lineup playing after the break, and why it is never a forecast of usage.",
             )),
         )),
)


def all_fields() -> list[Field]:
    return [f for p in PAGES for v in p.visuals for fs in v.roles.values() for f in fs] + \
           [v.sort[0] for p in PAGES for v in p.visuals if v.sort]
