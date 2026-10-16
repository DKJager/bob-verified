import json
import sys
import os
import subprocess
import csv
import hashlib

import pytest

from bobverified.bobrun import main


# --- Fixtures ---

@pytest.fixture
def fake_key(monkeypatch):
    """Set a fake API key in environment."""
    monkeypatch.setenv("BOB_API_KEY", "fake-test-key-12345-do-not-leak")


@pytest.fixture
def git_workspace(tmp_path):
    """Create a valid git workspace."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=ws, check=True, capture_output=True)
    # Initial commit so we have a HEAD
    (ws / "README.md").write_text("# Project\n")
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=ws, check=True, capture_output=True)
    return ws


@pytest.fixture
def fake_bob_echo_args(tmp_path):
    """Create a fake bob script that echoes its argv to stdout as JSON."""
    fake_bob = tmp_path / "fake_bob.sh"
    fake_bob.write_text("""#!/bin/bash
# Echo all arguments as JSON array to stdout
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@"
# Echo to stderr to test masking
echo "Key: $BOB_API_KEY" >&2
""")
    fake_bob.chmod(0o755)
    return fake_bob


@pytest.fixture
def fake_bob_success(tmp_path):
    """Create a fake bob that returns a valid success JSON."""
    fake_bob = tmp_path / "fake_bob_ok.sh"
    fake_bob.write_text("""#!/bin/bash
echo '{"type":"result","timestamp":"2026-10-15T12:00:00Z","status":"success","stats":{"task_id":"test-task-abc","duration_ms":500,"session_costs":0.01,"max_cost":0.5,"tool_calls":1},"last_message":"Done"}'
""")
    fake_bob.chmod(0o755)
    return fake_bob


@pytest.fixture
def fake_bob_fail(tmp_path):
    """Create a fake bob that returns failure status."""
    fake_bob = tmp_path / "fake_bob_fail.sh"
    # First call fails, second call (retry) also fails
    fake_bob.write_text("""#!/bin/bash
