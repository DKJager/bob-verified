(Two phrases were edited before publication: a directory example in the documentation prompt was removed and the default author address in the wiring prompt was neutralised. Every other word is as sent to the tool.)


```
Create ONE new file: bobverified/gate.py (Python 3.12, standard library only). Make the existing test file tests/test_gate.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_gate.py first; it is the exact contract. Implement these public names:

load_config(path: str) -> dict
  Read a JSON object. Required key "test_command" (non-empty str), else raise ValueError. Defaults: "start_command": None, "urls": [], "start_wait_s": 10, "break_command": None, "control_exempt": []. If "urls" is non-empty and "start_command" is falsy, raise ValueError. Return the dict with defaults filled in.

run_checks(workdir: str, config: dict, step_command: str | None = None, timeout_s: int = 300) -> list[dict]
  Returns a list of {"name": str, "ok": bool, "detail": str}, in this order:
  1. name "step": only if step_command is truthy. Run it with shell=True in workdir. ok means exit code 0.
  2. name "tests": run config["test_command"] the same way.
  3. only if config["start_command"] is set: start it with subprocess.Popen(shell=True, cwd=workdir, stdout/stderr to DEVNULL, start_new_session=True). Then for each url in config["urls"], poll every 0.2 s (urllib.request.urlopen, timeout 2) until a response arrives or config["start_wait_s"] seconds passed since that url's polling began. Connection errors mean "not up yet, retry". A response with status 200 means ok; any other status (urllib raises HTTPError, use its code) is a final failure with no retry. Add one check named "url:<the url>" per url. If there are no urls, just wait 1 second. Then add a check named "start": ok if the process is still running (poll() is None) or exited with code 0. The "start" check goes BEFORE the url checks in the returned list. Always stop the server at the end: os.killpg(pgid, SIGTERM), wait up to 3 s, then SIGKILL.
  Shell commands run with the current environment minus the variable BOB_API_KEY. "detail" is "exit <code>" followed by the last 2000 characters of stdout+stderr; on timeout the check is not ok and detail is "timeout".

make_broken_copy(workdir: str, dest: str, break_command: str | None) -> None
  shutil.copytree(workdir, dest) ignoring these names: .git, .venv, venv, __pycache__, .pytest_cache, node_modules. If break_command is set, run it with shell=True in dest (raise RuntimeError if its exit code is not 0). Otherwise replace the content of every *.py file under dest with the single line: raise RuntimeError('deliberate break')

verify_step(workdir: str, config: dict, step_command: str | None, scratch_dir: str | None = None) -> dict
  1. checks = run_checks(workdir, config, step_command). If any check is not ok, return verdict "REJECT_CHECKS_FAILED" with control = {"ran": False, "checks": [], "weak": []}.
  2. Otherwise create a temporary directory (tempfile.mkdtemp(dir=scratch_dir)), call make_broken_copy(workdir, <tmp>/broken, config["break_command"]), run run_checks on the broken copy with the same step_command, and collect "weak" = names of control checks that are ok and not listed in config["control_exempt"]. Verdict is "CHECKS_TOO_WEAK" if weak is non-empty, else "ACCEPT". Always remove the temporary directory afterwards (try/finally). The real workdir must never be modified.
  Return {"verdict": ..., "utc": ISO-8601 UTC timestamp string, "step_command": step_command, "checks": checks, "control": {"ran": bool, "checks": [...], "weak": [...]}}.

write_gate_result(evidence_dir: str, step_id: str, result: dict) -> str
  Write result as indented JSON to <evidence_dir>/gate/<step_id>.json (create directories) and return that path as a string.

main(argv: list[str] | None = None) -> int
  argparse with one subcommand "verify" taking --workdir, --config (path to JSON, loaded with load_config), --step-cmd (default ""), --evidence, --step-id (all but --step-cmd required). Run verify_step, write the result with write_gate_result, print one line "<step_id>: <VERDICT>" and then one line "  failed: <check name>" for each failed check (control weak checks: "  weak: <name>"). Return 0 for ACCEPT, 1 for REJECT_CHECKS_FAILED, 3 for CHECKS_TOO_WEAK. End the file with: if __name__ == "__main__": sys.exit(main())

Work like this: write the file, run `python -m pytest -q tests/test_gate.py`, fix, repeat until all tests pass. Keep the code clear with short docstrings. Do not run the whole repository test suite.

```

