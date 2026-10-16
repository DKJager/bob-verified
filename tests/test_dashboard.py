"""Tests for bobverified.dashboard (written by the team; Bob writes the implementation)."""
import csv
import hashlib
import json
import threading
import urllib.error
import urllib.request

import pytest

from bobverified import dashboard

FIELDS = ["id", "attempt", "status", "bob_task_id", "session_costs", "cumulative_spent",
          "duration_ms", "accept_pass", "commit_sha"]
SHA1 = "a" * 40


def make_run(root, weak_step=False):
    root.mkdir(parents=True, exist_ok=True)
    (root / "plan.json").write_text(json.dumps({
        "title": "Demo run <b>",
        "target": {"name": "tinyapp", "url": "https://example.com/tinyapp", "commit": "c0ffee", "license": "MIT"},
        "steps": [
            {"id": "step_01", "title": "Pin dependencies", "verify": "true"},
            {"id": "step_02", "title": "Port to <script>alert(1)</script>", "verify": "false"},
            {"id": "step_03", "title": "Add tests", "verify": "true"},
        ]}))
    with open(root / "ledger.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerow({"id": "step_01", "attempt": "1", "status": "done", "bob_task_id": "bt1",
                    "session_costs": "0.5", "cumulative_spent": "0.5", "accept_pass": "PASS", "commit_sha": SHA1})
        w.writerow({"id": "step_02", "attempt": "2", "status": "fail", "bob_task_id": "bt2",
                    "session_costs": "1.25", "cumulative_spent": "1.75", "accept_pass": "FAIL", "commit_sha": ""})
        w.writerow({"id": "plan", "attempt": "1", "status": "done", "bob_task_id": "bt0",
                    "session_costs": "0.25", "cumulative_spent": "2.0", "accept_pass": "PASS", "commit_sha": "b" * 40})
    (root / "gate").mkdir()
    (root / "gate" / "step_01.json").write_text(json.dumps({
        "verdict": "CHECKS_TOO_WEAK" if weak_step else "ACCEPT", "utc": "2026-10-16T12:00:00Z", "step_command": "true",
        "checks": [{"name": "tests", "ok": True, "detail": "exit 0"}],
        "control": {"ran": True, "checks": [{"name": "tests", "ok": weak_step, "detail": "exit 1"}],
                    "weak": ["tests"] if weak_step else []}}))
    (root / "gate" / "step_02.json").write_text(json.dumps({
        "verdict": "REJECT_CHECKS_FAILED", "utc": "2026-10-16T12:05:00Z", "step_command": "false",
        "checks": [{"name": "step", "ok": False, "detail": "exit 1"}, {"name": "tests", "ok": True, "detail": "exit 0"}],
        "control": {"ran": False, "checks": [], "weak": []}}))
    (root / "reconciliation.json").write_text(json.dumps({
        "status": "MATCH", "ledger_total": 1.75, "db_total": 1.75, "delta": 0.0, "utc": "2026-10-16T12:10:00Z"}))
    (root / "reverify").mkdir()
    (root / "reverify" / "20261001T121500Z.json").write_text(json.dumps({
        "utc": "2026-10-01T12:15:00Z", "all_ok": True, "results": [],
        "log": "2026-10-01T12:15:00Z start reverify of 3 steps\n2026-10-01T12:15:09Z step_01: ACCEPT"}))
    return root


def dir_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_load_run_combines_plan_ledger_and_gate(tmp_path):
    run = dashboard.load_run(str(make_run(tmp_path / "run")))
    assert run["title"] == "Demo run <b>"
    assert run["target"]["license"] == "MIT"
    steps = {s["id"]: s for s in run["steps"]}
    assert list(steps) == ["step_01", "step_02", "step_03"]
    assert steps["step_01"]["status"] == "done"
    assert steps["step_01"]["cost"] == pytest.approx(0.5)
    assert steps["step_01"]["commit_sha"] == SHA1
    assert steps["step_01"]["gate_verdict"] == "ACCEPT"
    assert steps["step_01"]["control_weak"] == []
    assert steps["step_02"]["status"] == "fail"
    assert steps["step_02"]["attempt"] == 2
    assert steps["step_02"]["gate_verdict"] == "REJECT_CHECKS_FAILED"
    assert steps["step_02"]["gate_failed"] == ["step"]
    assert steps["step_03"]["status"] == "not_run"
    assert steps["step_03"]["gate_verdict"] is None
    assert steps["step_03"]["cost"] == 0.0
    assert run["total_cost"] == pytest.approx(2.0)  # includes the planning task, which is not a plan step
    assert run["commits"] == [SHA1]
    assert run["reconciliation"]["status"] == "MATCH"
    assert run["last_reverify"]["utc"] == "2026-10-01T12:15:00Z"


def test_load_run_empty_directory_is_safe(tmp_path):
    (tmp_path / "empty").mkdir()
    run = dashboard.load_run(str(tmp_path / "empty"))
    assert run["steps"] == [] and run["total_cost"] == 0.0
    assert run["reconciliation"] is None and run["last_reverify"] is None


def test_render_html_shows_the_evidence_and_escapes(tmp_path):
    html = dashboard.render_html(dashboard.load_run(str(make_run(tmp_path / "run"))))
    for needle in ["step_01", "step_02", "step_03", "ACCEPT", "REJECT_CHECKS_FAILED", "MATCH",
                   "2.00", "credits", "MIT", "https://example.com/tinyapp", "c0ffee", "aaaaaaa",
                   "2026-10-01T12:15:00Z", "step_01: ACCEPT", "negative control"]:
        assert needle in html, needle
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;" in html
    assert "$2.00" not in html
    assert 'action="/reverify"' in html and 'method="post"' in html.lower()