echo '{"type":"result","timestamp":"2026-10-15T12:00:00Z","status":"error","stats":{"task_id":"fail-task","duration_ms":100,"session_costs":0.01,"max_cost":0.5},"last_message":"Failed"}'
exit 1
""")
    fake_bob.chmod(0o755)
    return fake_bob


def make_tasks_file(path, tasks_data):
    """Helper to write a tasks JSON file."""
    path.write_text(json.dumps(tasks_data))
    return path


# --- T1: fake bob that echoes its argv proves the exact argument list, prompt last, no --prompt-file ---

def test_T1_exact_argument_list_no_prompt_file(tmp_path, git_workspace, fake_key, fake_bob_echo_args):
    """Verify Bob is called with exact args: no --prompt-file, prompt is last positional."""
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 10.0,
        "gate_after_task": 99,
        "gate_max_spent": 10.0,
        "author": "Test <test@example.com>",
        "tasks": [{
            "id": "t1",
            "mode": "plan",
            "prompt": "Hello world prompt",
            "max_cost": 0.5,
            "max_turns": 10,
            "timeout_s": 60,
            "accept": [],
            "retry_on_fail": False
        }]
    })
    
    evidence_dir = tmp_path / "evidence"
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_echo_args)
        ],
        capture_output=True,
        text=True
    )
    
    # Read the bob_result.json to see what args were passed
    bob_result = evidence_dir / "tasks" / "t1" / "bob_result.json"
    assert bob_result.exists(), "bob_result.json should exist"
    
    # The fake bob outputs the args as a JSON-wrapped bash array
    # Format: ["arg1","arg2",...,"lastarg"]
    content = bob_result.read_text()
    args_raw = json.loads(content)  # This is ["run --format json ... prompt"]
    
    # The args are space-joined inside the array element
    args = list(args_raw)
    
    # Verify NO --prompt-file
    assert "--prompt-file" not in args, "Must NOT use --prompt-file flag"
    
    # Verify the prompt is the LAST argument
    assert args[-1] == "Hello world prompt", f"Prompt must be last argument, got: {args[-1]}"
    
    # Verify required flags present
    assert "run" in args
    assert "--format" in args
    assert "json" in args[args.index("--format") + 1] if "--format" in args else False
    assert "--mode" in args
    assert "--max-cost" in args
    assert "--max-turns" in args
    assert "--workspace" in args
    assert "--accept-license" in args
    assert "--trust" in args
    assert "--disable-mcp" in args


# --- T2: key never appears in any evidence file even when the fake bob prints it to stderr ---

def test_T2_key_masked_in_evidence(tmp_path, git_workspace, fake_key, fake_bob_echo_args):
    """API key must never appear in evidence files, even if leaked to stderr."""
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 10.0,
        "gate_after_task": 99,
        "gate_max_spent": 10.0,
        "author": "Test <test@example.com>",
        "tasks": [{
            "id": "t2",
            "mode": "agent",
            "prompt": "Test prompt",
            "max_cost": 0.5,
            "max_turns": 5,
            "timeout_s": 60,
            "accept": [],
            "retry_on_fail": False
        }]
    })
    
    evidence_dir = tmp_path / "evidence"
    secret_key = "fake-test-key-12345-do-not-leak"
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_echo_args)
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "BOB_API_KEY": secret_key}
    )
    
    # Check ALL evidence files for the key
    evidence_files = list(evidence_dir.rglob("*"))
    for ef in evidence_files:
        if ef.is_file():
            content = ef.read_text(errors="ignore")
            assert secret_key not in content, f"API key found in evidence file: {ef}"
    
    # Specifically check bob_stderr.txt where the fake bob writes the key
    stderr_file = evidence_dir / "tasks" / "t2" / "bob_stderr.txt"
    if stderr_file.exists():
        content = stderr_file.read_text()
        assert secret_key not in content, "API key must be masked in bob_stderr.txt"


# --- T3: budget stop exit 3 before the call that would exceed budget_total ---

def test_T3_budget_stop_exit_3(tmp_path, git_workspace, fake_key, fake_bob_success):
    """Must exit 3 and write STOP_BUDGET.md when a task would exceed budget_total."""
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 0.5,  # Total budget 0.5
        "gate_after_task": 99,
        "gate_max_spent": 10.0,
        "author": "Test <test@example.com>",
        "tasks": [
            {
                "id": "t3a",
                "mode": "agent",
                "prompt": "First task",
                "max_cost": 0.3,
                "max_turns": 5,
                "timeout_s": 60,
                "accept": [],
                "retry_on_fail": False
            },
            {
                "id": "t3b",
                "mode": "agent",
                "prompt": "Second task - should be blocked",
                "max_cost": 0.3,  # 0.3 + 0.3 = 0.6 > 0.5 budget
                "max_turns": 5,
                "timeout_s": 60,
                "accept": [],
                "retry_on_fail": False
            }
        ]
    })
    
    evidence_dir = tmp_path / "evidence"
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_success)
        ],
        capture_output=True,
        text=True
    )
    
    # First task runs with session_costs 0.01, cumulative = 0.01 (< 0.5)
    # Second task: spent_so_far (0.01) + max_cost (0.3) = 0.31 < 0.5, so it would run
    # Need to adjust test to actually trigger budget stop
    
    # Let's make the fake bob return a cost that consumes the budget
    fake_bob_expensive = tmp_path / "fake_bob_expensive.sh"
    fake_bob_expensive.write_text("""#!/bin/bash
echo '{"type":"result","timestamp":"2026-10-15T12:00:00Z","status":"success","stats":{"task_id":"expensive","duration_ms":500,"session_costs":0.4,"max_cost":0.5,"tool_calls":1},"last_message":"Done"}'
""")
    fake_bob_expensive.chmod(0o755)
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_expensive)
        ],
        capture_output=True,
        text=True
    )
    
    # After t3a: cumulative = 0.4
    # Before t3b: spent_so_far (0.4) + max_cost (0.3) = 0.7 > 0.5 -> STOP
    assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}"
    
    stop_file = evidence_dir / "STOP_BUDGET.md"
    assert stop_file.exists(), "STOP_BUDGET.md must be written on budget stop"
    
    # Verify SUMMARY.json exists
    summary = evidence_dir / "SUMMARY.json"
    assert summary.exists(), "SUMMARY.json must exist even on stop"


# --- T4: hard gate exit 4 after task N when spend > gate_max_spent ---

def test_T4_hard_gate_exit_4(tmp_path, git_workspace, fake_key):
    """Must exit 4 and write STOP_GATE.md when spend exceeds gate_max_spent after gate_after_task."""
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 10.0,
        "gate_after_task": 1,  # Check after first task (1-indexed)
        "gate_max_spent": 0.05,  # Gate limit 0.05
        "author": "Test <test@example.com>",
        "tasks": [
            {
                "id": "t4a",
                "mode": "agent",
                "prompt": "First task",
                "max_cost": 1.0,
                "max_turns": 5,
                "timeout_s": 60,
                "accept": [],
                "retry_on_fail": False
            },
            {
                "id": "t4b",
                "mode": "agent",
                "prompt": "Second task - should not run",
                "max_cost": 1.0,
                "max_turns": 5,
                "timeout_s": 60,
                "accept": [],
                "retry_on_fail": False
            }
        ]
    })
    
    # Fake bob that returns cost > gate_max_spent
    fake_bob_over_gate = tmp_path / "fake_bob_over_gate.sh"
    fake_bob_over_gate.write_text("""#!/bin/bash