```
Create ONE new file: bobverified/ledger.py (Python 3.12, standard library only). Make the existing test file tests/test_ledger.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_ledger.py first; it is the exact contract. Context: a runner writes a CSV ledger with columns id, attempt, status, bob_task_id, session_costs, cumulative_spent, duration_ms, accept_pass, commit_sha. IBM Bob keeps its own task store, a SQLite file with a table "tasks" (columns used here: id, status, first_message, costs, created_at). "costs" is a JSON string like {"cost": 0.5, "contextTokens": 100} or NULL; created_at is epoch milliseconds. The module compares what the ledger says was spent with what Bob's own store says.

Implement these public names:

bob_db_tasks(db_path: str, since_ms: int = 0) -> list[dict]
  Open the database READ-ONLY with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) (raise FileNotFoundError first if the file does not exist; never create it). Return one dict per task whose created_at > since_ms and whose costs is not NULL/empty, ordered by created_at ascending: {"id", "status", "cost" (float from the costs JSON), "created_at", "first_line"}. first_line is the first line of first_message, at most 80 characters ("" if NULL).

bob_db_total(db_path: str, since_ms: int = 0) -> float
  Sum of "cost" over bob_db_tasks.

read_ledger(csv_path: str) -> list[dict]
  All rows of the CSV as dicts (csv.DictReader).

ledger_total(csv_path: str) -> float
  Sum of float(session_costs) over rows whose status is "done" or "fail" (ignore any other status such as "reconcile"; treat empty or invalid numbers as 0).

reconcile(ledger_csv: str, db_path: str, since_ms: int = 0, tolerance: float = 0.01) -> dict
  Returns {"ledger_total", "db_total", "delta" (db_total - ledger_total), "status" ("MATCH" if abs(delta) <= tolerance else "MISMATCH"), "retries" (number of ledger rows whose attempt is an integer > 1), "failed_steps" (number of rows with status "fail"), "db_tasks_not_in_ledger" (the bob_db_tasks entries whose id is not any ledger row's bob_task_id)}.

write_reconciliation(evidence_dir: str, ledger_csv: str, db_path: str, since_ms: int = 0, tolerance: float = 0.01) -> str
  Call reconcile, add the key "utc" (ISO-8601 UTC timestamp string) and "since_ms", write indented JSON to <evidence_dir>/reconciliation.json (create the directory) and return that path as a string.

main(argv: list[str] | None = None) -> int
  argparse options: --ledger, --db, --evidence (all required), --since-ms (int, default 0), --tolerance (float, default 0.01). Call write_reconciliation, print one line: "<STATUS> ledger=<x.xxxx> bob=<y.yyyy> delta=<z.zzzz>". Return 0 for MATCH and 2 for MISMATCH. End the file with: if __name__ == "__main__": sys.exit(main())

Work like this: write the file, run `python -m pytest -q tests/test_ledger.py`, fix, repeat until all tests pass. Keep the code clear with short docstrings. Do not run the whole repository test suite.

```

