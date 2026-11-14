"""The API serves the frozen model and cannot retrain or alter it.

1. Startup refuses a tampered artifact or specification.
2. The API source never calls a fitting or serializing method (static AST scan).
3. Only GET routes, plus one read-only POST (/predictions); no PUT / PATCH / DELETE.
4. Serving many predictions leaves the artifact on disk and the parameters in memory unchanged.
"""
from __future__ import annotations

import ast
import json
import shutil

import pytest

from nba_lineups.api.services.predictions import FrozenPredictor, ModelIntegrityError
from nba_lineups.config import PROJECT_ROOT
from nba_lineups.modeling import final
from nba_lineups.modeling.holdout import NotFrozenError

MODEL_DIR, REPORTS = PROJECT_ROOT / "models" / "final", PROJECT_ROOT / "reports" / "phase6"
API_SRC = PROJECT_ROOT / "src" / "nba_lineups" / "api"
FORBIDDEN_CALLS = {"fit", "fit_transform", "partial_fit", "set_params", "fit_final", "fit_model", "freeze", "dump",
                   "tune", "run_models", "write_text", "write_bytes", "unlink", "rmtree"}


@pytest.fixture
def model_copy(tmp_path):
    d = tmp_path / "final"
    shutil.copytree(MODEL_DIR, d)
    return d


def test_startup_accepts_the_frozen_model():
    p = FrozenPredictor(MODEL_DIR, REPORTS)                 # with the git check: committed and unchanged
    assert p.artifact_sha256 == json.loads((MODEL_DIR / final.SPEC).read_text())["artifact"]["sha256"]
    assert p.model.model_name == "linear" and p.verify()


def test_startup_refuses_swapped_artifact(model_copy):
    (model_copy / final.ARTIFACT).write_bytes((model_copy / final.ARTIFACT).read_bytes() + b"\0")
    with pytest.raises(ModelIntegrityError, match="SHA-256"):
        FrozenPredictor(model_copy, REPORTS, require_git_freeze=False)


def test_startup_refuses_unfrozen_spec(model_copy):
    spec = json.loads((model_copy / final.SPEC).read_text())
    (model_copy / final.SPEC).write_text(json.dumps(spec | {"status": "draft"}))
    with pytest.raises(ModelIntegrityError, match="not marked frozen"):
        FrozenPredictor(model_copy, REPORTS, require_git_freeze=False)


def test_startup_refuses_spec_naming_other_features(model_copy):
    spec = json.loads((model_copy / final.SPEC).read_text())
    spec["model"]["features_used"] = spec["model"]["features_used"][:-1]
    (model_copy / final.SPEC).write_text(json.dumps(spec))
    with pytest.raises(ModelIntegrityError, match="differs from the frozen specification"):
        FrozenPredictor(model_copy, REPORTS, require_git_freeze=False)


def test_startup_requires_committed_model_by_default(model_copy):
    """A copy outside the repository is not committed: the default git check refuses it."""
    with pytest.raises((NotFrozenError, ValueError)):
        FrozenPredictor(model_copy, REPORTS)


def test_api_source_never_fits_or_writes():
    for f in API_SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                assert name not in FORBIDDEN_CALLS, f"{f.name}:{node.lineno} calls {name}()"
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.endswith(("tuning", "cv", "build")), f"{f.name} imports {node.module}"
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open":
                assert False, f"{f.name}:{node.lineno} opens a file"


def test_api_sql_never_reads_last_team_id():
    """last_team_id leaks post-break trades (Phase 4); only docstrings may mention it."""
    for f in API_SRC.rglob("*.py"):
        tree = ast.parse(f.read_text())
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                assert "last_team_id" not in node.value, f"{f.name}:{node.lineno}"


def test_only_read_only_routes(offline_client):
    paths = offline_client.get("/openapi.json").json()["paths"]
    methods = {(p, m.upper()) for p, item in paths.items() for m in item}
    assert len(methods) >= 14
    writes = {(p, m) for p, m in methods if m not in {"GET", "HEAD"}}
    assert writes == {("/api/v1/predictions", "POST")}
    for p in ("/api/v1/model", "/api/v1/predictions", "/api/v1/lineups/1/prediction"):
        for m in ("put", "patch", "delete"):
            assert getattr(offline_client, m)(p).status_code == 405


def test_predictions_do_not_change_model(offline_client):
    """Score many lineups through the same code path the endpoints use (synthetic rows: no database)."""
    p = offline_client.app.state.predictor
    before_disk, before_mem = final.sha256(p.artifact_path), p.parameters_fingerprint()
    coef = p.model.pipeline.named_steps["model"].coef_.copy()
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(0)
    rows = pd.DataFrame(rng.normal(size=(200, len(p.model.features))), columns=p.model.features)
    for _, r in rows.iterrows():
        p.contributions(r)
    p.model.predict_frame(rows)
    assert final.sha256(p.artifact_path) == before_disk == p.spec["artifact"]["sha256"]
    assert p.parameters_fingerprint() == before_mem and np.array_equal(coef, p.model.pipeline.named_steps["model"].coef_)
    assert p.verify()


def test_verify_detects_in_memory_mutation():
    p = FrozenPredictor(MODEL_DIR, REPORTS)
    p.model.pipeline.named_steps["model"].coef_[0] += 1e-9       # a private copy, never written to disk
    assert not p.verify()
