"""The held-out seasons can only be read with a key, and a key only exists for a frozen, committed model."""
from __future__ import annotations

import json
import subprocess

import pytest

from nba_lineups.analysis.data import HeldOutDataError
from nba_lineups.modeling import access, final, holdout, raw
from nba_lineups.modeling.features import FeatureBuilder

from . import synthetic


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def frozen_repo(tmp_path):
    """A throwaway git repo containing a frozen model directory (not committed yet)."""
    repo = tmp_path / "repo"
    model_dir = repo / "models" / "final"
    model_dir.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    tables, targets = synthetic.make()
    final.freeze(final.fit_final("linear", {}, tables, targets), model_dir, {"chosen": "linear"}, {})
    return repo, model_dir


def test_key_cannot_be_forged():
    with pytest.raises(HeldOutDataError):
        access.HoldoutKey(object(), "x")


def test_unlock_requires_a_frozen_model(tmp_path):
    with pytest.raises(holdout.NotFrozenError):
        holdout.unlock(tmp_path, git_check=False)


def test_unlock_requires_the_model_to_be_committed(frozen_repo):
    repo, model_dir = frozen_repo
    with pytest.raises(holdout.NotFrozenError, match="not committed"):
        holdout.unlock(model_dir, repo=repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "freeze")
    key = holdout.unlock(model_dir, repo=repo)
    assert isinstance(key, access.HoldoutKey)


def test_unlock_rejects_edits_after_the_freeze(frozen_repo):
    repo, model_dir = frozen_repo
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "freeze")
    spec_path = model_dir / final.SPEC
    spec = json.loads(spec_path.read_text())
    spec["model"]["params"] = {"retuned": True}
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(holdout.NotFrozenError, match="differs"):
        holdout.unlock(model_dir, repo=repo)


def test_unlock_rejects_a_swapped_artifact(frozen_repo):
    repo, model_dir = frozen_repo
    (model_dir / final.ARTIFACT).write_bytes(b"not the frozen model")
    with pytest.raises(holdout.NotFrozenError, match="hash"):
        holdout.unlock(model_dir, git_check=False)


def test_spec_not_marked_frozen_is_rejected(frozen_repo):
    _, model_dir = frozen_repo
    spec_path = model_dir / final.SPEC
    spec = json.loads(spec_path.read_text())
    spec["status"] = "draft"
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(holdout.NotFrozenError, match="not marked frozen"):
        holdout.unlock(model_dir, git_check=False)


def test_key_admits_held_out_seasons_but_fitting_on_them_is_still_refused(frozen_repo):
    repo, model_dir = frozen_repo
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "freeze")
    key = holdout.unlock(model_dir, repo=repo)
    assert access.check_seasons(["2024-25", "2025-26"], key) == ["2024-25", "2025-26"]
    with pytest.raises(HeldOutDataError):
        access.check_seasons(["2024-25"])                       # no key
    tables, _ = synthetic.make()
    relabel = lambda d: d.assign(season_id=d.season_id.replace("2020-21", "2024-25"))  # noqa: E731
    with pytest.raises(HeldOutDataError):
        raw.build_tables(relabel(tables.lineups), relabel(tables.members), relabel(tables.usage))
    unlocked = raw.build_tables(relabel(tables.lineups), relabel(tables.members), relabel(tables.usage), key=key)
    with pytest.raises(HeldOutDataError):
        FeatureBuilder().fit(unlocked, ["2018-19", "2024-25"])
    b = FeatureBuilder().fit(unlocked, ["2018-19", "2019-20"])      # fitting on dev seasons is fine
    assert b.train_seasons_ == ("2018-19", "2019-20")
