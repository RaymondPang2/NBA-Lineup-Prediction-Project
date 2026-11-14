"""Pydantic models: the API contract.

Response models do double duty: FastAPI validates (and filters) every response against them, and they
generate the OpenAPI schema behind /docs. Request models validate input before any code runs.

Units: ratings are points per 100 possessions (exact, unrounded; round for display). `def_rating` is
points ALLOWED per 100 opponent possessions, so lower is better. Net = off − def.
"""
from __future__ import annotations

from datetime import date
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")
SEASON_PATTERN = r"^\d{4}-\d{2}$"


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0, description="rows matching the filters, over all pages")
    total_pages: int = Field(ge=0)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------------------------------------------------------------- catalog

class Window(BaseModel):
    window_type: Literal["pre_asb", "post_asb"]
    date_from: date
    date_to: date


class Season(BaseModel):
    season_id: str = Field(examples=["2025-26"])
    start_year: int
    is_irregular: bool = Field(description="2019-20 (bubble) and 2020-21 (72 games)")
    first_game_date: date
    last_game_date: date
    role: Literal["development", "held_out"] = Field(
        description="development: used to train the frozen model; held_out: its final test seasons")
    windows: list[Window]
    n_lineups: int


class Team(BaseModel):
    team_id: int
    abbreviation: str
    team_name: str


class Player(BaseModel):
    player_id: int
    player_name: str


# ---------------------------------------------------------------- shared stats

class WindowStats(BaseModel):
    """Totals and ratings for one window (pre- or post-All-Star break)."""
    gp: int | None = None
    minutes: float
    poss: int = Field(description="own (offensive) possessions")
    opp_poss: int | None = Field(description="opponent possessions; null only for zero-second rows")
    pts: int
    opp_pts: int
    off_rating: float | None
    def_rating: float | None
    net_rating: float | None
    net_rating_sampling_sd: float | None = Field(
        None, description="SD of the observed net rating from sampling noise alone: sqrt(K·(1/poss + 1/opp_poss))")


class Change(BaseModel):
    """Post-break minus pre-break. For def_rating a NEGATIVE change is an improvement."""
    off_rating: float | None
    def_rating: float | None
    net_rating: float | None
    net_rating_sampling_sd: float | None = Field(
        description="SD of the net-rating change expected from sampling noise alone, if true quality never changed")
    exceeds_noise: bool | None = Field(description="|change| > 1.96 × sampling SD (a rough flag, not a test of a "
                                                   "pre-chosen lineup: scanning many lineups finds some by chance)")


# ---------------------------------------------------------------- lineups

class LineupSummary(BaseModel):
    lineup_id: int
    season_id: str
    team_id: int
    team_abbreviation: str
    players: list[Player]
    pre_break: WindowStats | None
    post_break: WindowStats | None
    change: Change | None


class LineupDetail(LineupSummary):
    season_total: WindowStats | None


# ---------------------------------------------------------------- players and teams

class PlayerWindow(BaseModel):
    """A player's ON-COURT totals for one team in one window, pooled over every lineup they played in."""
    n_lineups: int
    minutes: float
    poss: int
    opp_poss: int | None
    off_rating: float | None
    def_rating: float | None
    net_rating: float | None
    off_court_net_rating: float | None = Field(description="team net rating with the player OFF the court")
    on_off_net: float | None = Field(description="on-court net minus off-court net (noisy, context-dependent)")


class PlayerUsage(BaseModel):
    """From the player endpoint: one row per season and window, ALL teams combined (traded players)."""
    gp: int
    minutes: float
    usg_pct: float | None = Field(description="share of team plays used while on court, 0-1")
    ts_pct: float | None


class PlayerTeamSeason(BaseModel):
    player_id: int
    player_name: str
    season_id: str
    team_id: int
    team_abbreviation: str
    pre_break: PlayerWindow | None
    post_break: PlayerWindow | None
    usage_pre_break: PlayerUsage | None
    usage_post_break: PlayerUsage | None


class PlayerDetail(Player):
    seasons: list[PlayerTeamSeason]


class TeamWindow(BaseModel):
    lineup_minutes: float = Field(description="sum over lineups (≈ team minutes)")
    poss: int
    opp_poss: int | None
    pts: int
    opp_pts: int
    off_rating: float | None
    def_rating: float | None
    net_rating: float | None
    games: int
    wins: int
    losses: int
    n_lineups: int


class TeamSeason(Team):
    season_id: str
    pre_break: TeamWindow | None
    post_break: TeamWindow | None
    change: Change | None


# ---------------------------------------------------------------- predictions

class PredictionRequest(BaseModel):
    """A lineup to predict: five players of one team in one season. The lineup need not have played together."""
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "season_id": "2025-26", "team_id": 1610612738,
        "player_ids": [1628369, 1627759, 201950, 1630202, 1628401], "possessions": 100}]})

    season_id: str = Field(pattern=SEASON_PATTERN)
    team_id: int = Field(gt=0)
    player_ids: list[int] = Field(min_length=5, max_length=5, description="exactly five distinct player ids")
    possessions: int = Field(100, ge=10, le=3000,
                             description="post-break possessions (each end) to size the predictive interval for")

    @field_validator("player_ids")
    @classmethod
    def _distinct(cls, v: list[int]) -> list[int]:
        if len(set(v)) != 5 or min(v) <= 0:
            raise ValueError("player_ids must be five distinct positive ids")
        return sorted(v)


