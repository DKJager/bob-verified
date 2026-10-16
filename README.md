# Bob, verified

A tool that lets an engineering team hand a legacy codebase to IBM Bob and get a modernization they can trust, because every step Bob takes is checked by an independent gate before it is accepted.

---

## What this repository is

The primary contribution of this repository is the verification and orchestration layer (the gate, the negative control, the ledger reconciliation and the dashboard). It is not the demo application, which is fetched at run time and is not part of this repository.

---

## How it works

The pipeline has five stages:

1. **Plan.** IBM Bob runs in plan mode and proposes a numbered list of steps. Each step carries a title, a description, and a single verification command that must pass before the step is accepted.

2. **Step.** IBM Bob runs in agent mode and implements one step at a time. The prompt instructs it to work only on the current step and to run the verification command itself before finishing.

3. **Gate.** Once Bob finishes a step, the gate runs three things: (a) the step's own verification command, (b) the target's smoke checks (`test_command` from the target config), and (c) a negative control — the same checks are re-run on a deliberately broken copy of the working directory, and if any check passes on the broken copy the step is refused with the verdict `CHECKS_TOO_WEAK`. Only a verdict of `ACCEPT` allows the step to be committed and the run to continue.

4. **Ledger.** The runner writes a CSV ledger with per-step cost, attempt count, and status. After the run, `bobverified.ledger` reconciles the session costs recorded in the ledger against the costs stored in Bob's own local task database and reports `MATCH` or `MISMATCH`. Retries are counted. A configurable budget cap stops the run before a task is started if the remaining budget would be exceeded.

5. **Dashboard.** `bobverified.dashboard` serves a read-only HTML page for a finished run. The page shows each step's status, gate verdict, negative-control outcome, cost, attempt count, and commit SHA. A "Re-verify now" button triggers `bobverified.reverify`, which re-runs the gate checks against the target, appends a timestamped log entry, and refreshes the page. The re-verify action makes no AI call and costs nothing.

---

## Repository map

| Path | Purpose |
|---|---|
| `bobverified/bobrun.py` | Task runner: drives IBM Bob step by step, writes the ledger and evidence, commits accepted steps |
| `bobverified/gate.py` | Gate: runs verification checks and the negative-control broken-copy test |
| `bobverified/ledger.py` | Reconciles the CSV ledger against Bob's local task store; reports cost totals and retries |
| `bobverified/reverify.py` | Re-runs the gate checks against the target without any AI call |
| `bobverified/dashboard.py` | HTTP dashboard server; exposes the "Re-verify now" action |
| `bobverified/wire.py` | Assembles a plan JSON and target config into a bobrun tasks file |
| `scripts/fetch_target.sh` | Fetches and pins the demo target from its upstream repository |
| `targets/` | Target config files (JSON); one per supported demo target |
| `tests/` | Full test suite for all modules above |
| `deploy/` | Dockerfile, systemd unit, and deployment notes |
| `docs/` | Build history and run artefacts added after a recorded demo run |

---

## Demo target

| Field | Value |
|---|---|
| Name | `simple_api` |
| Upstream URL | https://github.com/mmautner/simple_api |
| Pinned commit | `17067fe3113a746e0a5044af88f5777d6e50c999` |
| Licence | MIT (Copyright (c) 2014 Max Mautner) |
| Config | `targets/simple_api.json` |

`scripts/fetch_target.sh` reads `targets/simple_api.json` and checks out the pinned commit into a work directory outside this repository. The source code of `simple_api` is not stored here.

The results of the recorded demo run are added under `docs/` after the run. No claim is made here about results that are not yet in the repository.

---

## Provenance

Everything in this repository was written between 16 and 18 October 2026 (the hackathon period), with one exception: `bobverified/bobrun.py` and its tests were ported from a runner written on 15 October 2026 by the team, not by IBM Bob (original file sha256 `7638f47e2a7bf9cdfefb7e4d97d2b93c4d2644daf7bda757c9e28605928eecd3`).

The other modules were written by IBM Bob from specifications and tests written by the team. `docs/BUILD_HISTORY.md` lists who wrote what. Bob's commits carry `Bob-Task` and `Bob-Trace` trailers in the git history.

---

## Testing

Requirements: Python 3.12, git. The package uses only the standard library at runtime.

```
python3.12 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

The full suite takes a few minutes because the gate tests start real servers.

---

## Running it

### 1. Build the tasks file

```
python -m bobverified.wire \
  --plan PLAN.json \
  --target targets/simple_api.json \
  --workdir /path/to/workdir \
  --evidence /path/to/run-dir \
  --out tasks.json
```

Key options: `--budget` (total cost cap, default 20.0), `--max-cost` (per-task cap, default 4.0), `--max-turns` (default 40), `--env KEY=VALUE` (repeated; merged into the target environment for gate checks).

### 2. Run the runner

```
BOB_API_KEY=... python -m bobverified.bobrun \
  --tasks tasks.json \
  --workspace /path/to/workdir \
  --evidence /path/to/run-dir
```

Options: `--bob` (path to the bob binary, default `bob`), `--resume` (skip already-done steps), `--dry` (dry run without calling Bob), `--only STEP_ID[,STEP_ID]` (run a subset of steps).

`BOB_API_KEY` is read from the environment and never stored in any file.

### 3. Reconcile costs

```
python -m bobverified.ledger \
  --ledger /path/to/run-dir/ledger.csv \
  --db /path/to/bob.db \
  --evidence /path/to/run-dir
```

### 4. Serve the dashboard

```
python -m bobverified.dashboard --run /path/to/run-dir
```

Options: `--host` (default `127.0.0.1`), `--port` (default `8080`).

### 5. Re-verify from the command line

```
python -m bobverified.reverify --run /path/to/run-dir
```

Exits 0 if all checks pass, 1 otherwise.

### Environment variables

| Variable | Purpose |
|---|---|
| `BOB_API_KEY` | API key passed to IBM Bob; never stored in any file |
| `TARGET_VENV` | Path to the virtualenv for the target application; must be outside the target tree |
