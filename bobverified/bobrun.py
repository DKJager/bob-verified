#!/usr/bin/env python3.12
"""IBM Bob task runner. Ported from the runner written on 15 Oct 2026 by the team (not by Bob), original sha256 7638f47e2a7bf9cdfefb7e4d97d2b93c4d2644daf7bda757c9e28605928eecd3."""

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DRY_SUCCESS = json.dumps(
    {
        "type": "result",
        "timestamp": "2026-10-15T12:00:00Z",
        "status": "success",
        "stats": {
            "task_id": "dry-000000",
            "duration_ms": 0,
            "session_costs": 0.0,
            "max_cost": 0.0,
            "tool_calls": 0,
        },
        "last_message": "dry run",
    }
)


def _mask_key(text: str, key: str) -> str:
    if not key:
        return text
    return text.replace(key, "[MASKED_API_KEY]")


def _is_git_repo(path: Path) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def _git_diff(path: Path) -> str:
    r = subprocess.run(
        ["git", "-C", str(path), "diff"], capture_output=True, text=True
    )
    return r.stdout if r.returncode == 0 else ""


def _git_status(path: Path) -> str:
    r = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    return r.stdout if r.returncode == 0 else ""


def _git_commit(
    path: Path, message: str, author: str, trailers: list[tuple[str, str]]
) -> str:
    subprocess.run(
        ["git", "-C", str(path), "add", "-A"], capture_output=True, check=True
    )
    r = subprocess.run(
        ["git", "-C", str(path), "diff", "--cached", "--quiet"], capture_output=True
    )
    if r.returncode == 0:
        return ""
    trail_args = [f"{k}: {v}" for k, v in trailers]
    full_message = message + "\n\n" + "\n".join(trail_args)
    subprocess.run(
        ["git", "-C", str(path), "commit", "--author", author, "-m", full_message],
        check=True,
        capture_output=True,
    )
    r = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


def _git_stash_push(path: Path, name: str) -> None:
    r = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if not r.stdout.strip():
        return
    subprocess.run(
        ["git", "-C", str(path), "stash", "push", "--include-untracked", "-m", name],
        capture_output=True,
        check=True,
    )


def _bob_args(bob: str, task: dict, workspace: str, prompt: str) -> list[str]:
    return [
        bob,
        "run",
        "--format",
        "json",
        "--mode",
        task["mode"],
        "--max-cost",
        str(task["max_cost"]),
        "--max-turns",
        str(task["max_turns"]),
        "--workspace",
        workspace,
        "--accept-license",
        "--trust",
        "--disable-mcp",
        prompt,
    ]


def _run_bob(
    bob: str,
    task: dict,
    workspace: str,
    prompt: str,
    api_key: str,
    dry: bool,
) -> tuple[str, str, int]:
    if dry:
        return DRY_SUCCESS, "", 0
    env = {**os.environ, "BOB_API_KEY": api_key}
    args = _bob_args(bob, task, workspace, prompt)
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=task["timeout_s"],
            env=env,
        )
    except subprocess.TimeoutExpired:
        return "", "timeout", 124
    return result.stdout, result.stderr, result.returncode


def _run_accept(task: dict, workspace: str) -> tuple[bool, str]:
    accept_pass = True
    lines = []
    for cmd in task.get("accept", []):
        try:
            child_env = {k: v for k, v in os.environ.items() if k != "BOB_API_KEY"}
            ar = subprocess.run(
                cmd,
                shell=True,
                cwd=workspace,
                env=child_env,
                capture_output=True,
                text=True,
                timeout=900,
            )
            lines.append(f"$ {cmd}\n{ar.stdout}{ar.stderr}")
            if ar.returncode != 0:
                accept_pass = False
        except Exception as exc:
            lines.append(f"$ {cmd}\nERROR: {exc}")
            accept_pass = False
    return accept_pass, "\n---\n".join(lines)


