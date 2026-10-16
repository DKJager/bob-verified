# Build history: who wrote what

Everything in this repository was written between 16 and 18 October 2026 (the hackathon period), except where stated below. This file records who or what wrote each part.

## Ported runner (written by the team on 15 Oct 2026, not by Bob)

- bobverified/bobrun.py and tests/test_bobrun.py are ported from a task runner and its 23 tests written on 15 Oct 2026 (inside the hackathon period) by the team, NOT by IBM Bob. Original runner sha256: 7638f47e2a7bf9cdfefb7e4d97d2b93c4d2644daf7bda757c9e28605928eecd3.
- Changes made while porting (16 Oct 2026, by the team): module moved into the bobverified package, default Bob binary changed to "bob", internal paths and comments removed from the tests, test import lines adjusted. Logic unchanged.
- Commit: "port runner written 15 Oct (not by Bob)".

## Written by IBM Bob (phase 1, the tool)

Each task ran through the runner: Bob wrote the implementation from a precise specification and a test file written by the team; the runner accepted the task only if the named tests passed and no other file had changed, and then committed with Bob-Task and Bob-Trace trailers.

| Task | What Bob wrote | Result | Credits (Bob's own figure) | Commit |
|---|---|---|---|---|
| b01_gate | bobverified/gate.py | done (attempt 1) | 0.319 | 078c8127 |
| b02_ledger | bobverified/ledger.py | done (attempt 1) | 0.176 | 7c7c7c75 |
| b03_reverify | bobverified/reverify.py | done (attempt 1) | 0.331 | 402a479a |
| b04_dashboard | bobverified/dashboard.py | done (attempt 1) | 0.470 | bd370b28 |
| b05_wire | bobverified/wire.py (first version) | done (attempt 1) | 0.249 | 7b4ac0a3 |
| b06_fetch | scripts/fetch_target.sh | fail (attempt 2) | 0.354 | none |
| b06_fetch | scripts/fetch_target.sh | done (attempt 1) | 0.156 | d95e36fa |
| b07_gate_env | bobverified/gate.py (per-target env support) | done (attempt 1) | 0.166 | 50262638 |
| b08_wire_env | bobverified/wire.py (env flags) | done (attempt 1) | 0.135 | 4eb3a9f7 |
| b09_maxsteps | bobverified/wire.py (max_steps) | done (attempt 1) | 0.131 | 9fa5cd28 |
| b10_deploy | deploy/Dockerfile, deploy/bob-verified-dashboard.service, deploy/DEPLOY.md | done (attempt 1) | 0.361 | 7564a8c2 |
| b11_docs | README.md, THIRD_PARTY.md | done (attempt 1) | 0.450 | 5b01eb61 |
| b12_dashfix | bobverified/dashboard.py (credits display, total including planning) | done (attempt 1) | 0.273 | a93b87ff |
| b13_dashtimeout | bobverified/dashboard.py (re-verify as a subprocess stopped with its whole process tree at a time limit) | done (attempt 1) | 0.309 | a0ae1d6c |
| b14_dashlimits | bobverified/dashboard.py (per-visitor rate limit, one re-verify at a time) | done (attempt 1) | 0.339 | b86733a1 |

Total Bob credits for tool-building (tasks above), from Bob's local task store: 4.219.

The live demo host was deployed on 16 Oct 2026 with these files; the history of this repository was rewritten once before publication to remove fixture key strings and a personal default address (commit ids in this file are the ids after the rewrite).

Task b06_fetch ran twice. The first attempt's tests passed, but an acceptance check written by the team mishandled a newly created directory and rejected it; the check was fixed (git status -uall) and the task was run again.

## Written by the team without Bob

- All test files except the ported runner tests: tests/test_gate.py, test_ledger.py, test_reverify.py, test_dashboard.py, test_wire.py, test_fetch.py, test_e2e.py, test_targets.py, test_deploy_files.py, plus tests/conftest.py. They were written before the implementation they check, and they define the contract Bob was given.
- targets/simple_api.json (the pinned demo target configuration), pyproject.toml, .gitignore and this file.
- The task specifications given to Bob (kept in the run evidence).

## Edits by the team to files Bob wrote

- bobverified/dashboard.py was changed by Bob in task b12 after the team saw the real dashboard (it showed dollars and left out the planning cost).
- bobverified/wire.py: the default value of the author parameter of build_tasks was changed from a personal address to the neutral "Bob verified runner <runner@example.invalid>" (one line, 16 Oct 2026). Nothing else in Bob's modules was edited by hand.

## The recorded demo run (16 Oct 2026)

Run through the tool itself (evidence in docs/run/): IBM Bob in plan mode wrote the 3-step plan for the demo target; IBM Bob in agent mode implemented each step; the gate accepted each step after its negative control. The team wrote no code in the target. The plan task and the three step tasks are in docs/run/ledger.csv; the commits are in the work checkout and carry Bob-Task trailers.

## Written by the team without Bob (submission package)

deploy/setup_box.sh, deploy/nginx-bob-verified.conf and the hardened systemd unit, SECURITY_SCAN.md, LICENSE, README additions (results section, live demo URL), SUBMISSION.md, docs/PITCH.md, docs/PITCH.pdf (rendered from the same content), docs/SCRIPT.md, deploy/README.md. The owner checklist is kept out of the repository.

Bob wrote no tests in phase 1; the team wrote no implementation module other than the ported runner.
