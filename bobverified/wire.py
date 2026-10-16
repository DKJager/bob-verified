"""bobverified.wire – wire a plan JSON + target config into a bobrun tasks file."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

# Pattern for valid step ids.
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Directory containing this file (bobverified/).
_PKG_DIR = Path(__file__).parent
# Parent of bobverified/ – the default pkg_root (so `import bobverified` works).
_DEFAULT_PKG_ROOT = str(_PKG_DIR.parent)


# ---------------------------------------------------------------------------
# load_plan
# ---------------------------------------------------------------------------

def load_plan(path: str) -> dict:
    """Read and validate a plan JSON file; raise ValueError on invalid content."""
    with open(path, encoding="utf-8") as fh:
        plan: dict = json.load(fh)

    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise ValueError("'steps' must be a non-empty list")

    seen_ids: set[str] = set()
    for i, step in enumerate(steps):
        sid = step.get("id", "")
        if not isinstance(sid, str) or not _ID_RE.match(sid):
            raise ValueError(f"step[{i}] 'id' {sid!r} does not match ^[a-z][a-z0-9_]*$")
        if sid in seen_ids:
            raise ValueError(f"duplicate step id {sid!r}")
        seen_ids.add(sid)

        title = step.get("title", "")
        if not isinstance(title, str) or not title:
            raise ValueError(f"step[{i}] 'title' must be a non-empty string")

        verify = step.get("verify")
        if verify is None:
            raise ValueError(f"step[{i}] missing 'verify'")
        if not isinstance(verify, str) or not verify.strip():
            raise ValueError(f"step[{i}] 'verify' must be a non-empty string after strip()")

        # Ensure missing description becomes "".
        if "description" not in step:
            step["description"] = ""

    return plan


# ---------------------------------------------------------------------------
# step_prompt
# ---------------------------------------------------------------------------

def step_prompt(step: dict, index: int, total: int) -> str:
    """Return the instruction text for Bob for one plan step."""
    lines = [
        f"Implement step {index} of {total} of the modernization plan, and only that step.",
        f"Step id: {step['id']}",
        f"Title: {step['title']}",
        f"Details: {step.get('description', '')}",
        f"Verification command: {step['verify']}",
        "Rules:",
        "- Keep changes scoped to this step.",
        "- Do not undo work from earlier steps.",
        "- Run the verification command from the repository root when done and, "
        "if it fails, fix the problem within this step and run it again.",
        "- Never write secrets or keys into files.",
        "- Do not create files outside the repository.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# build_tasks
# ---------------------------------------------------------------------------

def build_tasks(
    plan: dict,
    target_config_path: str,
    workdir: str,
    evidence_dir: str,
    python: str = sys.executable,
    pkg_root: str | None = None,
    budget_total: float = 20.0,
    max_cost: float = 4.0,
    max_turns: int = 40,
    timeout_s: int = 1800,
    author: str = "Bob verified runner <runner@example.invalid>",
    gate_after_task: int = 0,
    gate_max_spent: float = 1000.0,
    retry_on_fail: bool = False,
) -> dict:
    """Build and return a bobrun tasks dict from a validated plan."""
    if pkg_root is None:
        pkg_root = _DEFAULT_PKG_ROOT

    steps = plan["steps"]
    n = len(steps)
    tasks = []

    for i, step in enumerate(steps, start=1):
        prompt = step_prompt(step, i, n)

        # Build the accept command as a list of tokens, then join with spaces.
        # Using shlex.quote on each token ensures round-trip via shlex.split.
        tokens = [
            "env",
            f"PYTHONPATH={shlex.quote(pkg_root)}",
            shlex.quote(python),
            "-m",
            "bobverified.gate",
            "verify",
            "--workdir",
            shlex.quote(workdir),
            "--config",
            shlex.quote(os.path.join(evidence_dir, "target.json")),
            "--step-cmd",
            shlex.quote(step["verify"]),
            "--evidence",
            shlex.quote(evidence_dir),
            "--step-id",
            shlex.quote(step["id"]),
        ]
        accept_cmd = " ".join(tokens)

        tasks.append({
            "id": step["id"],
            "mode": "agent",
            "prompt": prompt,
            "max_cost": max_cost,
            "max_turns": max_turns,
            "timeout_s": timeout_s,
            "accept": [accept_cmd],
            "retry_on_fail": retry_on_fail,
        })

    return {
        "budget_total": budget_total,
        "gate_after_task": gate_after_task,
        "gate_max_spent": gate_max_spent,
        "author": author,
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# write_run_files
# ---------------------------------------------------------------------------

def write_run_files(
    evidence_dir: str,
    plan: dict,
    target_config_path: str,
    workdir: str,
    env: dict | None = None,
) -> None:
    """Create evidence_dir and write plan.json and target.json into it."""
    os.makedirs(evidence_dir, exist_ok=True)

    with open(target_config_path, encoding="utf-8") as fh:
        target_cfg: dict = json.load(fh)

    # plan.json: plan + "target" summary (four keys, missing become "").
    target_summary = {
        "name": target_cfg.get("name", "") or "",
        "url": target_cfg.get("url", "") or "",
        "commit": target_cfg.get("commit", "") or "",
        "license": target_cfg.get("license", "") or "",
    }
    plan_out = dict(plan)
    plan_out["target"] = target_summary
    plan_path = os.path.join(evidence_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(plan_out, fh, indent=2)

    # target.json: full target config + workdir + merged env.
    target_out = dict(target_cfg)
    target_out["workdir"] = workdir
    merged_env = dict(target_cfg.get("env") or {})
    if env:
        merged_env.update(env)
    target_out["env"] = merged_env
    target_path = os.path.join(evidence_dir, "target.json")
    with open(target_path, "w", encoding="utf-8") as fh:
        json.dump(target_out, fh, indent=2)


# ---------------------------------------------------------------------------
# main / CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m bobverified.wire``."""
    ap = argparse.ArgumentParser(prog="bobverified.wire")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--pkg-root", default=None)
    ap.add_argument("--budget", type=float, default=20.0)
    ap.add_argument("--max-cost", type=float, default=4.0)
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--gate-after", type=int, default=0)
    ap.add_argument("--gate-max-spent", type=float, default=1000.0)
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")

    args = ap.parse_args(argv)

    # Parse --env KEY=VALUE pairs.
    env_dict: dict[str, str] = {}
    for item in args.env:
        if "=" not in item or item.split("=", 1)[0] == "":
            print(f"--env requires KEY=VALUE (got {item!r})", file=sys.stderr)
            return 2
        k, v = item.split("=", 1)
        env_dict[k] = v

    try:
        plan = load_plan(args.plan)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        write_run_files(args.evidence, plan, args.target, args.workdir, env=env_dict or None)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        tasks_dict = build_tasks(
            plan,
            args.target,
            args.workdir,
            args.evidence,
            python=args.python,
            pkg_root=args.pkg_root,
            budget_total=args.budget,
            max_cost=args.max_cost,
            max_turns=args.max_turns,
            gate_after_task=args.gate_after,
            gate_max_spent=args.gate_max_spent,
            retry_on_fail=args.retry,
        )
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(tasks_dict, fh, indent=2)
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    n = len(tasks_dict["tasks"])
    print(f"wrote {args.out}: {n} tasks, budget {args.budget}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