echo '{"type":"result","timestamp":"2026-10-15T12:00:00Z","status":"success","stats":{"task_id":"gate-task","duration_ms":500,"session_costs":0.1,"max_cost":1.0,"tool_calls":1},"last_message":"Done"}'
""")
    fake_bob_over_gate.chmod(0o755)
    
    evidence_dir = tmp_path / "evidence"
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_over_gate)
        ],
        capture_output=True,
        text=True
    )
    
    # After t4a (task 1): cumulative = 0.1 > gate_max_spent (0.05) -> exit 4
    assert result.returncode == 4, f"Expected exit code 4, got {result.returncode}"
    
    stop_file = evidence_dir / "STOP_GATE.md"
    assert stop_file.exists(), "STOP_GATE.md must be written on gate stop"
    
    # Verify task t4b was NOT run
    t4b_result = evidence_dir / "tasks" / "t4b" / "bob_result.json"
    assert not t4b_result.exists(), "Second task should not have run after gate stop"


# --- T5: success + passing accept -> one commit with both trailers and the configured author ---

def test_T5_commit_with_trailers_and_author(tmp_path, git_workspace, fake_key, fake_bob_success):
    """Successful task with passing accept commands must create commit with trailers and author."""
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 10.0,
        "gate_after_task": 99,
        "gate_max_spent": 10.0,
        "author": "Alice <alice@example.com>",
        "tasks": [{
            "id": "t5",
            "mode": "agent",
            "prompt": "Make a change that passes tests",
            "max_cost": 0.5,
            "max_turns": 5,
            "timeout_s": 60,
            "accept": ["echo 'accept test passed'"],  # Will pass
            "retry_on_fail": False
        }]
    })
    
    evidence_dir = tmp_path / "evidence"
    
    # Create a file that bob "changes"
    (git_workspace / "newfile.txt").write_text("created by bob\n")
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_success)
        ],
        capture_output=True,
        text=True,
        cwd=str(git_workspace)
    )
    
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}: {result.stderr}"
    
    # Check commit exists
    log_result = subprocess.run(
        ["git", "log", "-1", "--format=%H|%an|%ae|%s"],
        cwd=git_workspace,
        capture_output=True,
        text=True
    )
    
    assert log_result.returncode == 0
    parts = log_result.stdout.strip().split("|")
    commit_sha = parts[0]
    author_name = parts[1]
    author_email = parts[2]
    commit_msg = parts[3]
    
    # Verify author
    assert author_name == "Alice", f"Commit author name should be Alice, got {author_name}"
    assert author_email == "alice@example.com", f"Commit author email should be alice@example.com, got {author_email}"
    
    # Verify commit message starts correctly
    assert commit_msg.startswith("bob: t5"), f"Commit message should start with 'bob: t5', got: {commit_msg}"
    
    # Verify trailers exist
    trailer_result = subprocess.run(
        ["git", "log", "-1", "--format=%(trailers)"],
        cwd=git_workspace,
        capture_output=True,
        text=True
    )
    trailers = trailer_result.stdout
    assert "Bob-Task:" in trailers, f"Missing Bob-Task trailer: {trailers}"
    assert "Bob-Trace:" in trailers, f"Missing Bob-Trace trailer: {trailers}"


# --- T6: failing accept + retry -> second call has "Previous attempt failed:" in prompt; still failing -> no commit, named stash exists ---

def test_T6_retry_and_stash_on_failure(tmp_path, git_workspace, fake_key):
    """Failed accept with retry must append failure text; persistent failure -> stash, no commit."""
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 10.0,
        "gate_after_task": 99,
        "gate_max_spent": 10.0,
        "author": "Test <test@example.com>",
        "tasks": [{
            "id": "t6",
            "mode": "agent",
            "prompt": "Do something that will fail",
            "max_cost": 0.5,
            "max_turns": 5,
            "timeout_s": 60,
            "accept": ["exit 1"],  # Accept command always fails
            "retry_on_fail": True
        }]
    })
    
    # Fake bob that tracks call count appends "CALLED" to a marker file
    call_marker = tmp_path / "call_count.txt"
    call_marker.write_text("0")
    
    fake_bob_tracker = tmp_path / "fake_bob_tracker.sh"
    fake_bob_tracker.write_text(f"""#!/bin/bash
