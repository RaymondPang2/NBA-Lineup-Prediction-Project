from __future__ import annotations

import platform

from fastapi import APIRouter

from ...config import HELDOUT_SEASONS
from ..deps import Predictor
from ..schemas import ModelCard, ModelPerformance
from ..services.model_info import APPROPRIATE_USE, DESCRIPTIONS, ESTIMAND, LIMITATIONS, NOT_FOR

router = APIRouter(prefix="/model", tags=["model"])


@router.get("", response_model=ModelCard, summary="Model card of the frozen model")
def model_card(predictor: Predictor):
    """What the model is, what it was trained on, its coefficients, intended use and limitations.
    `artifact_verified` re-hashes the artifact on disk and checks the in-memory parameters on every call."""
    s, pipe = predictor.spec, predictor.model.pipeline
    scale = pipe.named_steps["scale"]
    coefs = [{"feature": f, "description": DESCRIPTIONS.get(f, f), "coefficient": float(c),
              "training_mean": float(mu), "training_sd": float(sd)}
             for f, c, mu, sd in zip(predictor.features_used, pipe.named_steps["model"].coef_, scale.mean_, scale.scale_)]
    return {
        "name": s["model"]["name"], "label": s["model"]["label"], "frozen_at_utc": s["frozen_at_utc"],
        "artifact_sha256": predictor.artifact_sha256, "spec_sha256": predictor.spec_sha256,
        "artifact_verified": predictor.verify(), "trained_seasons": s["model"]["trained_seasons"],
        "held_out_seasons": list(HELDOUT_SEASONS), "prediction_target": ESTIMAND,
        "sample_weight": s["model"]["sample_weight"], "features_in": s["model"]["features_in"],
        "features_used": s["model"]["features_used"],
        "intercept": float(pipe.named_steps["model"].intercept_),
        "coefficients": sorted(coefs, key=lambda d: -abs(d["coefficient"])),
        "selection": {k: v for k, v in s["selection"].items() if k != "rule_text"},
        "uncertainty_method": predictor.uncertainty(0.0, 100)["method"],
        "appropriate_use": APPROPRIATE_USE, "not_for": NOT_FOR, "limitations": LIMITATIONS,
        "software": s["versions"] | {"serving_python": platform.python_version()},
    }


@router.get("/performance", response_model=ModelPerformance, summary="Evaluation results")
def model_performance(predictor: Predictor):
    """Development cross-validation and the one-time held-out evaluation, possession-weighted, with 95%
    team-season cluster-bootstrap intervals, and the answer to the pre-registered question: does the model
    beat the team prior?"""
    return predictor.reports.performance()
