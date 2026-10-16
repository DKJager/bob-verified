"""bobverified.gate – quality gate for Bob-verified steps.

Public API
----------
load_config, run_checks, make_broken_copy, verify_step,
write_gate_result, main
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from subprocess import DEVNULL
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COPY_IGNORE = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}


def _build_env(config_env: Optional[dict] = None) -> dict:
    """Build child environment: os.environ minus BOB_API_KEY, with config_env merged on top.

    BOB_API_KEY is removed again after the merge so the config can never restore it.
    """
    env = dict(os.environ)
    env.pop("BOB_API_KEY", None)
    if config_env:
        env.update(config_env)
    env.pop("BOB_API_KEY", None)
    return env


def _run(cmd: str, cwd: str, timeout_s: int, config_env: Optional[dict] = None) -> dict:
    """Run *cmd* with shell=True in *cwd*; return a check dict (name filled by caller)."""
    env = _build_env(config_env)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            env=env,
        )
        combined = result.stdout.decode(errors="replace")
        detail = f"exit {result.returncode}" + combined[-2000:]
        return {"ok": result.returncode == 0, "detail": detail}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "timeout"}


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Read a gate config JSON file and apply defaults.

    Required key: ``test_command`` (non-empty str).
    If ``urls`` is non-empty, ``start_command`` must be set.
    Optional key: ``env`` – dict mapping str keys to str values.
    """
    with open(path, encoding="utf-8") as fh:
        raw: dict = json.load(fh)

    test_command = raw.get("test_command")
    if not test_command or not isinstance(test_command, str):
        raise ValueError("'test_command' is required and must be a non-empty string")

    env = raw.get("env", {})
    if not isinstance(env, dict):
        raise ValueError("'env' must be a dict")
    for k, v in env.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError("'env' keys and values must all be strings")

    cfg = {
        "test_command": test_command,
        "start_command": raw.get("start_command", None),
        "urls": raw.get("urls", []),
        "start_wait_s": raw.get("start_wait_s", 10),
        "break_command": raw.get("break_command", None),
        "control_exempt": raw.get("control_exempt", []),
        "env": env,
    }

    if cfg["urls"] and not cfg["start_command"]:
        raise ValueError("'start_command' is required when 'urls' is non-empty")

    return cfg


# ---------------------------------------------------------------------------
# run_checks
# ---------------------------------------------------------------------------

def run_checks(
    workdir: str,
    config: dict,
    step_command: Optional[str] = None,
    timeout_s: int = 300,
) -> list[dict]:
    """Execute step, tests, optional server + url checks; return list of check dicts."""
    checks: list[dict] = []

    config_env = config.get("env") or None

    # 1. Optional step check
    if step_command:
        res = _run(step_command, workdir, timeout_s, config_env)
        checks.append({"name": "step", **res})

    # 2. Tests
    res = _run(config["test_command"], workdir, timeout_s, config_env)
    checks.append({"name": "tests", **res})

    # 3. Server + URL checks (only if start_command is set)
    if config.get("start_command"):
        env = _build_env(config_env)
        proc = subprocess.Popen(
            config["start_command"],
            shell=True,
            cwd=workdir,
            stdout=DEVNULL,
            stderr=DEVNULL,
            start_new_session=True,
            env=env,
        )
        pgid = os.getpgid(proc.pid)

        try:
            # "start" check placeholder – inserted before url checks
            start_ok = True  # assume ok; update after polling
            url_checks: list[dict] = []

            urls = config.get("urls", [])
            wait_s = config.get("start_wait_s", 10)

            if not urls:
                time.sleep(1)
            else:
                for url in urls:
                    deadline = time.monotonic() + wait_s
                    url_ok = False
                    url_detail = f"timeout after {wait_s}s"
                    while time.monotonic() < deadline:
                        try:
                            with urllib.request.urlopen(url, timeout=2) as resp:
                                status = resp.status
                                if status == 200:
                                    url_ok = True
                                    url_detail = f"exit 0"
                                    break
                                else:
                                    url_ok = False
                                    url_detail = f"exit {status}"
                                    break  # non-200 is a final failure
                        except urllib.error.HTTPError as exc:
                            url_ok = False
                            url_detail = f"exit {exc.code}"
                            break  # final failure
                        except Exception:
                            # Connection error – not up yet; retry
                            time.sleep(0.2)
                    url_checks.append({"name": f"url:{url}", "ok": url_ok, "detail": url_detail})

            # "start" check: process still running or exited 0
            poll = proc.poll()
            start_ok = poll is None or poll == 0
            start_detail = "exit 0" if poll == 0 else ("exit 0" if poll is None else f"exit {poll}")
            checks.append({"name": "start", "ok": start_ok, "detail": start_detail})
            checks.extend(url_checks)

        finally:
            # Stop the server
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()

    return checks