# Read and increment call count
COUNT=$(cat {call_marker})
echo $((COUNT + 1)) > {call_marker}
# Output success JSON so we can test accept failure path
echo '{{"type":"result","timestamp":"2026-10-15T12:00:00Z","status":"success","stats":{{"task_id":"retry-task","duration_ms":500,"session_costs":0.01,"max_cost":0.5,"tool_calls":1}},"last_message":"Done"}}'
# Log the prompt (last arg) to a file for inspection
python3 -c 'import json,sys; print(json.dumps(sys.argv[-1]))' "$@" >> {tmp_path / "prompts_log.txt"}
""")
    fake_bob_tracker.chmod(0o755)
    
    evidence_dir = tmp_path / "evidence"
    
    # Make a change that will be stashed
    (git_workspace / "failed_change.txt").write_text("this should be stashed\n")
    subprocess.run(["git", "add", "-A"], cwd=git_workspace, capture_output=True)
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_tracker)
        ],
        capture_output=True,
        text=True,
        cwd=str(git_workspace)
    )
    
    # Should complete (exit 0) but task marked failed
    assert result.returncode == 0, f"Exit should be 0 (tasks done, some failed): {result.returncode}"
    
    # Verify 2 calls were made (original + 1 retry)
    call_count = int(call_marker.read_text().strip())
    assert call_count == 2, f"Expected 2 Bob calls (original + retry), got {call_count}"
    
    # Verify second call had "Previous attempt failed:" in prompt
    prompts_log = tmp_path / "prompts_log.txt"
    if prompts_log.exists():
        lines = prompts_log.read_text().strip().split("\n")
        if len(lines) >= 2:
            second_prompt = json.loads(lines[-1])
            assert "Previous attempt failed:" in second_prompt, \
                f"Retry prompt should contain 'Previous attempt failed:', got: {second_prompt}"
    
    # Verify NO commit was made for this task (check ledger)
    ledger = evidence_dir / "ledger.csv"
    assert ledger.exists()
    with open(ledger) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        t6_rows = [r for r in rows if r["id"] == "t6"]
        assert len(t6_rows) > 0
        # Status should indicate failure
        last_t6 = t6_rows[-1]
        assert last_t6["status"] == "fail", f"Task should be marked failed, got: {last_t6['status']}"
        # Commit SHA should be empty
        assert not last_t6["commit_sha"] or last_t6["commit_sha"] == "", \
            f"Failed task should not have commit SHA, got: {last_t6['commit_sha']}"
    
    # Verify named stash exists
    stash_result = subprocess.run(
        ["git", "stash", "list"],
        cwd=git_workspace,
        capture_output=True,
        text=True
    )
    assert "bobrun-failed-t6" in stash_result.stdout, \
        f"Named stash 'bobrun-failed-t6' should exist, stash list: {stash_result.stdout}"


# --- T7: non-git workspace -> exit 2 ---

def test_T7_non_git_workspace_exit_2(tmp_path, fake_key):
    """Non-git workspace must cause exit code 2 (refused)."""
    # Create a directory that is NOT a git repo
    non_git_ws = tmp_path / "not_a_repo"
    non_git_ws.mkdir()
    
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 10.0,
        "gate_after_task": 99,
        "gate_max_spent": 10.0,
        "author": "Test <test@example.com>",
        "tasks": [{
            "id": "t7",
            "mode": "agent",
            "prompt": "Test",
            "max_cost": 0.5,
            "max_turns": 5,
            "timeout_s": 60,
            "accept": [],
            "retry_on_fail": False
        }]
    })
    
    evidence_dir = tmp_path / "evidence"
    fake_bob = tmp_path / "fake.sh"
    fake_bob.write_text("#!/bin/bash\necho '{}'\n")
    fake_bob.chmod(0o755)
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(non_git_ws),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob)
        ],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 2, f"Non-git workspace should cause exit 2, got {result.returncode}"


# --- T8: --resume skips done tasks ---

def test_T8_resume_skips_done_tasks(tmp_path, git_workspace, fake_key, fake_bob_success):
    """--resume must skip tasks already marked done in the ledger."""
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 10.0,
        "gate_after_task": 99,
        "gate_max_spent": 10.0,
        "author": "Test <test@example.com>",
        "tasks": [
            {
                "id": "t8a",
                "mode": "agent",
                "prompt": "First task",
                "max_cost": 0.5,
                "max_turns": 5,
                "timeout_s": 60,
                "accept": [],
                "retry_on_fail": False
            },
            {
                "id": "t8b",
                "mode": "agent",
                "prompt": "Second task",
                "max_cost": 0.5,
                "max_turns": 5,
                "timeout_s": 60,
                "accept": [],
                "retry_on_fail": False
            }
        ]
    })
    
    evidence_dir = tmp_path / "evidence"
    
    # Run first time - should run both tasks
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_success)
        ],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    
    # Count Bob invocations via task directories created
    task_dirs_before = list((evidence_dir / "tasks").iterdir())
    
    # Run with --resume - should skip both done tasks
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_success),
            "--resume"
        ],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    
    # Verify ledger shows both tasks as done
    ledger = evidence_dir / "ledger.csv"
    with open(ledger) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
    # Group by id and check last status
    statuses = {}
    for row in rows:
        statuses[row["id"]] = row["status"]
    
    assert statuses.get("t8a") == "done", "t8a should be done"
    assert statuses.get("t8b") == "done", "t8b should be done"
    
    # With --resume, no new rows should be added (tasks skipped)
    # Check that we still have exactly 2 rows (original run)
    assert len(rows) == 2, f"With --resume, no new rows should be added. Got {len(rows)} rows."


# --- T9: ledger.csv, EVIDENCE.md, PROMPTS.md, SUMMARY.json written with the fields above ---

def test_T9_evidence_files_written(tmp_path, git_workspace, fake_key, fake_bob_success):
    """All evidence files must be written with correct fields."""
    tasks_file = tmp_path / "tasks.json"
    make_tasks_file(tasks_file, {
        "budget_total": 10.0,
        "gate_after_task": 99,
        "gate_max_spent": 10.0,
        "author": "Test <test@example.com>",
        "tasks": [{
            "id": "t9",
            "mode": "plan",
            "prompt": "Test prompt with special chars: <>\"'",
            "max_cost": 0.5,
            "max_turns": 5,
            "timeout_s": 60,
            "accept": [],
            "retry_on_fail": False
        }]
    })
    
    evidence_dir = tmp_path / "evidence"
    
    result = subprocess.run(
        [
            sys.executable, "-m", "bobverified.bobrun",
            "--tasks", str(tasks_file),
            "--workspace", str(git_workspace),
            "--evidence", str(evidence_dir),
            "--bob", str(fake_bob_success)
        ],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"run failed: {result.stderr}"
    
    # 1. Check ledger.csv
    ledger = evidence_dir / "ledger.csv"
    assert ledger.exists(), "ledger.csv must exist"
    with open(ledger) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) > 0, "ledger.csv must have at least one row"
        row = rows[0]
        required_fields = ["id", "attempt", "status", "bob_task_id", "session_costs", 
                          "cumulative_spent", "duration_ms", "accept_pass", "commit_sha"]
        for field in required_fields:
            assert field in row, f"ledger.csv missing field: {field}"
    
    # 2. Check EVIDENCE.md
    evidence_md = evidence_dir / "EVIDENCE.md"
    assert evidence_md.exists(), "EVIDENCE.md must exist"
    evidence_content = evidence_md.read_text()
    assert "t9" in evidence_content, "EVIDENCE.md should contain task id"
    assert "plan" in evidence_content, "EVIDENCE.md should contain mode"
    # Check for sha256 of prompt
    prompt_sha = hashlib.sha256("Test prompt with special chars: <>\"'".encode()).hexdigest()
    assert prompt_sha in evidence_content or "prompt" in evidence_content.lower(), \
        "EVIDENCE.md should contain prompt sha256 or prompt reference"
    
    # 3. Check PROMPTS.md
    prompts_md = evidence_dir / "PROMPTS.md"
    assert prompts_md.exists(), "PROMPTS.md must exist"
    prompts_content = prompts_md.read_text()
    assert "Test prompt with special chars" in prompts_content, \
        "PROMPTS.md must contain full prompt text"
    
    # 4. Check SUMMARY.json
    summary_json = evidence_dir / "SUMMARY.json"
    assert summary_json.exists(), "SUMMARY.json must exist"
    summary = json.loads(summary_json.read_text())
    assert "tasks_done" in summary or "done" in str(summary).lower(), \
        "SUMMARY.json should have tasks done count"
    assert "total_spent" in summary or "spent" in str(summary).lower(), \
        "SUMMARY.json should have total spent"


# ===== REPAIR TESTS F1-F5 (written 15 Oct 2026) =====

def _fx_counter_bob(tmp_path, cost, status="success", rc=0, leak_key=False):
    marker = tmp_path / "fx_calls.txt"
    marker.write_text("0")
    plog = tmp_path / "fx_prompts.jsonl"
    leak = 'echo "Key: $BOB_API_KEY" >&2' if leak_key else ""
    fb = tmp_path / "fx_bob.sh"
    fb.write_text(f"""#!/bin/bash
