"""Tests for bobverified.ledger (written by the team; Bob writes the implementation)."""
import csv
import json
import sqlite3
import subprocess
import sys

import pytest

from bobverified import ledger

FIELDS = ["id", "attempt", "status", "bob_task_id", "session_costs", "cumulative_spent",
          "duration_ms", "accept_pass", "commit_sha"]


def make_db(path, rows):
    """rows: (id, status, cost_or_None, created_at, first_message). Same column names as Bob's task store."""
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, first_message TEXT, costs TEXT, created_at INTEGER)")
    for tid, status, cost, ts, msg in rows:
        costs = None if cost is None else json.dumps({"cost": cost, "contextTokens": 100})
        c.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", (tid, status, msg, costs, ts))
    c.commit()
    c.close()


def make_ledger(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            full = {k: "" for k in FIELDS}
            full.update(r)
            w.writerow(full)


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "bob.db")
    make_db(p, [
        ("old1", "completed", 39.0, 1000, "an old task before the window"),
        ("t1", "completed", 0.5, 2000, "write gate\nsecond line"),
        ("t2", "error", 1.25, 3000, "write ledger"),
        ("t2b", "completed", 0.75, 3500, "write ledger retry"),
        ("nocost", "active", None, 4000, "no cost yet"),
    ])
    return p


def test_bob_db_tasks_filters_by_time_and_skips_null_costs(db):
    rows = ledger.bob_db_tasks(db, since_ms=1500)
    assert [r["id"] for r in rows] == ["t1", "t2", "t2b"]
    assert rows[0]["cost"] == 0.5
    assert rows[0]["first_line"] == "write gate"
    assert set(rows[0]) >= {"id", "status", "cost", "created_at", "first_line"}


def test_bob_db_total(db):
    assert ledger.bob_db_total(db, since_ms=1500) == pytest.approx(2.5)
    assert ledger.bob_db_total(db) == pytest.approx(41.5)


def test_bob_db_missing_file_raises_and_is_not_created(tmp_path):
    p = tmp_path / "nope.db"
    with pytest.raises(FileNotFoundError):
        ledger.bob_db_total(str(p))
    assert not p.exists()


def test_ledger_total_ignores_reconcile_rows(tmp_path):
    p = str(tmp_path / "ledger.csv")
    make_ledger(p, [
        {"id": "a", "attempt": "1", "status": "done", "session_costs": "0.5", "bob_task_id": "t1"},
        {"id": "b", "attempt": "2", "status": "fail", "session_costs": "2.0", "bob_task_id": "t2b"},
        {"id": "reconcile", "attempt": "0", "status": "reconcile", "session_costs": "9.0"},
    ])
    assert ledger.ledger_total(p) == pytest.approx(2.5)
    assert len(ledger.read_ledger(p)) == 3


def test_reconcile_match(db, tmp_path):
    p = str(tmp_path / "ledger.csv")
    make_ledger(p, [
        {"id": "a", "attempt": "1", "status": "done", "session_costs": "0.5", "bob_task_id": "t1"},
        {"id": "b", "attempt": "2", "status": "done", "session_costs": "2.0", "bob_task_id": "t2b"},
    ])
    r = ledger.reconcile(p, db, since_ms=1500)
    assert r["status"] == "MATCH"
    assert r["ledger_total"] == pytest.approx(2.5)
    assert r["db_total"] == pytest.approx(2.5)
    assert r["delta"] == pytest.approx(0.0)
    assert r["retries"] == 1
    assert r["failed_steps"] == 0
    assert [t["id"] for t in r["db_tasks_not_in_ledger"]] == ["t2"]


def test_reconcile_detects_under_reported_ledger(db, tmp_path):
    """The ledger claims less than Bob really charged (the failure seen on 15 Oct)."""
    p = str(tmp_path / "ledger.csv")
    make_ledger(p, [
        {"id": "a", "attempt": "1", "status": "done", "session_costs": "0.5", "bob_task_id": "t1"},
        {"id": "b", "attempt": "1", "status": "fail", "session_costs": "0.0", "bob_task_id": "t2"},
    ])
    r = ledger.reconcile(p, db, since_ms=1500)
    assert r["status"] == "MISMATCH"
    assert r["delta"] == pytest.approx(2.0)
    assert r["failed_steps"] == 1


def test_reconcile_tolerance(db, tmp_path):
    p = str(tmp_path / "ledger.csv")
    make_ledger(p, [{"id": "a", "attempt": "1", "status": "done", "session_costs": "2.495", "bob_task_id": "t1"}])
    assert ledger.reconcile(p, db, since_ms=1500, tolerance=0.01)["status"] == "MATCH"
    assert ledger.reconcile(p, db, since_ms=1500, tolerance=0.001)["status"] == "MISMATCH"


def test_write_reconciliation_and_cli(db, tmp_path):
    p = str(tmp_path / "ledger.csv")
    make_ledger(p, [{"id": "a", "attempt": "1", "status": "done", "session_costs": "2.5", "bob_task_id": "t1"}])
    ev = tmp_path / "ev"
    out = ledger.write_reconciliation(str(ev), p, db, since_ms=1500)
    data = json.loads(open(out).read())
    assert str(out).endswith("reconciliation.json")
    assert data["status"] == "MATCH" and "utc" in data
    r = subprocess.run([sys.executable, "-m", "bobverified.ledger", "--ledger", p, "--db", db,
                        "--evidence", str(ev), "--since-ms", "1500"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "MATCH" in r.stdout
    make_ledger(p, [{"id": "a", "attempt": "1", "status": "done", "session_costs": "0.1", "bob_task_id": "t1"}])
    r = subprocess.run([sys.executable, "-m", "bobverified.ledger", "--ledger", p, "--db", db,
                        "--evidence", str(ev), "--since-ms", "1500"], capture_output=True, text=True)
    assert r.returncode == 2
    assert "MISMATCH" in r.stdout
