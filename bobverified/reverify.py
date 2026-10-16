"""bobverified.reverify – re-run the verification pipeline for a finished run.

Re-executes every plan step that has a ``verify`` command against the fetched
target, with no AI model calls, and keeps a timestamped log.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

from bobverified import gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(dt: datetime.datetime | None = None) -> str:
    """Return a UTC ISO-8601 timestamp string: YYYY-MM-DDTHH:MM:SSZ."""
    if dt is None:
        dt = _now_utc()
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_stamp(dt: datetime.datetime | None = None) -> str:
    """Return a timestamp safe for filenames (with microseconds): YYYYMMDDTHHMMSSffffffZ."""
    if dt is None:
        dt = _now_utc()
    return dt.strftime("%Y%m%dT%H%M%S%fZ")


# ---------------------------------------------------------------------------
# reverify
# ---------------------------------------------------------------------------

def reverify(run_dir: str) -> dict:
    """Re-run the verification pipeline for the run stored in *run_dir*.

    Loads ``target.json`` (gate config + workdir) and ``plan.json``, then
    calls :func:`gate.verify_step` for every step with a ``verify`` command
    plus a final whole-target check.  Saves a timestamped JSON record and
    appends to ``reverify.log``.  Returns the result dict.
    """
    target_path = os.path.join(run_dir, "target.json")
    plan_path = os.path.join(run_dir, "plan.json")

    # Load config (raises FileNotFoundError if target.json is missing).
    config = gate.load_config(target_path)

    # gate.load_config strips unknown keys; read workdir from raw JSON.
    with open(target_path, encoding="utf-8") as fh:
        raw_target = json.load(fh)
    workdir = raw_target.get("workdir")
    if not workdir:
        raise ValueError("'workdir' key is required in target.json")

    # Load plan (optional).
    steps: list[dict] = []
    if os.path.exists(plan_path):
        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
        steps = plan.get("steps", [])

    start_dt = _now_utc()
    start_stamp = _stamp(start_dt)

    # Collect (step_id, verify_command) pairs; only steps with a non-empty verify.
    tasks: list[tuple[str, str | None]] = []
    for step in steps:
        verify_cmd = step.get("verify", "")
        if verify_cmd:
            tasks.append((step["id"], verify_cmd))
    # Final whole-target check.
    tasks.append(("final", None))

    log_lines: list[str] = []

    def log(msg: str) -> None:
        log_lines.append(f"{_stamp()} {msg}")

    log(f"start reverify of {len(tasks)} checks")

    results: list[dict] = []
    all_ok = True

    for step_id, verify_cmd in tasks:
        gate_result = gate.verify_step(workdir, config, verify_cmd)
        verdict = gate_result["verdict"]

        failed = [c["name"] for c in gate_result["checks"] if not c["ok"]]
        weak = gate_result["control"].get("weak", [])

        if verdict != "ACCEPT":
            all_ok = False

        # Build log line.
        line = f"{step_id}: {verdict}"
        if failed:
            line += f" failed: {','.join(failed)}"
        if weak:
            line += f" weak: {','.join(weak)}"
        log(line)

        results.append({
            "step_id": step_id,
            "verdict": verdict,
            "failed": failed,
            "weak": weak,
            "utc": gate_result["utc"],
        })

    log(f"done all_ok={all_ok}")

    log_text = "\n".join(log_lines) + "\n"

    result = {
        "utc": start_stamp,
        "all_ok": all_ok,
        "results": results,
        "log": log_text,
    }

    # Save JSON record.
    reverify_dir = os.path.join(run_dir, "reverify")
    os.makedirs(reverify_dir, exist_ok=True)
    record_name = f"{_file_stamp()}.json"
    record_path = os.path.join(reverify_dir, record_name)
    with open(record_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    # Append to reverify.log.
    log_file = os.path.join(run_dir, "reverify.log")
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(log_text + "\n")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``bobverified.reverify`` CLI."""
    parser = argparse.ArgumentParser(prog="bobverified.reverify")
    parser.add_argument("--run", required=True, help="Path to the run directory")
    args = parser.parse_args(argv)

    result = reverify(args.run)
    print(result["log"], end="")
    return 0 if result["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
