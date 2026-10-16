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
| b01_gate | bobverified/gate.py | done (attempt 1) | 0.319 | ed457e43 |
| b02_ledger | bobverified/ledger.py | done (attempt 1) | 0.176 | 35e21157 |
| b03_reverify | bobverified/reverify.py | done (attempt 1) | 0.331 | 48b71144 |
| b04_dashboard | bobverified/dashboard.py | done (attempt 1) | 0.470 | 1541f121 |
| b05_wire | bobverified/wire.py (first version) | done (attempt 1) | 0.249 | 101f5a27 |
| b06_fetch | scripts/fetch_target.sh | fail (attempt 2) | 0.354 | none |
| b06_fetch | scripts/fetch_target.sh | done (attempt 1) | 0.156 | 9a19e60c |
| b07_gate_env | bobverified/gate.py (per-target env support) | done (attempt 1) | 0.166 | c001be50 |
| b08_wire_env | bobverified/wire.py (env flags) | done (attempt 1) | 0.135 | 389e81bd |
| b09_maxsteps | bobverified/wire.py (max_steps) | done (attempt 1) | 0.131 | c7e01579 |
| b10_deploy | deploy/Dockerfile, deploy/bob-verified-dashboard.service, deploy/DEPLOY.md | done (attempt 1) | 0.361 | 033fbcf4 |
| b11_docs | README.md, THIRD_PARTY.md | done (attempt 1) | 0.450 | 498b922d |

Total Bob credits for this phase, from Bob's local task store: 3.298.

Task b06_fetch ran twice. The first attempt's tests passed, but an acceptance check written by the team mishandled a newly created directory and rejected it; the check was fixed (git status -uall) and the task was run again.

## Written by the team without Bob

- All test files except the ported runner tests: tests/test_gate.py, test_ledger.py, test_reverify.py, test_dashboard.py, test_wire.py, test_fetch.py, test_e2e.py, test_targets.py, test_deploy_files.py, plus tests/conftest.py. They were written before the implementation they check, and they define the contract Bob was given.
- targets/simple_api.json (the pinned demo target configuration), pyproject.toml, .gitignore and this file.
- The task specifications given to Bob (kept in the run evidence).

## Edits by the team to files Bob wrote

- bobverified/wire.py: the default value of the author parameter of build_tasks was changed from a personal address to the neutral "Bob verified runner <runner@example.invalid>" (one line, 16 Oct 2026). Nothing else in Bob's modules was edited by hand.

Bob wrote no tests in phase 1; the team wrote no implementation module other than the ported runner.