```
Create ONE new file: bobverified/reverify.py (Python 3.12, standard library plus the existing bobverified.gate module). Make the existing test file tests/test_reverify.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_reverify.py first (it is the contract), then read bobverified/gate.py to see load_config and verify_step, which you must reuse (do not copy their logic).

Purpose: re-run the verification pipeline for a finished run against the fetched target, with no call to any AI model, and keep a timestamped log. A "run directory" holds: target.json (a gate config as understood by gate.load_config, plus the extra key "workdir": the path of the target checkout) and plan.json ({"title": ..., "steps": [{"id": ..., "title": ..., "verify": "<shell command, optional>"}, ...]}).

Implement:

reverify(run_dir: str) -> dict
  1. Load <run_dir>/target.json with gate.load_config (raises FileNotFoundError if missing; let it propagate). Take workdir = config["workdir"]; if it is missing raise ValueError. (Check that gate.load_config keeps the extra "workdir" key; if it does not, read the key from the raw JSON instead of editing gate.py.)
  2. Load <run_dir>/plan.json if it exists (no plan means no steps).
  3. For every plan step that has a non-empty "verify" string, in order, call gate.verify_step(workdir, config, step["verify"]). Then call gate.verify_step(workdir, config, None) once more for a final whole-target check, with step_id "final".
  4. Build result = {"utc": <ISO-8601 UTC "%Y-%m-%dT%H:%M:%SZ" at start>, "all_ok": True only if every verdict is "ACCEPT", "results": [{"step_id", "verdict", "failed": [names of checks with ok False], "weak": [names from control weak], "utc": <the gate result's utc>} ...], "log": <text>}.
  5. The log is one line per event, every line starting with a UTC timestamp in that same format followed by a space: a start line ("start reverify of N checks"), one line per step ("<step_id>: <VERDICT>", add " failed: a,b" or " weak: a,b" when relevant), and an end line ("done all_ok=<True/False>"). Take a fresh timestamp for every line.
  6. Save the result as JSON to <run_dir>/reverify/<UTC stamp %Y%m%dT%H%M%S%fZ>.json (the %f microseconds make same-second calls distinct; create the directory) and append the log text plus a newline to <run_dir>/reverify.log. Return the result dict.

main(argv: list[str] | None = None) -> int
  argparse option --run (required). Call reverify, print the log, return 0 if all_ok else 1. End the file with: if __name__ == "__main__": sys.exit(main())

Work like this: write the file, run `python -m pytest -q tests/test_reverify.py`, fix, repeat until all tests pass. Short docstrings, clear code. Do not run the whole repository test suite.

```

```
Create ONE new file: bobverified/dashboard.py (Python 3.12, standard library only). Make the existing test file tests/test_dashboard.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_dashboard.py first; it is the exact contract (it builds a sample "run directory" with make_run). A run directory contains: plan.json ({"title", "target": {"name","url","commit","license"}, "steps": [{"id","title","verify"}]}), ledger.csv (columns id, attempt, status, bob_task_id, session_costs, cumulative_spent, duration_ms, accept_pass, commit_sha), gate/<step id>.json (gate results: verdict, utc, step_command, checks [{name, ok, detail}], control {ran, checks, weak}), reconciliation.json, and reverify/<stamp>.json (records with utc, all_ok, results, log). Every file is optional; missing files must never raise.

Implement these public names:

load_run(run_dir: str) -> dict
  Returns {"title" (plan title, "" if none), "target" (dict, {} if none), "steps": [...], "total_cost": float, "commits": [non-empty commit shas of done steps in step order], "reconciliation": dict|None (reconciliation.json), "last_reverify": dict|None (the JSON file in reverify/ whose file name sorts last)}.
  Steps come from plan.json steps in plan order; if there is no plan, from ledger rows in order. For each step the dict has: "id", "title", "verify", "status" ("done" or "fail" from the LAST ledger row with that id, or "not_run" when there is none), "attempt" (int, 0 if not run), "cost" (float: sum of session_costs of all ledger rows with that id; 0.0 if none), "commit_sha" ("" if none), "gate_verdict" (verdict from gate/<id>.json or None), "gate_utc", "gate_failed" (names of checks with ok false), "control_ran" (bool), "control_weak" (list of names), "gate_checks" (list), "control_checks" (list). total_cost is the sum of the step costs.

render_html(run: dict) -> str
  A complete, self-contained HTML page (inline CSS, no JavaScript, no external resources; readable on a phone; light and dark via prefers-color-scheme). Escape EVERY value taken from the data with html.escape. Show: the title as <title> and <h1>; the target name, url, pinned commit and license; a summary line with counts of done / failed / not run steps, the total cost with 2 decimals, and the reconciliation status (MATCH/MISMATCH with ledger and Bob totals) or "not reconciled"; a table with one row per step with columns: id, title, status, gate verdict, "negative control", cost, attempts, commit (first 7 characters of the sha). The negative control cell reads: "broken copy failed every check" when control_ran and control_weak is empty; "checks too weak: <names>" when control_weak is not empty; "not run" when the gate result exists but the control did not run; "-" when there is no gate result. Under each step with a gate result add a <details> element listing its checks and control checks (name, ok, detail). Add a section "Re-verify" with <form method="post" action="/reverify"> containing one button "Re-verify now" and the sentence that this re-runs the checks against the target and makes no AI call and costs nothing; then, if last_reverify exists, show its utc, all_ok and its log inside <pre>. Colour verdicts: ACCEPT green, REJECT_CHECKS_FAILED red, CHECKS_TOO_WEAK amber, and never use colour alone (the verdict text is always shown).

make_server(run_dir: str, host: str = "127.0.0.1", port: int = 8080, reverify_fn=None) -> http.server.ThreadingHTTPServer
  Handler rules (re-read the run directory on every request so the page is live): GET / -> 200 text/html utf-8 with render_html(load_run(run_dir)); GET /api/run -> 200 application/json of load_run; any other GET path -> 404 (never read files named by the URL). POST /reverify -> call reverify_fn(run_dir) (when reverify_fn is None, import bobverified.reverify lazily and use its reverify) while holding a threading.Lock; if the function raises, build a record {"utc": now, "all_ok": False, "results": [], "log": "<utc> error: <exception text>"}. Count the *.json files in <run_dir>/reverify before and after the call; if the count did not grow (the function did not save its own record, as with a fake), save the returned record as <run_dir>/reverify/<UTC stamp %Y%m%dT%H%M%S%fZ>.json (create the directory). Then answer 303 with Location: / . POST to any other path -> 404. PUT, DELETE and PATCH -> 405 with an Allow: GET, POST header. Silence the default request logging (override log_message). The server must work with port 0 (the tests ask the OS for a free port; use srv.server_address[1]).

main(argv: list[str] | None = None) -> int
  argparse: --run (required), --host (default 127.0.0.1), --port (int, default 8080). Create the server, print "serving <run> on http://<host>:<port>", serve_forever until KeyboardInterrupt, then close. End the file with: if __name__ == "__main__": sys.exit(main())

Work like this: write the file, run `python -m pytest -q tests/test_dashboard.py`, fix, repeat until all tests pass. Clear code, short docstrings. Do not run the whole repository test suite.

```