class Interval(BaseModel):
    lo: float
    hi: float


class PredictionPlayer(Player):
    has_pre_break_data: bool = Field(description="played before the break this season (any team)")
    new_to_team: bool = Field(description="no pre-break minutes for THIS team (e.g. traded or returning)")


class Baselines(BaseModel):
    team_prior: float = Field(description="team's pre-break net rating from its OTHER lineups + a constant "
                                          "fitted on the development seasons. The reference the model must beat.")
    league_mean: float = Field(description="possession-weighted mean post-break net rating of development lineups")
    eb_lineup_team: float = Field(description="the lineup's own pre-break rating shrunk toward the team prior")


class Uncertainty(BaseModel):
    possessions: int = Field(description="post-break possessions on each end assumed for the intervals")
    model_sd: float = Field(description="PREDICTIVE (model) uncertainty: typical error of the prediction about the "
                                        "lineup's TRUE post-break rating, sqrt(MSE − noise variance) on held-out data")
    sampling_sd: float = Field(description="SAMPLING uncertainty: how much the OBSERVED rating varies around the "
                                           "true one after `possessions` possessions, sqrt(K·2/possessions)")
    total_sd: float = Field(description="sqrt(model_sd² + sampling_sd²): error vs the rating you would observe")
    true_rating_interval_95: Interval
    observed_rating_interval_95: Interval
    method: str


class Contribution(BaseModel):
    feature: str
    description: str
    value: float | None = Field(description="raw feature value (null = missing, imputed with the training median)")
    contribution: float = Field(description="coefficient × standardized value: points this feature adds to the "
                                            "intercept. Contributions + intercept = prediction")


class PreBreakContext(BaseModel):
    poss: int
    opp_poss: int
    net_rating: float | None = Field(description="raw pre-break net rating (noisy at small samples)")
    reliability: float = Field(description="share of the raw rating's variance that is signal (0 without history)")
    team_net_rating_excluding_lineup: float | None


class ObservedPostBreak(BaseModel):
    """What actually happened after the break. NOT an input: the prediction never reads post-break data."""
    poss: int
    opp_poss: int | None
    net_rating: float | None
    in_evaluation_sample: bool = Field(description="≥ 25 possessions on each end (the model's target sample)")


class Prediction(BaseModel):
    lineup_id: int | None = Field(description="null for a combination that never played together this season")
    season_id: str
    team_id: int
    team_abbreviation: str
    players: list[PredictionPlayer]
    predicted_net_rating: float = Field(description="frozen linear model, post-break net rating per 100 possessions")
    baselines: Baselines
    model_minus_team_prior: float
    uncertainty: Uncertainty
    pre_break: PreBreakContext
    intercept: float
    contributions: list[Contribution]
    season_used_for_training: bool = Field(description="true: this season's post-break results were training "
                                                       "labels, so the prediction is in-sample")
    observed_post_break: ObservedPostBreak | None = None
    notes: list[str]


# ---------------------------------------------------------------- model card

class Coefficient(BaseModel):
    feature: str
    description: str
    coefficient: float = Field(description="net-rating points per 1 training SD of the feature")
    training_mean: float
    training_sd: float


class Estimate(BaseModel):
    estimate: float
    lo: float = Field(description="95% team-season cluster-bootstrap interval")
    hi: float


class EvaluationSummary(BaseModel):
    evaluation: str
    n_lineups: int | None
    rmse_model: Estimate
    rmse_team_prior: Estimate
    rmse_league_mean: Estimate
    rmse_noise_floor: Estimate
    r2_model: Estimate
    r2_ceiling: Estimate
    model_minus_team_prior: Estimate
    model_minus_league_mean: Estimate | None
    calibration_slope: Estimate | None


class ModelPerformance(BaseModel):
    weighting: str
    development_cv: EvaluationSummary
    held_out: list[EvaluationSummary]
    beats_team_prior: bool = Field(description="pre-registered primary question: does the pooled held-out RMSE "
                                               "difference vs the team prior have a 95% CI entirely below 0?")
    beats_league_mean: bool
    conclusion: str


class ModelCard(BaseModel):
    name: str
    label: str
    frozen_at_utc: str
    artifact_sha256: str
    spec_sha256: str
    artifact_verified: bool = Field(description="artifact on disk re-hashed now and equal to the frozen spec")
    trained_seasons: list[str]
    held_out_seasons: list[str]
    prediction_target: str
    sample_weight: str
    features_in: list[str]
    features_used: list[str]
    intercept: float
    coefficients: list[Coefficient]
    selection: dict
    uncertainty_method: str
    appropriate_use: list[str]
    not_for: list[str]
    limitations: list[str]
    software: dict


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable", "not_configured"]
    model: Literal["ok", "unavailable"]
    model_artifact_sha256: str | None = None
