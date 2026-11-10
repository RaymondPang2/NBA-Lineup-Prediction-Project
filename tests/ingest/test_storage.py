import os

import pytest

from nba_lineups.ingest.storage import atomic_write_json, read_json


def test_roundtrip_and_no_temp_files_left(tmp_path):
    path = tmp_path / "a" / "b.json"
    sha = atomic_write_json(path, {"x": [1, 2]})
    assert read_json(path) == {"x": [1, 2]}
    assert len(sha) == 64
    assert [p.name for p in path.parent.iterdir()] == ["b.json"]


def test_failed_replace_keeps_old_file_and_cleans_up(tmp_path, monkeypatch):
    path = tmp_path / "b.json"
    atomic_write_json(path, {"version": 1})

    def boom(*_):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_json(path, {"version": 2})
    assert read_json(path) == {"version": 1}          # old file untouched
    assert [p.name for p in tmp_path.iterdir()] == ["b.json"]  # temp file removed


def test_read_json_handles_missing_and_truncated(tmp_path):
    assert read_json(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text('{"resultSets": [')  # what a crash mid-write WITHOUT atomic writes would leave
    assert read_json(bad) is None