```
Create ONE new file: bobverified/wire.py (Python 3.12, standard library only). Make the existing test file tests/test_wire.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_wire.py first; it is the exact contract. Context: a "plan" is a JSON file {"title": str, "steps": [{"id", "title", "description" (optional), "verify"}]} produced by an AI planner. A runner (bobverified/bobrun.py, read its _load_tasks/main to see the tasks-file format: keys budget_total, gate_after_task, gate_max_spent, author, tasks[{id, mode, prompt, max_cost, max_turns, timeout_s, accept[], retry_on_fail}]) executes one Bob task per step and treats each task's "accept" shell commands as pass/fail. This module wires a plan and a target configuration into a runner tasks file whose accept command is the independent verification gate (bobverified.gate verify, see its main() for the options: --workdir --config --step-cmd --evidence --step-id).

Implement these public names:

load_plan(path: str) -> dict
  Read the JSON plan and validate; raise ValueError (with a clear message) if: "steps" is missing or not a non-empty list; any step lacks a non-empty string "title"; any step's "id" does not match ^[a-z][a-z0-9_]*$; ids are not unique; any step lacks a "verify" string that is non-empty after strip(). Missing "description" becomes "". Return the plan dict.

step_prompt(step: dict, index: int, total: int) -> str
  The instruction text for Bob. Plain lines, in this order: "Implement step <index> of <total> of the modernization plan, and only that step." / "Step id: <id>" / "Title: <title>" / "Details: <description>" / "Verification command: <verify>" / then these rules: keep changes scoped to this step; do not undo work from earlier steps; run the verification command from the repository root when done and, if it fails, fix the problem within this step and run it again; never write secrets or keys into files; do not create files outside the repository. The prompt must contain the step's own id, title, description and verify text, and must NOT mention any other step's id.

build_tasks(plan: dict, target_config_path: str, workdir: str, evidence_dir: str, python: str = sys.executable, pkg_root: str | None = None, budget_total: float = 20.0, max_cost: float = 4.0, max_turns: int = 40, timeout_s: int = 1800, author: str = "Bob verified runner <runner@example.invalid>", gate_after_task: int = 0, gate_max_spent: float = 1000.0, retry_on_fail: bool = False) -> dict
  Return the runner tasks dict. One task per step in order: {"id": step id, "mode": "agent", "prompt": step_prompt(step, i, n), "max_cost", "max_turns", "timeout_s", "accept": [<one shell command string>], "retry_on_fail"}. The accept command is built from shlex.quote'd tokens joined by spaces: env PYTHONPATH=<pkg_root> <python> -m bobverified.gate verify --workdir <workdir> --config <evidence_dir>/target.json --step-cmd <the step's verify text> --evidence <evidence_dir> --step-id <step id>. pkg_root defaults to the directory that contains the bobverified package (the parent of this file's directory). The tests re-split the command with shlex.split and check the tokens, so quoting must round-trip even for verify text with spaces and quotes.

write_run_files(evidence_dir: str, plan: dict, target_config_path: str, workdir: str) -> None
  Create evidence_dir if needed. Write <evidence_dir>/plan.json: the plan plus a key "target" holding exactly {"name", "url", "commit", "license"} taken from the target config JSON (missing values become ""). Write <evidence_dir>/target.json: the whole target config plus the key "workdir" set to the workdir argument.

main(argv: list[str] | None = None) -> int
  argparse options: --plan, --target, --workdir, --evidence, --out (all required); optional --python (default sys.executable), --pkg-root, --budget (float, default 20), --max-cost (float, default 4), --max-turns (int, default 40), --gate-after (int, default 0), --gate-max-spent (float, default 1000), --retry (flag). Load the plan, call write_run_files then build_tasks, write the tasks dict as indented JSON to --out, print "wrote <out>: <n> tasks, budget <budget>" and return 0. On ValueError or a missing file print the message to stderr and return 2. End the file with: if __name__ == "__main__": sys.exit(main())

Work like this: write the file, run `python -m pytest -q tests/test_wire.py`, fix, repeat until all tests pass. Clear code, short docstrings. Do not run the whole repository test suite.

```

