"""The ONLY way to read the held-out seasons (2024-25, 2025-26).

`unlock(model_dir)` issues a HoldoutKey only if:
  1. frozen_spec.json exists with status "frozen";
  2. the artifact's SHA-256 equals the one recorded in the spec;
  3. both files are tracked by git and identical to the committed version (no uncommitted edits),
     so the commit history proves the model was frozen before the held-out data was read.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from ..analysis.data import HeldOutDataError
from ..config import PROJECT_ROOT
from .access import _MINT, HoldoutKey
from .final import ARTIFACT, SPEC, sha256


class NotFrozenError(HeldOutDataError):
    pass


def _git_clean_and_tracked(paths: list[Path], repo: Path) -> None:
    for p in paths:
        rel = str(Path(p).resolve().relative_to(repo.resolve()))
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=repo, capture_output=True)
        if tracked.returncode != 0:
            raise NotFrozenError(f"{rel} is not committed: commit the frozen model before unlocking the holdout")
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=repo)
        if dirty.returncode != 0:
            raise NotFrozenError(f"{rel} differs from the committed version")


def unlock(model_dir: Path, git_check: bool = True, repo: Path = PROJECT_ROOT) -> HoldoutKey:
    spec_path, artifact = Path(model_dir) / SPEC, Path(model_dir) / ARTIFACT
    if not spec_path.exists() or not artifact.exists():
        raise NotFrozenError("no frozen model: run scripts/phase6/train_evaluate.py and commit models/final/")
    spec = json.loads(spec_path.read_text())
    if spec.get("status") != "frozen":
        raise NotFrozenError("frozen_spec.json is not marked frozen")
    if sha256(artifact) != spec["artifact"]["sha256"]:
        raise NotFrozenError("model artifact does not match the frozen specification (hash mismatch)")
    if git_check:
        _git_clean_and_tracked([spec_path, artifact], repo)
    return HoldoutKey(_MINT, hashlib.sha256(spec_path.read_bytes()).hexdigest())
