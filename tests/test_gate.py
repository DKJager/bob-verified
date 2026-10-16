"""Tests for bobverified.gate (written by the team; Bob writes the implementation)."""
import hashlib
import json
import socket
import subprocess
import sys
import textwrap

import pytest

from bobverified import gate


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_app(root, bug=False):
    """A tiny app: lib.add, a server answering 200 on / and 404 elsewhere, and a test file."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "lib.py").write_text(
        "def add(a, b):\n    return a - b\n" if bug else "def add(a, b):\n    return a + b\n"
    )
    (root / "server.py").write_text(
        textwrap.dedent(
            """
            import sys
            from http.server import BaseHTTPRequestHandler, HTTPServer
            import lib

            class H(BaseHTTPRequestHandler):
                def do_GET(self):
                    code = 200 if self.path == "/" else 404
                    self.send_response(code)
                    self.end_headers()
                    self.wfile.write(b"ok")
                def log_message(self, *a):
                    pass

            HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
            """
        )
    )
    (root / "test_lib.py").write_text(
        "import lib\n\ndef test_add():\n    assert lib.add(2, 3) == 5\n"
    )
    return root


def make_config(port, **over):
    cfg = {
        "test_command": f"{sys.executable} -m pytest -q test_lib.py",
        "start_command": f"{sys.executable} server.py {port}",
        "urls": [f"http://127.0.0.1:{port}/"],
        "start_wait_s": 8,
    }
    cfg.update(over)
    return cfg


def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def by_name(checks):
    return {c["name"]: c for c in checks}


# ---- config ----

def test_load_config_defaults(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"test_command": "true"}))
    cfg = gate.load_config(str(f))
    assert cfg["test_command"] == "true"
    assert cfg["urls"] == []
    assert cfg["start_command"] is None
    assert cfg["break_command"] is None
    assert cfg["control_exempt"] == []
    assert cfg["start_wait_s"] > 0


def test_load_config_requires_test_command(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"urls": []}))
    with pytest.raises(ValueError):
        gate.load_config(str(f))


def test_load_config_urls_need_start_command(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"test_command": "true", "urls": ["http://127.0.0.1:1/"]}))
    with pytest.raises(ValueError):
        gate.load_config(str(f))


# ---- run_checks ----

def test_run_checks_all_pass(tmp_path):
    app = make_app(tmp_path / "app")
    port = free_port()
    cfg = make_config(port)
    checks = gate.run_checks(str(app), cfg, step_command=f"{sys.executable} -c 'import lib'")
    named = by_name(checks)
    assert named["step"]["ok"] is True
    assert named["tests"]["ok"] is True
    assert named["start"]["ok"] is True
    assert named[f"url:http://127.0.0.1:{port}/"]["ok"] is True
    assert all(set(c) >= {"name", "ok", "detail"} for c in checks)


def test_run_checks_step_failure_is_reported(tmp_path):
    app = make_app(tmp_path / "app")
    cfg = {"test_command": "true"}
    cfg = {"test_command": "true", "start_command": None, "urls": [], "start_wait_s": 2,
           "break_command": None, "control_exempt": []}
    checks = gate.run_checks(str(app), cfg, step_command="false")
    assert by_name(checks)["step"]["ok"] is False
    assert by_name(checks)["tests"]["ok"] is True


def test_run_checks_bad_url_status_fails(tmp_path):
    app = make_app(tmp_path / "app")
    port = free_port()
    cfg = make_config(port, urls=[f"http://127.0.0.1:{port}/missing"], start_wait_s=4)
    checks = gate.run_checks(str(app), cfg, step_command=None)
    named = by_name(checks)
    assert "step" not in named
    assert named[f"url:http://127.0.0.1:{port}/missing"]["ok"] is False


def test_run_checks_failing_tests_detected(tmp_path):
    app = make_app(tmp_path / "app", bug=True)
    cfg = make_config(free_port())
    checks = gate.run_checks(str(app), cfg, step_command=None)
    assert by_name(checks)["tests"]["ok"] is False


def test_run_checks_does_not_leak_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("BOB_API_KEY", "fake-key-do-not-leak")
    app = make_app(tmp_path / "app")
    cfg = {"test_command": "true", "start_command": None, "urls": [], "start_wait_s": 2,
           "break_command": None, "control_exempt": []}
    checks = gate.run_checks(str(app), cfg, step_command='test -z "$BOB_API_KEY"')
    assert by_name(checks)["step"]["ok"] is True


# ---- verify_step ----

def test_verify_accepts_working_step_with_strong_checks(tmp_path):
    app = make_app(tmp_path / "app")
    before = tree_hash(app)
    cfg = make_config(free_port())
    res = gate.verify_step(str(app), cfg, f"{sys.executable} -m pytest -q test_lib.py")
    assert res["verdict"] == "ACCEPT"
    assert res["control"]["ran"] is True
    assert res["control"]["weak"] == []
    assert all(c["ok"] for c in res["checks"])
    assert not any(c["ok"] for c in res["control"]["checks"])
    assert "utc" in res and "step_command" in res
    assert tree_hash(app) == before  # the real tree is never modified by the control


def test_verify_rejects_step_that_claims_success_without_working(tmp_path):
    """NEGATIVE TEST: the step 'finished' but the code is broken. The gate must refuse it."""
    app = make_app(tmp_path / "app", bug=True)
    cfg = make_config(free_port())
    res = gate.verify_step(str(app), cfg, f"{sys.executable} -m pytest -q test_lib.py")
    assert res["verdict"] == "REJECT_CHECKS_FAILED"
    failed = [c["name"] for c in res["checks"] if not c["ok"]]
    assert "tests" in failed and "step" in failed
    assert res["control"]["ran"] is False


def test_verify_flags_checks_too_weak(tmp_path):
    """Checks that cannot tell a working tree from a broken one must be refused."""
    app = make_app(tmp_path / "app")
    cfg = {"test_command": "true", "start_command": None, "urls": [], "start_wait_s": 2,
           "break_command": None, "control_exempt": []}
    res = gate.verify_step(str(app), cfg, "true")
    assert res["verdict"] == "CHECKS_TOO_WEAK"
    assert set(res["control"]["weak"]) == {"step", "tests"}


def test_verify_uses_custom_break_command(tmp_path):
    app = make_app(tmp_path / "app")
    cfg = {"test_command": "test -f marker.txt", "start_command": None, "urls": [],
           "start_wait_s": 2, "break_command": "rm marker.txt", "control_exempt": []}
    (app / "marker.txt").write_text("x")
    res = gate.verify_step(str(app), cfg, None)
    assert res["verdict"] == "ACCEPT"
    assert (app / "marker.txt").exists()


def test_verify_control_exempt_names_are_not_weak(tmp_path):
    app = make_app(tmp_path / "app")
    cfg = make_config(free_port(), control_exempt=["step"])
    res = gate.verify_step(str(app), cfg, "true")
    assert res["verdict"] == "ACCEPT"


def test_make_broken_copy_skips_git_and_venv(tmp_path):
    app = make_app(tmp_path / "app")
    (app / ".git").mkdir()
    (app / ".git" / "x").write_text("g")
    (app / ".venv").mkdir()
    (app / ".venv" / "y.py").write_text("v")
    dest = tmp_path / "copy"
    gate.make_broken_copy(str(app), str(dest), None)
    assert not (dest / ".git").exists()
    assert not (dest / ".venv").exists()
    assert "deliberate" in (dest / "lib.py").read_text()
    assert (app / "lib.py").read_text().startswith("def add")


# ---- write + CLI ----

def test_write_gate_result(tmp_path):
    res = {"verdict": "ACCEPT", "checks": []}
    p = gate.write_gate_result(str(tmp_path / "ev"), "step_01", res)
    assert p.endswith("gate/step_01.json") or str(p).endswith("gate/step_01.json")
    assert json.loads(open(p).read())["verdict"] == "ACCEPT"


def run_cli(app, cfgfile, ev, step_cmd, step_id="s1"):
    return subprocess.run(
        [sys.executable, "-m", "bobverified.gate", "verify", "--workdir", str(app),
         "--config", str(cfgfile), "--step-cmd", step_cmd, "--evidence", str(ev),
         "--step-id", step_id],
        capture_output=True, text=True,
    )


def test_cli_exit_codes_and_evidence(tmp_path):
    good = make_app(tmp_path / "good")
    bad = make_app(tmp_path / "bad", bug=True)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(make_config(free_port())))
    step = f"{sys.executable} -m pytest -q test_lib.py"
    ev = tmp_path / "ev"
    r = run_cli(good, cfg, ev, step, "ok_step")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((ev / "gate" / "ok_step.json").read_text())["verdict"] == "ACCEPT"
    r = run_cli(bad, cfg, ev, step, "bad_step")
    assert r.returncode == 1
    assert json.loads((ev / "gate" / "bad_step.json").read_text())["verdict"] == "REJECT_CHECKS_FAILED"
    weak = tmp_path / "w.json"
    weak.write_text(json.dumps({"test_command": "true"}))
    r = run_cli(good, weak, ev, "true", "weak_step")
    assert r.returncode == 3
    assert json.loads((ev / "gate" / "weak_step.json").read_text())["verdict"] == "CHECKS_TOO_WEAK"