```
Create ONE new file: scripts/fetch_target.sh (bash) and make it executable (chmod +x). Make the existing test file tests/test_fetch.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_fetch.py first; it is the exact contract. Purpose: fetch the legacy demo application at run time from its public upstream at a pinned commit, into a work directory OUTSIDE this repository (the application's code must never be stored in this repository).

Usage: scripts/fetch_target.sh <target.json> <dest_dir>
The JSON file has the keys "url" (a git URL or local path) and "commit" (a full or abbreviated commit sha); other keys are ignored. Read them with python3 -c using the json module (python3 is available; do not require jq).

Behaviour:
1. Use `set -euo pipefail`. With the wrong number of arguments print a usage line to stderr and exit 64.
2. Resolve <dest_dir> to an absolute path without requiring that it exists (python3 os.path.realpath works). Resolve this repository's root as the parent directory of the directory that holds the script. If dest equals the repository root or is inside it, print an error to stderr and exit 2 without creating anything.
3. If <dest>/.git does not exist, create the parent directory and run `git clone --quiet <url> <dest>`; otherwise run `git -C <dest> fetch --quiet origin` (idempotent re-runs must work).
4. Run `git -C <dest> checkout --quiet -f -B modernize <commit>`. If that fails print "commit <commit> not found in <url>" to stderr and exit 1. Then `git -C <dest> reset --quiet --hard <commit>` and `git -C <dest> clean -fdxq` so a re-run always restores a pristine pinned tree.
5. Verify that `git -C <dest> rev-parse HEAD` starts with the requested commit; otherwise exit 1.
6. Set a local commit identity so the runner can commit: `git -C <dest> config user.name "Bob verified runner"` and `git -C <dest> config user.email "runner@example.invalid"`.
7. Print one line: "OK <full sha> <dest>" and exit 0.

Work like this: write the script, run `python -m pytest -q tests/test_fetch.py`, fix, repeat until all tests pass. Keep it short and readable, with a comment header explaining the purpose.

```