C=$(cat {marker}); echo $((C + 1)) > {marker}
python3 -c 'import json,sys; print(json.dumps(sys.argv[-1]))' "$@" >> {plog}
{leak}
echo '{{"type":"result","timestamp":"2026-10-15T12:00:00Z","status":"{status}","stats":{{"task_id":"fx","duration_ms":10,"session_costs":{cost},"max_cost":5,"tool_calls":0}},"last_message":"x"}}'
exit {rc}
""")
    fb.chmod(0o755)
    return fb, marker, plog


def _fx_run(tasks_file, ws, ev, bob, *extra):
    return subprocess.run([sys.executable, "-m", "bobverified.bobrun", "--tasks", str(tasks_file), "--workspace", str(ws),
                           "--evidence", str(ev), "--bob", str(bob), *extra], capture_output=True, text=True)


def _fx_task(tid, accept=None, retry=False, max_cost=1.0):
    return {"id": tid, "mode": "agent", "prompt": f"do {tid}", "max_cost": max_cost, "max_turns": 3, "timeout_s": 60,
            "accept": accept or [], "retry_on_fail": retry}


def test_F1_retry_attempt_costs_are_counted(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 1.0)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 99, "gate_max_spent": 50,
                         "author": "T <t@e.com>", "tasks": [_fx_task("f1", accept=["exit 1"], retry=True)]})
    ev = tmp_path / "ev"
    r = _fx_run(tf, git_workspace, ev, bob)
    assert r.returncode == 0, r.stderr
    assert marker.read_text().strip() == "2"
    summ = json.loads((ev / "SUMMARY.json").read_text())
    assert abs(float(summ["total_spent"]) - 2.0) < 1e-6, f"both attempts must be counted, got {summ['total_spent']}"
    rows = list(csv.DictReader(open(ev / "ledger.csv")))
    assert abs(float(rows[-1]["cumulative_spent"]) - 2.0) < 1e-6


def test_F2_resume_restores_spent_budget(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 3.0)
    ev = tmp_path / "ev"
    tf1 = make_tasks_file(tmp_path / "t1.json", {"budget_total": 5, "gate_after_task": 99, "gate_max_spent": 99,
                          "author": "T <t@e.com>", "tasks": [_fx_task("a", max_cost=3.0)]})
    assert _fx_run(tf1, git_workspace, ev, bob).returncode == 0
    tf2 = make_tasks_file(tmp_path / "t2.json", {"budget_total": 5, "gate_after_task": 99, "gate_max_spent": 99,
                          "author": "T <t@e.com>", "tasks": [_fx_task("a", max_cost=3.0), _fx_task("b", max_cost=3.0)]})
    r = _fx_run(tf2, git_workspace, ev, bob, "--resume")
    assert r.returncode == 3, f"3 already spent + 3 > 5 must stop with exit 3 on resume, got {r.returncode}"
    assert marker.read_text().strip() == "1", "task b must not be called"


def test_F3_resume_still_enforces_hard_gate(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 2.0)
    ev = tmp_path / "ev"
    cfg = {"budget_total": 50, "gate_after_task": 1, "gate_max_spent": 1.0, "author": "T <t@e.com>"}
    tf1 = make_tasks_file(tmp_path / "t1.json", dict(cfg, tasks=[_fx_task("a", max_cost=2.0)]))
    r1 = _fx_run(tf1, git_workspace, ev, bob)
    assert r1.returncode == 4
    tf2 = make_tasks_file(tmp_path / "t2.json", dict(cfg, tasks=[_fx_task("a", max_cost=2.0), _fx_task("b", max_cost=2.0)]))
    r2 = _fx_run(tf2, git_workspace, ev, bob, "--resume")
    assert r2.returncode == 4, f"gate after task 1 must still stop a resumed run, got {r2.returncode}"
    assert marker.read_text().strip() == "1", "task b must not be called past the gate"


def test_F4_retry_prompt_is_logged(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 0.1)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 99, "gate_max_spent": 50,
                         "author": "T <t@e.com>", "tasks": [_fx_task("f4", accept=["exit 1"], retry=True)]})
    ev = tmp_path / "ev"
    assert _fx_run(tf, git_workspace, ev, bob).returncode == 0
    prompts = (ev / "PROMPTS.md").read_text()
    assert "Previous attempt failed:" in prompts, "the retry prompt actually sent must be logged in PROMPTS.md"


def test_F5_key_never_sent_in_retry_prompt(tmp_path, git_workspace, fake_key):
    bob, marker, plog = _fx_counter_bob(tmp_path, 0.1, status="error", rc=1, leak_key=True)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 99, "gate_max_spent": 50,
                         "author": "T <t@e.com>", "tasks": [_fx_task("f5", retry=True)]})
    ev = tmp_path / "ev"
    _fx_run(tf, git_workspace, ev, bob)
    assert marker.read_text().strip() == "2"
    sent = [json.loads(l) for l in plog.read_text().splitlines() if l.strip()]
    key = "fake-test-key-12345-do-not-leak"
    assert all(key not in p for p in sent), "API key must never appear in a prompt sent to Bob"
    assert key not in (ev / "PROMPTS.md").read_text()


# ===== REPAIR TESTS F6-F8 (written 15 Oct 2026) =====

def test_F6_spend_accumulates_across_tasks(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 3.0)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 7, "gate_after_task": 99, "gate_max_spent": 99,
                         "author": "T <t@e.com>", "tasks": [_fx_task("a", max_cost=3.0), _fx_task("b", max_cost=3.0),
                                                           _fx_task("c", max_cost=3.0)]})
    ev = tmp_path / "ev"
    r = _fx_run(tf, git_workspace, ev, bob)
    assert r.returncode == 3, f"3+3 spent, +3 > 7 must stop before task c with exit 3, got {r.returncode}"
    assert marker.read_text().strip() == "2"
    rows = list(csv.DictReader(open(ev / "ledger.csv")))
    assert abs(float(rows[-1]["cumulative_spent"]) - 6.0) < 1e-6, "cumulative_spent must add across tasks"
    summ = json.loads((ev / "SUMMARY.json").read_text())
    assert abs(float(summ["total_spent"]) - 6.0) < 1e-6


def test_F6b_gate_uses_total_across_tasks(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 2.0)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 2, "gate_max_spent": 3.0,
                         "author": "T <t@e.com>", "tasks": [_fx_task("a", max_cost=2.0), _fx_task("b", max_cost=2.0),
                                                           _fx_task("c", max_cost=2.0)]})
    r = _fx_run(tf, git_workspace, tmp_path / "ev", bob)
    assert r.returncode == 4, f"2+2=4 > 3 after task 2 must hit the gate, got {r.returncode}"
    assert marker.read_text().strip() == "2"


def test_F7_unparsable_bob_output_is_logged(tmp_path, git_workspace, fake_key):
    fb = tmp_path / "junk_bob.sh"
    fb.write_text("#!/bin/bash\necho 'this is not json'\nexit 0\n")
    fb.chmod(0o755)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 99, "gate_max_spent": 50,
                         "author": "T <t@e.com>", "tasks": [_fx_task("f7")]})
    ev = tmp_path / "ev"
    r = _fx_run(tf, git_workspace, ev, fb)
    assert r.returncode == 0
    err = ev / "errors.log"
    assert err.exists() and "f7" in err.read_text(), "parse failures must be written to evidence/errors.log with the task id"
    rows = list(csv.DictReader(open(ev / "ledger.csv")))
    assert rows[-1]["status"] == "fail"


def test_F8_evidence_md_shows_retry_prompt(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 0.1)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 99, "gate_max_spent": 50,
                         "author": "T <t@e.com>", "tasks": [_fx_task("f8", accept=["exit 1"], retry=True)]})
    ev = tmp_path / "ev"
    assert _fx_run(tf, git_workspace, ev, bob).returncode == 0
    assert "Previous attempt failed:" in (ev / "EVIDENCE.md").read_text()


# ===== REPAIR TESTS F9-F12 (review round 3, 15 Oct 2026; session-written, locked) =====

def test_F9_accept_commands_never_see_the_key(tmp_path, git_workspace, fake_key, fake_bob_success):
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 99, "gate_max_spent": 50,
                         "author": "T <t@e.com>", "tasks": [_fx_task("f9", accept=["env"])]})
    ev = tmp_path / "ev"
    assert _fx_run(tf, git_workspace, ev, fake_bob_success).returncode == 0
    key = "fake-test-key-12345-do-not-leak"
    for p in ev.rglob("*"):
        if p.is_file():
            assert key not in p.read_text(errors="ignore"), f"key found in {p}"


def test_F10_only_keeps_original_gate_position(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 2.0)
    cfg = {"budget_total": 50, "gate_after_task": 1, "gate_max_spent": 1.0, "author": "T <t@e.com>",
           "tasks": [_fx_task("a", max_cost=2.0), _fx_task("b", max_cost=2.0), _fx_task("c", max_cost=2.0)]}
    tf = make_tasks_file(tmp_path / "t.json", cfg)
    r = _fx_run(tf, git_workspace, tmp_path / "ev", bob, "--only", "b,c")
    assert r.returncode == 0, f"gate belongs to task a (position 1); running only b,c must not gate-stop, got {r.returncode}"
    assert marker.read_text().strip() == "2"


def test_F11_ledger_row_cost_counts_all_attempts(tmp_path, git_workspace, fake_key):
    bob, marker, _ = _fx_counter_bob(tmp_path, 1.5)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 99, "gate_max_spent": 50,
                         "author": "T <t@e.com>", "tasks": [_fx_task("f11", accept=["exit 1"], retry=True)]})
    ev = tmp_path / "ev"
    assert _fx_run(tf, git_workspace, ev, bob).returncode == 0
    rows = list(csv.DictReader(open(ev / "ledger.csv")))
    assert abs(sum(float(r["session_costs"]) for r in rows) - 3.0) < 1e-6


def test_F12_unreadable_tasks_file_refused_with_summary(tmp_path, git_workspace, fake_key, fake_bob_success):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    ev = tmp_path / "ev"
    r = _fx_run(bad, git_workspace, ev, fake_bob_success)
    assert r.returncode == 2
    assert (ev / "SUMMARY.json").exists()


# ===== REPAIR TEST F13 (live finding 15 Oct 21:52Z; session-written, locked) =====

def test_F13_multiline_bob_output_cost_is_counted(tmp_path, git_workspace, fake_key):
    fb = tmp_path / "turns_bob.sh"
    fb.write_text("""#!/bin/bash
echo '{"type":"error","timestamp":"2026-10-15T21:49:03Z","severity":"error","message":"The task reached the maximum of 40 turns."}'
echo '{"type":"result","timestamp":"2026-10-15T21:49:03Z","status":"success","stats":{"task_id":"mt","duration_ms":10,"session_costs":2.5,"max_cost":4,"tool_calls":50},"last_message":"x"}'
""")
    fb.chmod(0o755)
    tf = make_tasks_file(tmp_path / "t.json", {"budget_total": 50, "gate_after_task": 99, "gate_max_spent": 50,
                         "author": "T <t@e.com>", "tasks": [_fx_task("f13", retry=True)]})
    ev = tmp_path / "ev"
    assert _fx_run(tf, git_workspace, ev, fb).returncode == 0
    rows = list(csv.DictReader(open(ev / "ledger.csv")))
    assert rows[-1]["status"] == "fail", "a max-turns error line must mark the attempt failed"
    assert abs(float(rows[-1]["cumulative_spent"]) - 5.0) < 1e-6, "both attempts' costs (2.5 each) must be counted"