def test_render_html_flags_weak_controls(tmp_path):
    html = dashboard.render_html(dashboard.load_run(str(make_run(tmp_path / "run", weak_step=True))))
    assert "CHECKS_TOO_WEAK" in html


@pytest.fixture
def server(tmp_path):
    run_dir = make_run(tmp_path / "run")
    calls = []

    def fake_reverify(path):
        calls.append(path)
        return {"utc": "2026-10-16T13:00:00Z", "all_ok": True, "results": [],
                "log": "2026-10-16T13:00:00Z FAKE-REVERIFY-LOG"}

    srv = dashboard.make_server(str(run_dir), "127.0.0.1", 0, reverify_fn=fake_reverify)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base, run_dir, calls
    srv.shutdown()
    srv.server_close()


def test_server_get_pages_are_read_only(server):
    base, run_dir, calls = server
    before = dir_hash(run_dir)
    with urllib.request.urlopen(base + "/") as r:
        assert r.status == 200 and "text/html" in r.headers["Content-Type"]
        assert "step_01" in r.read().decode()
    with urllib.request.urlopen(base + "/api/run") as r:
        data = json.loads(r.read())
        assert data["total_cost"] == pytest.approx(2.0)
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/nope")
    assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/../../etc/passwd")
    assert e.value.code == 404
    assert dir_hash(run_dir) == before
    assert calls == []


def test_server_post_reverify_runs_function_and_shows_log(server):
    base, run_dir, calls = server
    req = urllib.request.Request(base + "/reverify", data=b"", method="POST")
    with urllib.request.urlopen(req) as r:  # follows the 303 back to /
        body = r.read().decode()
    assert calls == [str(run_dir)]
    assert "FAKE-REVERIFY-LOG" in body
    assert len(list((run_dir / "reverify").glob("*.json"))) == 2  # the handler saved the new record


def test_server_post_reverify_survives_errors(tmp_path):
    run_dir = make_run(tmp_path / "run")

    def boom(path):
        raise RuntimeError("target missing")

    srv = dashboard.make_server(str(run_dir), "127.0.0.1", 0, reverify_fn=boom)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with urllib.request.urlopen(urllib.request.Request(base + "/reverify", data=b"", method="POST")) as r:
            body = r.read().decode()
        assert "target missing" in body
    finally:
        srv.shutdown()
        srv.server_close()


def test_server_rejects_other_methods(server):
    base, _, _ = server
    req = urllib.request.Request(base + "/", data=b"x", method="PUT")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 405


# ---- re-verify as a stopped-on-timeout subprocess ----

import json as _json
import os
import sys
import time


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_run_reverify_subprocess_returns_the_saved_record(tmp_path):
    run_dir = make_run(tmp_path / "run")
    script = (
        "import json,sys,pathlib\n"
        "d=pathlib.Path(sys.argv[1])/'reverify'; d.mkdir(exist_ok=True)\n"
        "(d/'99999999T000000000000Z.json').write_text(json.dumps({'utc':'2026-10-16T20:00:00Z','all_ok':True,'results':[],'log':'2026-10-16T20:00:00Z fake run'}))\n"
    )
    res = dashboard.run_reverify_subprocess(str(run_dir), timeout_s=20,
                                            command=[sys.executable, "-c", script, str(run_dir)])
    assert res["all_ok"] is True and "fake run" in res["log"]


def test_run_reverify_subprocess_kills_the_whole_process_tree_on_timeout(tmp_path):
    run_dir = make_run(tmp_path / "run")
    pidfile = tmp_path / "grandchild.pid"
    script = (
        "import subprocess,sys,time\n"
        f"p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)'],start_new_session=True)\n"
        f"open({str(pidfile)!r},'w').write(str(p.pid))\n"
        "time.sleep(300)\n"
    )
    t0 = time.time()
    res = dashboard.run_reverify_subprocess(str(run_dir), timeout_s=2, command=[sys.executable, "-c", script])
    assert time.time() - t0 < 15
    assert res["all_ok"] is False
    assert "exceeded" in res["log"] and "2" in res["log"]
    gc = int(pidfile.read_text())
    for _ in range(30):
        if not pid_alive(gc):
            break
        time.sleep(0.1)
    assert not pid_alive(gc), "grandchild survived the timeout"


def test_run_reverify_subprocess_reports_a_crash(tmp_path):
    run_dir = make_run(tmp_path / "run")
    res = dashboard.run_reverify_subprocess(str(run_dir), timeout_s=20,
                                            command=[sys.executable, "-c", "import sys;print('boom detail');sys.exit(3)"])
    assert res["all_ok"] is False
    assert "boom detail" in res["log"]


def test_server_default_reverify_uses_the_timeout(tmp_path, monkeypatch):
    run_dir = make_run(tmp_path / "run")
    seen = {}

    def fake(run, timeout_s=None, **kw):
        seen["t"] = timeout_s
        return {"utc": "2026-10-16T13:00:00Z", "all_ok": True, "results": [], "log": "2026-10-16T13:00:00Z DEFAULT-PATH"}

    monkeypatch.setattr(dashboard, "run_reverify_subprocess", fake)
    srv = dashboard.make_server(str(run_dir), "127.0.0.1", 0, reverify_timeout_s=77)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with urllib.request.urlopen(urllib.request.Request(base + "/reverify", data=b"", method="POST")) as r:
            assert "DEFAULT-PATH" in r.read().decode()
        assert seen["t"] == 77
    finally:
        srv.shutdown()
        srv.server_close()