```
Create ONE new file: scripts/fetch_target.sh (bash) and make it executable (chmod +x). Make the existing test file tests/test_fetch.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_fetch.py first; it is the exact contract. Purpose: fetch the legacy demo application at run time from its public upstream at a pinned commit, into a work directory OUTSIDE this repository (the application's code must never be stored in this repository).

Usage: scripts/fetch_target.sh <target.json> <dest_dir>
The JSON file has the keys "url" (a git URL or local path) and "commit" (a full or abbreviated commit sha); other keys are ignored. Read them with python3 -c using the json module (python3 is available; do not require jq).

Behaviour:
1. Use `set -euo pipefail`. With the wrong number of arguments print a usage line to stderr and exit 64.
2. Resolve <dest_dir> to an absolute path without requiring that it exists (python3 os.path.realpath works). Resolve this repository's root as the parent directory of the directory that holds the script. If dest equals the repository root or is inside it, print an error to stderr and exit 2 without creating anything.
3. If <dest>/.git does not exist, create the parent directory and run `git clone --quiet <url> <dest>`; otherwise run `git -C <dest> fetch --quiet origin` (idempotent re-runs must work).
4. Run `git -C <dest> checkout --quiet -f -B modernize <commit>`. If that fails print "commit <commit> not found in <url>" to stderr and exit 1. Then `git -C <dest> reset --quiet --hard <commit>` and `git -C <dest> clean -fdxq` so a re-run always restores a pristine pinned tree.
5. Verify that `git -C <dest> rev-parse HEAD` starts with the requested commit; otherwise exit 1.
6. Set a local commit identity so the runner can commit: `git -C <dest> config user.name "Bob verified runner"` and `git -C <dest> config user.email "runner@example.invalid"`.
7. Print one line: "OK <full sha> <dest>" and exit 0.

Work like this: write the script, run `python -m pytest -q tests/test_fetch.py`, fix, repeat until all tests pass. Keep it short and readable, with a comment header explaining the purpose.


Previous attempt failed:
Accept commands failed.
Output:
$ python -m pytest -q tests/test_fetch.py
.....                                                                    [100%]
5 passed in 0.50s

---
$ test -z "$(git status --porcelain | grep -v 'scripts/fetch_target.sh')"

```

```
Create ONE new file: scripts/fetch_target.sh (bash) and make it executable (chmod +x). Make the existing test file tests/test_fetch.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_fetch.py first; it is the exact contract. Purpose: fetch the legacy demo application at run time from its public upstream at a pinned commit, into a work directory OUTSIDE this repository (the application's code must never be stored in this repository).

Usage: scripts/fetch_target.sh <target.json> <dest_dir>
The JSON file has the keys "url" (a git URL or local path) and "commit" (a full or abbreviated commit sha); other keys are ignored. Read them with python3 -c using the json module (python3 is available; do not require jq).

Behaviour:
1. Use `set -euo pipefail`. With the wrong number of arguments print a usage line to stderr and exit 64.
2. Resolve <dest_dir> to an absolute path without requiring that it exists (python3 os.path.realpath works). Resolve this repository's root as the parent directory of the directory that holds the script. If dest equals the repository root or is inside it, print an error to stderr and exit 2 without creating anything.
3. If <dest>/.git does not exist, create the parent directory and run `git clone --quiet <url> <dest>`; otherwise run `git -C <dest> fetch --quiet origin` (idempotent re-runs must work).
4. Run `git -C <dest> checkout --quiet -f -B modernize <commit>`. If that fails print "commit <commit> not found in <url>" to stderr and exit 1. Then `git -C <dest> reset --quiet --hard <commit>` and `git -C <dest> clean -fdxq` so a re-run always restores a pristine pinned tree.
5. Verify that `git -C <dest> rev-parse HEAD` starts with the requested commit; otherwise exit 1.
6. Set a local commit identity so the runner can commit: `git -C <dest> config user.name "Bob verified runner"` and `git -C <dest> config user.email "runner@example.invalid"`.
7. Print one line: "OK <full sha> <dest>" and exit 0.

Work like this: write the script, run `python -m pytest -q tests/test_fetch.py`, fix, repeat until all tests pass. Keep it short and readable, with a comment header explaining the purpose.

```

```
Edit ONE existing file: bobverified/gate.py. Add support for an optional "env" mapping in the target configuration so commands can use per-target environment variables (for example the location of a virtualenv that lives outside the target directory). Make the new tests at the end of tests/test_gate.py pass, and keep every existing test in that file passing. Do not edit any test file and do not change any other file.

Read tests/test_gate.py (especially the last section "per-target environment variables") and bobverified/gate.py first.

Required changes:
1. load_config: new key "env", default {}. It must be a dict whose keys and values are all strings, otherwise raise ValueError. Keep it in the returned dict.
2. A single helper that builds the child environment: start from os.environ, remove BOB_API_KEY, merge config.get("env", {}) on top, then remove BOB_API_KEY again (so the config can never put the key back). Use it for EVERY subprocess the module starts: the step command, the test command, the start command, and the break command.
3. make_broken_copy gets a new optional keyword parameter env: dict | None = None (a plain mapping merged as in point 2, used only for the break command). verify_step must pass config.get("env") to it.
Existing call signatures must keep working.

Work like this: edit the file, run `python -m pytest -q tests/test_gate.py`, fix, repeat until all tests pass. Do not run other test files.

```