# ---------------------------------------------------------------------------
# make_broken_copy
# ---------------------------------------------------------------------------

def make_broken_copy(
    workdir: str,
    dest: str,
    break_command: Optional[str],
    env: Optional[dict] = None,
) -> None:
    """Copy *workdir* to *dest*, then break it.

    Excludes: .git, .venv, venv, __pycache__, .pytest_cache, node_modules.
    If *break_command* is provided, run it in *dest*; otherwise replace every
    *.py file with ``raise RuntimeError('deliberate break')``.
    *env* is an optional mapping merged on top of the clean environment (same
    rules as the config ``env`` key – BOB_API_KEY is always stripped).
    """
    shutil.copytree(
        workdir,
        dest,
        ignore=shutil.ignore_patterns(*_COPY_IGNORE),
    )

    if break_command:
        result = subprocess.run(
            break_command, shell=True, cwd=dest, env=_build_env(env)
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"break_command exited with code {result.returncode}"
            )
    else:
        dest_path = __import__("pathlib").Path(dest)
        for py_file in dest_path.rglob("*.py"):
            py_file.write_text("raise RuntimeError('deliberate break')\n")


# ---------------------------------------------------------------------------
# verify_step
# ---------------------------------------------------------------------------

def verify_step(
    workdir: str,
    config: dict,
    step_command: Optional[str],
    scratch_dir: Optional[str] = None,
) -> dict:
    """Run checks on *workdir*; if all pass, run a control check on a broken copy.

    Returns a result dict with keys: verdict, utc, step_command, checks, control.
    """
    utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    checks = run_checks(workdir, config, step_command)

    if any(not c["ok"] for c in checks):
        return {
            "verdict": "REJECT_CHECKS_FAILED",
            "utc": utc,
            "step_command": step_command,
            "checks": checks,
            "control": {"ran": False, "checks": [], "weak": []},
        }

    # Control run on broken copy
    tmp = tempfile.mkdtemp(dir=scratch_dir)
    try:
        broken = os.path.join(tmp, "broken")
        make_broken_copy(workdir, broken, config.get("break_command"), env=config.get("env"))
        control_checks = run_checks(broken, config, step_command)

        exempt = set(config.get("control_exempt", []))
        weak = [c["name"] for c in control_checks if c["ok"] and c["name"] not in exempt]

        verdict = "CHECKS_TOO_WEAK" if weak else "ACCEPT"
        return {
            "verdict": verdict,
            "utc": utc,
            "step_command": step_command,
            "checks": checks,
            "control": {"ran": True, "checks": control_checks, "weak": weak},
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# write_gate_result
# ---------------------------------------------------------------------------

def write_gate_result(evidence_dir: str, step_id: str, result: dict) -> str:
    """Serialise *result* as indented JSON to <evidence_dir>/gate/<step_id>.json."""
    out_dir = os.path.join(evidence_dir, "gate")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{step_id}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    return out_path


# ---------------------------------------------------------------------------
# main / CLI
# ---------------------------------------------------------------------------

_EXIT_ACCEPT = 0
_EXIT_REJECT = 1
_EXIT_WEAK = 3


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``bobverified.gate`` CLI."""
    parser = argparse.ArgumentParser(prog="bobverified.gate")
    sub = parser.add_subparsers(dest="subcommand")

    verify_p = sub.add_parser("verify", help="Verify a step")
    verify_p.add_argument("--workdir", required=True)
    verify_p.add_argument("--config", required=True, dest="config_path")
    verify_p.add_argument("--step-cmd", default="", dest="step_cmd")
    verify_p.add_argument("--evidence", required=True)
    verify_p.add_argument("--step-id", required=True)

    args = parser.parse_args(argv)

    if args.subcommand != "verify":
        parser.print_help()
        return 2

    config = load_config(args.config_path)
    step_command = args.step_cmd if args.step_cmd else None

    result = verify_step(args.workdir, config, step_command)
    write_gate_result(args.evidence, args.step_id, result)

    verdict = result["verdict"]
    print(f"{args.step_id}: {verdict}")
    for c in result["checks"]:
        if not c["ok"]:
            print(f"  failed: {c['name']}")
    for name in result["control"].get("weak", []):
        print(f"  weak: {name}")

    if verdict == "ACCEPT":
        return _EXIT_ACCEPT
    elif verdict == "REJECT_CHECKS_FAILED":
        return _EXIT_REJECT
    else:  # CHECKS_TOO_WEAK
        return _EXIT_WEAK


if __name__ == "__main__":
    sys.exit(main())
