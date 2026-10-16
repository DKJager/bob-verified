"""End-to-end test: wire + runner + gate + ledger + dashboard + reverify on a tiny repo with a FAKE Bob.

The fake Bob never calls any model. Step 1 makes a harmless real change. Step 2 breaks the code but
still prints a success result, so only the independent gate can catch it."""
import json
import os
import subprocess
import sys

import pytest

from bobverified import dashboard, ledger, reverify
from test_gate import free_port, make_app, make_config
from test_ledger import make_db

FAKE_BOB = r'''#!/usr/bin/env python3
import json, sys, pathlib
args = sys.argv[1:]
ws = pathlib.Path(args[args.index("--workspace") + 1])
prompt = args[-1]
if "step_01" in prompt:
    p = ws / "lib.py"
    p.write_text('"""Tiny library."""\n' + p.read_text())
elif "step_02" in prompt:
    (ws / "lib.py").write_text("def add(a, b):\n    return a - b\n")
cost = 0.25 if "step_01" in prompt else 0.5
print(json.dumps({"type": "result", "status": "success",
                  "stats": {"task_id": "fake-" + ("1" if "step_01" in prompt else "2"), "session_costs": cost}}))
'''


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_pipeline_accepts_good_step_and_rejects_step_that_claims_success_but_is_broken(tmp_path):
    work = make_app(tmp_path / "work" / "tiny")
    git(work, "init", "-q", "-b", "main")
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "T")
    (work / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "upstream state")

    verify = f"{sys.executable} -m pytest -q test_lib.py"
    plan = {"title": "Modernize tiny", "steps": [
        {"id": "step_01", "title": "Add module docstring", "description": "Document lib.", "verify": verify},
        {"id": "step_02", "title": "Rewrite add", "description": "Rewrite add.", "verify": verify},
    ]}
    cfg = make_config(free_port())
    cfg.update(name="tiny", url="https://example.com/tiny", commit="deadbeef", license="MIT")
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "target.json").write_text(json.dumps(cfg))
    fake = tmp_path / "fake_bob.py"
    fake.write_text(FAKE_BOB)
    fake.chmod(0o755)
    ev = tmp_path / "evidence"
    tasks = tmp_path / "tasks.json"
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(dashboard.__file__)))

    r = subprocess.run([sys.executable, "-m", "bobverified.wire", "--plan", str(tmp_path / "plan.json"),
                        "--target", str(tmp_path / "target.json"), "--workdir", str(work),
                        "--evidence", str(ev), "--out", str(tasks), "--budget", "5"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    env = {**os.environ, "BOB_API_KEY": "fake-key-for-test", "PYTHONPATH": pkg_root}
    r = subprocess.run([sys.executable, "-m", "bobverified.bobrun", "--tasks", str(tasks), "--workspace", str(work),
                        "--evidence", str(ev), "--bob", str(fake)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr

    # Step 1 accepted and committed with trailers; step 2 rejected, nothing committed, tree restored.
    log = git(work, "log", "--format=%B%x00")
    assert "Bob-Task: fake-1" in log
    assert "Bob-Task: fake-2" not in log
    assert len(git(work, "log", "--oneline").splitlines()) == 2  # upstream state + step 1 only
    assert (work / "lib.py").read_text().startswith('"""Tiny library."""')
    assert "a + b" in (work / "lib.py").read_text()

    g1 = json.loads((ev / "gate" / "step_01.json").read_text())
    g2 = json.loads((ev / "gate" / "step_02.json").read_text())
    assert g1["verdict"] == "ACCEPT" and g1["control"]["ran"] is True
    assert g2["verdict"] == "REJECT_CHECKS_FAILED"

    run = dashboard.load_run(str(ev))
    st = {s["id"]: s for s in run["steps"]}
    assert st["step_01"]["status"] == "done" and st["step_02"]["status"] == "fail"
    assert run["total_cost"] == pytest.approx(0.75)
    html = dashboard.render_html(run)
    assert "REJECT_CHECKS_FAILED" in html and "ACCEPT" in html

    db = str(tmp_path / "bob.db")
    make_db(db, [("fake-1", "completed", 0.25, 10, "s1"), ("fake-2", "completed", 0.5, 20, "s2")])
    rec = ledger.reconcile(str(ev / "ledger.csv"), db)
    assert rec["status"] == "MATCH"

    res = reverify.reverify(str(ev))
    assert res["all_ok"] is True
    assert [x["step_id"] for x in res["results"]] == ["step_01", "step_02", "final"]