```
Edit ONE existing file: bobverified/wire.py. Add environment-variable support for the target. Make the new tests at the end of tests/test_wire.py pass, and keep every existing test in that file passing. Do not edit any test file and do not change any other file.

Read tests/test_wire.py (especially the last two tests) and bobverified/wire.py first.

Required changes:
1. write_run_files gets a new optional keyword parameter env: dict | None = None. When given, the "env" key of the written <evidence_dir>/target.json is the target config's own "env" mapping (default {}) updated with env (the argument wins). When not given, behave as before but still keep the config's own "env" if it has one.
2. main gets a repeatable option --env KEY=VALUE (argparse action="append", default empty). Split each on the first "=" ; if there is no "=" or the key is empty, print a message to stderr and return 2. Pass the resulting dict to write_run_files.
Existing call signatures must keep working.

Work like this: edit the file, run `python -m pytest -q tests/test_wire.py`, fix, repeat until all tests pass. Do not run other test files.

```

```
Edit ONE existing file: bobverified/wire.py. Add a max_steps limit to plan loading. Make the new test test_load_plan_max_steps at the end of tests/test_wire.py pass and keep every other test in that file passing. Do not edit any test file and do not change any other file.

Change load_plan to accept an optional second parameter max_steps: int | None = None. When max_steps is not None and the plan has more steps than max_steps, raise ValueError with a clear message naming both numbers. Add a --max-steps option (int, default None) to main() and pass it to load_plan. Existing call signatures must keep working.

Work like this: edit the file, run `python -m pytest -q tests/test_wire.py`, fix, repeat until all tests pass. Do not run other test files.

```

```
Create three NEW files in a new directory deploy/ : deploy/Dockerfile, deploy/bob-verified-dashboard.service and deploy/DEPLOY.md. Make the existing test file tests/test_deploy_files.py pass. Do not edit any test file and do not create or change any other file.

Read tests/test_deploy_files.py first. Context: this repository contains a Python package "bobverified" (standard library only) whose module bobverified.dashboard serves a read-only web page for one "run directory" (options: --run DIR, --host, --port; default port 8080) and has a POST /reverify action that re-runs the verification checks against a fetched target checkout (no AI call). Read bobverified/dashboard.py and bobverified/reverify.py to confirm the options.

deploy/Dockerfile: FROM python:3.12-slim; install git (apt-get install -y --no-install-recommends git, then clean the apt lists); WORKDIR /app; COPY bobverified ./bobverified; ENV PYTHONUNBUFFERED=1; create a non-root user and switch to it; EXPOSE 8080; a VOLUME or comment explaining that the run directory is mounted at /data/run; CMD ["python", "-m", "bobverified.dashboard", "--run", "/data/run", "--host", "0.0.0.0", "--port", "8080"]. No secrets.

deploy/bob-verified-dashboard.service: a systemd unit (Description, After=network.target, a [Service] section running /usr/bin/python3.12 -m bobverified.dashboard --run /srv/bob-verified/run --host 127.0.0.1 --port 8080 with WorkingDirectory=/srv/bob-verified/app, Restart=on-failure, a dedicated User=bobverified, and Environment=TARGET_VENV=/srv/bob-verified/target-venv; [Install] WantedBy=multi-user.target).

deploy/DEPLOY.md: short, numbered steps for putting the dashboard on a Linux server behind a URL: copy the repository, copy the finished run directory (the evidence folder produced by a run) to /srv/bob-verified/run, create the target virtual environment (TARGET_VENV) and fetch the target with scripts/fetch_target.sh so that the "re-verify" button has something real to verify (the run directory's target.json says where the checkout is), install the systemd unit, put a reverse proxy (nginx or a cloud load balancer) in front on port 443 and forward to port 8080, and check it: open the page, press "Re-verify now" and read the timestamped log. Explain in two sentences that the page is read-only except for the re-verify button, which runs the stored verification commands and never calls an AI model. Mention the Docker alternative with the exact docker build and docker run commands (mount the run directory read-write at /data/run, because re-verify saves its log there, and publish port 8080).

Do not run Docker or systemd. Run `python -m pytest -q tests/test_deploy_files.py` until it passes.

```