def _parse_bob(stdout: str) -> dict:
    """Bob prints one JSON object per line. Use the last "result" object for status and cost;
    if any line is an error event (for example "reached the maximum of N turns"), the attempt is a
    failure but its cost is still the one in the result line."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass
    result, errors = {}, []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "result":
            result = obj
        elif obj.get("type") == "error":
            errors.append(str(obj.get("message", "")))
    if result and errors:
        result = dict(result)
        result["status"] = "error"
        result["errors"] = errors
    return result


def _load_tasks(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_ledger_done(evidence: Path) -> tuple[set[str], float]:
    done: set[str] = set()
    spent = 0.0
    ledger = evidence / "ledger.csv"
    if not ledger.exists():
        return done, spent
    with open(ledger, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") == "done":
                done.add(row.get("id", ""))
            try:
                spent = float(row.get("cumulative_spent", 0.0))
            except ValueError:
                with open(ledger.parent / "errors.log", "a", encoding="utf-8") as ef:
                    ef.write(f"{row.get('id', '-')}\tbad cumulative_spent in ledger: {row.get('cumulative_spent')!r}\n")
    return done, spent


_CSV_FIELDS = [
    "id",
    "attempt",
    "status",
    "bob_task_id",
    "session_costs",
    "cumulative_spent",
    "duration_ms",
    "accept_pass",
    "commit_sha",
]


def _append_ledger(evidence: Path, row: dict) -> None:
    ledger = evidence / "ledger.csv"
    write_header = not ledger.exists()
    with open(ledger, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)


def _append_evidence_md(
    evidence: Path, task: dict, prompt: str, result: dict, commit: str,
    accept_pass: str, files: str
) -> None:
    sha = hashlib.sha256(prompt.encode()).hexdigest()
    btid = result.get("stats", {}).get("task_id", "unknown") if result else "unknown"
    cost = result.get("stats", {}).get("session_costs", 0.0) if result else 0.0
    with open(evidence / "EVIDENCE.md", "a", encoding="utf-8") as f:
        f.write(
            f"\n## {task['id']}\n\n"
            f"- Mode: {task['mode']}\n"
            f"- Prompt SHA256: {sha}\n"
            f"- Prompt:\n\n```\n{prompt}\n```\n\n"
            f"- Bob Task ID: {btid}\n"
            f"- Session Cost: {cost}\n"
            f"- Files Changed: {files or 'no changes'}\n"
            f"- Accept Results: {accept_pass}\n"
            f"- Commit SHA: {commit or 'none'}\n"
        )


def _append_prompts_md(evidence: Path, prompt: str) -> None:
    with open(evidence / "PROMPTS.md", "a", encoding="utf-8") as f:
        f.write(f"\n```\n{prompt}\n```\n")


def _write_summary(
    evidence: Path, done: int, failed: int, spent: float, commits: list[str]
) -> None:
    with open(evidence / "SUMMARY.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "tasks_done": done,
                "tasks_failed": failed,
                "total_spent": spent,
                "commits": commits,
            },
            f,
            indent=2,
        )


def _log_error(evidence: Path, task_id: str, msg: str) -> None:
    err_file = evidence / "errors.log"
    entry = f"[{task_id}] {msg}\n"
    with open(err_file, "a", encoding="utf-8") as f:
        f.write(entry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--bob", default="bob")
    ap.add_argument("--only", default="")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    evidence = Path(args.evidence).resolve()
    api_key = os.environ.get("BOB_API_KEY", "")
    commits: list[str] = []

    if not _is_git_repo(workspace):
        evidence.mkdir(parents=True, exist_ok=True)
        _write_summary(evidence, 0, 0, 0.0, commits)
        return 2

    try:
        evidence.relative_to(workspace / "bob")
    except ValueError:
        try:
            evidence.relative_to(workspace)
            evidence.mkdir(parents=True, exist_ok=True)
            _write_summary(evidence, 0, 0, 0.0, commits)
            return 2
        except ValueError:
            pass
    evidence.mkdir(parents=True, exist_ok=True)

    if not args.dry and not api_key:
        _write_summary(evidence, 0, 0, 0.0, commits)
        return 2

    try:
        config = _load_tasks(args.tasks)
        [(_t["id"], _t["prompt"]) for _t in config["tasks"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _log_error(evidence, "-", f"cannot load tasks file {args.tasks}: {exc}")
        _write_summary(evidence, 0, 0, 0.0, commits)
        return 2
    budget_total = float(config["budget_total"])
    gate_after = int(config["gate_after_task"])
    gate_max_spent = float(config["gate_max_spent"])
    author = config["author"]
    tasks = config["tasks"]
    orig_pos = {t["id"]: i + 1 for i, t in enumerate(config["tasks"])}

    if args.only:
        only_ids = set(args.only.split(","))
        tasks = [t for t in tasks if t["id"] in only_ids]

    cumulative_spent = 0.0
    done_ids: set[str] = set()
    if args.resume:
        done_ids, cumulative_spent = _read_ledger_done(evidence)

    tasks_done = 0
    tasks_failed = 0

    for idx, task in enumerate(tasks):
        tid = task["id"]

        if tid in done_ids:
            tasks_done += 1
            if orig_pos.get(tid) == gate_after and cumulative_spent > gate_max_spent:
                (evidence / "STOP_GATE.md").write_text(
                    f"# Gate Stop\n\nSpent after gate task: {cumulative_spent} > gate max {gate_max_spent}\n"
                )
                _write_summary(evidence, tasks_done, tasks_failed, cumulative_spent, commits)
                return 4
            continue

        if cumulative_spent + task["max_cost"] > budget_total:
            (evidence / "STOP_BUDGET.md").write_text(
                f"# Budget Stop\n\nCumulative spent: {cumulative_spent}\n"
            )
            _write_summary(evidence, tasks_done, tasks_failed, cumulative_spent, commits)
            return 3

        task_ev = evidence / "tasks" / tid
        task_ev.mkdir(parents=True, exist_ok=True)

        base_prompt = task["prompt"]

        final_attempt = 1
        final_status = "fail"
        final_bob_task_id = ""
        final_session_costs = 0.0
        final_accept_pass = False
        final_commit_sha = ""
        final_duration_ms = 0
        final_result: dict = {}
        charged: list[float] = []
        final_accept_text = ""
        final_status_text = ""
        final_prompt_sent = base_prompt

        prompt = base_prompt

        for attempt in (1, 2):
            final_prompt_sent = prompt
            _append_prompts_md(evidence, prompt)
            t0 = time.perf_counter()
            stdout, stderr, rc = _run_bob(
                args.bob, task, str(workspace), prompt, api_key, args.dry
            )
            duration_ms = int((time.perf_counter() - t0) * 1000)
            stderr_masked = _mask_key(stderr, api_key)

            (task_ev / "bob_result.json").write_text(stdout, encoding="utf-8")
            (task_ev / "bob_stderr.txt").write_text(stderr_masked, encoding="utf-8")

            result = _parse_bob(stdout)
            if not result:
                _log_error(evidence, tid, "Unparsable Bob stdout")

            bob_success = bool(result) and result.get("status") == "success" and rc == 0
            bob_task_id = result.get("stats", {}).get("task_id", "")
            session_costs = float(result.get("stats", {}).get("session_costs", 0.0))
            charged.append(session_costs)

            diff = _git_diff(workspace)
            st = _git_status(workspace)
            (task_ev / "diff.patch").write_text(diff, encoding="utf-8")
            (task_ev / "status.txt").write_text(st, encoding="utf-8")

            accept_pass, accept_text = _run_accept(task, str(workspace))
            (task_ev / "accept.txt").write_text(accept_text, encoding="utf-8")

            this_status = "done" if (bob_success and accept_pass) else "fail"

            if this_status == "done":
                first_line = base_prompt.split("\n")[0][:60]
                commit_sha = _git_commit(
                    workspace,
                    f"bob: {tid} {first_line}",
                    author,
                    [("Bob-Task", bob_task_id), ("Bob-Trace", f"tasks/{tid}/bob_result.json")],
                )
                cumulative_spent += sum(charged)
                final_attempt = attempt
                final_status = "done"
                final_bob_task_id = bob_task_id
                final_session_costs = sum(charged)
                final_accept_pass = accept_pass
                final_commit_sha = commit_sha
                final_duration_ms = duration_ms
                final_result = result
                final_accept_text = accept_text
                final_status_text = st
                if commit_sha:
                    commits.append(commit_sha)
                break

            if task.get("retry_on_fail") and attempt == 1:
                parts = []
                if not bob_success:
                    parts.append(
                        f"Bob exit code: {rc}\nStderr: {stderr_masked[-2000:]}"
                    )
                if not accept_pass:
                    parts.append(
                        f"Accept commands failed.\nOutput:\n{accept_text[-2000:]}"
                    )
                failure_text = "\n".join(parts)[-3000:]
                prompt = base_prompt + "\n\nPrevious attempt failed:\n" + failure_text
                continue

            cumulative_spent += sum(charged)
            _git_stash_push(workspace, f"bobrun-failed-{tid}")
            final_attempt = attempt
            final_status = "fail"
            final_bob_task_id = bob_task_id
            final_session_costs = sum(charged)
            final_accept_pass = accept_pass
            final_commit_sha = ""
            final_duration_ms = duration_ms
            final_result = result
            final_accept_text = accept_text
            final_status_text = st
            break

        _append_ledger(
            evidence,
            {
                "id": tid,
                "attempt": str(final_attempt),
                "status": final_status,
                "bob_task_id": final_bob_task_id,
                "session_costs": str(final_session_costs),
                "cumulative_spent": str(cumulative_spent),
                "duration_ms": str(final_duration_ms),
                "accept_pass": "PASS" if final_accept_pass else "FAIL",
                "commit_sha": final_commit_sha,
            },
        )
        _append_evidence_md(
            evidence,
            task,
            final_prompt_sent,
            final_result,
            final_commit_sha,
            "PASS" if final_accept_pass else "FAIL",
            final_status_text,
        )

        if final_status == "done":
            tasks_done += 1
        else:
            tasks_failed += 1

        if orig_pos.get(tid) == gate_after and cumulative_spent > gate_max_spent:
            (evidence / "STOP_GATE.md").write_text(
                f"# Gate Stop\n\nSpent after gate task: {cumulative_spent} > gate max {gate_max_spent}\n"
            )
            _write_summary(evidence, tasks_done, tasks_failed, cumulative_spent, commits)
            return 4

    _write_summary(evidence, tasks_done, tasks_failed, cumulative_spent, commits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
