"""Tests for bobverified.reverify (written by the team; Bob writes the implementation)."""
import json
import re
import subprocess
import sys

import pytest

from bobverified import reverify
from test_gate import free_port, make_app, make_config

STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def make_run_dir(root, app, port):
    root.mkdir(parents=True, exist_ok=True)
    cfg = make_config(port)
    cfg["workdir"] = str(app)
    (root / "target.json").write_text(json.dumps(cfg))
    (root / "plan.json").write_text(json.dumps({"title": "t", "steps": [
        {"id": "step_01", "title": "one", "verify": f"{sys.executable} -m pytest -q test_lib.py"},
        {"id": "step_02", "title": "no verify command here"},
    ]}))
    return root


def test_reverify_passes_on_working_target_and_logs_with_timestamps(tmp_path):
    app = make_app(tmp_path / "app")
    run_dir = make_run_dir(tmp_path / "run", app, free_port())
    res = reverify.reverify(str(run_dir))
    assert res["all_ok"] is True
    ids = [r["step_id"] for r in res["results"]]
    assert ids == ["step_01", "final"]  # steps without a verify command are skipped; "final" has no step command
    assert all(r["verdict"] == "ACCEPT" for r in res["results"])
    assert STAMP.search(res["utc"])
    assert len(STAMP.findall(res["log"])) >= 3
    assert "step_01" in res["log"] and "final" in res["log"]
    saved = list((run_dir / "reverify").glob("*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text())["log"] == res["log"]
    assert (run_dir / "reverify.log").read_text().strip() != ""


def test_reverify_fails_on_broken_target(tmp_path):
    app = make_app(tmp_path / "app", bug=True)
    run_dir = make_run_dir(tmp_path / "run", app, free_port())
    res = reverify.reverify(str(run_dir))
    assert res["all_ok"] is False
    first = res["results"][0]
    assert first["verdict"] == "REJECT_CHECKS_FAILED"
    assert "tests" in first["failed"]


def test_reverify_missing_target_json_raises(tmp_path):
    (tmp_path / "run").mkdir()
    with pytest.raises(FileNotFoundError):
        reverify.reverify(str(tmp_path / "run"))


def test_reverify_second_call_adds_a_second_record(tmp_path):
    app = make_app(tmp_path / "app")
    run_dir = make_run_dir(tmp_path / "run", app, free_port())
    reverify.reverify(str(run_dir))
    reverify.reverify(str(run_dir))
    assert len(list((run_dir / "reverify").glob("*.json"))) == 2


def test_cli_prints_log_and_sets_exit_code(tmp_path):
    app = make_app(tmp_path / "app")
    run_dir = make_run_dir(tmp_path / "run", app, free_port())
    r = subprocess.run([sys.executable, "-m", "bobverified.reverify", "--run", str(run_dir)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "step_01" in r.stdout