```
Create TWO new files at the repository root: README.md and THIRD_PARTY.md. Do not change any other file. The facts below are exact; use them verbatim and do not invent any other facts, numbers, results or claims. Read the repository (bobverified/, scripts/, targets/, tests/, deploy/, docs/BUILD_HISTORY.md) so that every module, command and option you mention really exists.

README.md must contain, in a clear structure with short sections:
1. Title "Bob, verified" and a two-sentence summary: a tool that lets an engineering team hand a legacy codebase to IBM Bob and get a modernization they can trust, because every step Bob takes is checked by an independent gate before it is accepted.
2. A section stating plainly, in these words: "The primary contribution of this repository is the verification and orchestration layer (the gate, the negative control, the ledger reconciliation and the dashboard). It is not the demo application, which is fetched at run time and is not part of this repository."
3. How it works in five numbered stages: plan (IBM Bob in plan mode proposes numbered steps, each with one verification command), step (IBM Bob in agent mode implements one step), gate (the step's verification command, the target's own smoke checks, and a negative control: the same checks run on a deliberately broken copy must fail, otherwise the step is refused with the verdict CHECKS_TOO_WEAK), ledger (per-step cost from Bob's own result reconciled against Bob's local task store, retries counted, budget cap), dashboard (read-only page per run with a "Re-verify now" button that re-runs the checks against the target and shows a timestamped log, with no AI call and no cost). Describe only what the code in bobverified/ does.
4. Repository map: one line per module in bobverified/ (bobrun, gate, ledger, reverify, dashboard, wire), scripts/fetch_target.sh, targets/, tests/, deploy/, docs/.
5. Demo target: name simple_api, upstream URL https://github.com/mmautner/simple_api, pinned commit 17067fe3113a746e0a5044af88f5777d6e50c999, licence MIT (Copyright (c) 2014 Max Mautner). It is fetched by scripts/fetch_target.sh using targets/simple_api.json into a work directory outside this repository. Say that the results of the recorded demo run are added under docs/ after the run, and make no claim about results that are not in the repository.
6. Provenance: everything in this repository was written between 16 and 18 October 2026 (the hackathon period), except the runner bobverified/bobrun.py and its tests, which were ported from a runner written on 15 October 2026 by the team, not by IBM Bob (original file sha256 7638f47e2a7bf9cdfefb7e4d97d2b93c4d2644daf7bda757c9e28605928eecd3). The other modules were written by IBM Bob from specifications and tests written by the team; docs/BUILD_HISTORY.md lists who wrote what, and the git history carries Bob-Task and Bob-Trace trailers on Bob's commits.
7. Testing: python3.12 -m venv .venv; .venv/bin/pip install pytest; .venv/bin/python -m pytest -q (the full suite takes a few minutes because the gate tests start real servers). Python 3.12 and git are required; the package uses only the standard library.
8. Running it: the commands to build the tasks file (python -m bobverified.wire ...), run the runner (python -m bobverified.bobrun ...), reconcile costs (python -m bobverified.ledger ...), serve the dashboard (python -m bobverified.dashboard --run DIR) and re-verify from the command line (python -m bobverified.reverify --run DIR). Mention the environment variables BOB_API_KEY (never stored in any file) and TARGET_VENV (the virtualenv location, outside the target tree), and that wire accepts --env KEY=VALUE. Use the real option names from the code.

THIRD_PARTY.md: a table or list with: IBM Bob (Bob Shell), the AI development tool used to write and operate parts of this project, used under IBM's terms, not redistributed; simple_api by Max Mautner, MIT licence, fetched at run time from the URL and commit above, not distributed in this repository, its licence text is in its own repository; the libraries that the demo target's modernization installs inside the target (Flask, Flask-RESTful, SQLAlchemy; all permissively licensed, installed from their public releases, not vendored); pytest (MIT) as the only development dependency of this repository; Python standard library for all runtime code. State that no code from the target application is included in this repository.

Style: plain, factual, no marketing language, no emojis. Do not mention any internal hostnames, directory paths, company or client names other than IBM, or any AI model or provider other than IBM Bob.

```
