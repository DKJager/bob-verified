"""Reconcile a CSV ledger against IBM Bob's SQLite task store."""

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone


def bob_db_tasks(db_path: str, since_ms: int = 0) -> list[dict]:
    """Return tasks from Bob's SQLite store created after since_ms with non-null costs."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT id, status, first_message, costs, created_at "
            "FROM tasks WHERE created_at > ? AND costs IS NOT NULL AND costs != '' "
            "ORDER BY created_at ASC",
            (since_ms,),
        )
        rows = []
        for row in cur.fetchall():
            tid, status, first_message, costs_json, created_at = row
            cost = json.loads(costs_json)["cost"]
            first_line = ""
            if first_message:
                first_line = first_message.split("\n")[0][:80]
            rows.append({
                "id": tid,
                "status": status,
                "cost": float(cost),
                "created_at": created_at,
                "first_line": first_line,
            })
        return rows
    finally:
        conn.close()


def bob_db_total(db_path: str, since_ms: int = 0) -> float:
    """Sum of cost over all bob_db_tasks results."""
    return sum(t["cost"] for t in bob_db_tasks(db_path, since_ms))


def read_ledger(csv_path: str) -> list[dict]:
    """Return all rows of the CSV as dicts."""
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def ledger_total(csv_path: str) -> float:
    """Sum session_costs for rows with status 'done' or 'fail'; invalid numbers count as 0."""
    total = 0.0
    for row in read_ledger(csv_path):
        if row.get("status") not in ("done", "fail"):
            continue
        try:
            total += float(row.get("session_costs") or 0)
        except (ValueError, TypeError):
            pass
    return total


def reconcile(
    ledger_csv: str,
    db_path: str,
    since_ms: int = 0,
    tolerance: float = 0.01,
) -> dict:
    """Compare the ledger totals against Bob's task store and return a reconciliation summary."""
    l_total = ledger_total(ledger_csv)
    d_total = bob_db_total(db_path, since_ms)
    delta = d_total - l_total

    rows = read_ledger(ledger_csv)
    retries = sum(1 for r in rows if _is_retry(r.get("attempt", "")))
    failed_steps = sum(1 for r in rows if r.get("status") == "fail")

    ledger_task_ids = {r.get("bob_task_id") for r in rows}
    db_tasks = bob_db_tasks(db_path, since_ms)
    db_tasks_not_in_ledger = [t for t in db_tasks if t["id"] not in ledger_task_ids]

    status = "MATCH" if abs(delta) <= tolerance else "MISMATCH"
    return {
        "ledger_total": l_total,
        "db_total": d_total,
        "delta": delta,
        "status": status,
        "retries": retries,
        "failed_steps": failed_steps,
        "db_tasks_not_in_ledger": db_tasks_not_in_ledger,
    }


def _is_retry(attempt: str) -> bool:
    """Return True if attempt is an integer > 1."""
    try:
        return int(attempt) > 1
    except (ValueError, TypeError):
        return False


def write_reconciliation(
    evidence_dir: str,
    ledger_csv: str,
    db_path: str,
    since_ms: int = 0,
    tolerance: float = 0.01,
) -> str:
    """Run reconcile, append metadata, write JSON to evidence_dir/reconciliation.json, return path."""
    result = reconcile(ledger_csv, db_path, since_ms, tolerance)
    result["utc"] = datetime.now(timezone.utc).isoformat()
    result["since_ms"] = since_ms
    os.makedirs(evidence_dir, exist_ok=True)
    out_path = os.path.join(evidence_dir, "reconciliation.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return out_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: reconcile ledger against Bob's DB and write evidence."""
    parser = argparse.ArgumentParser(description="Reconcile CSV ledger with Bob task store")
    parser.add_argument("--ledger", required=True, help="Path to the CSV ledger file")
    parser.add_argument("--db", required=True, help="Path to Bob's SQLite database")
    parser.add_argument("--evidence", required=True, help="Directory for reconciliation output")
    parser.add_argument("--since-ms", type=int, default=0, help="Epoch ms lower bound (exclusive)")
    parser.add_argument("--tolerance", type=float, default=0.01, help="Match tolerance")
    args = parser.parse_args(argv)

    out_path = write_reconciliation(args.evidence, args.ledger, args.db, args.since_ms, args.tolerance)
    data = json.loads(open(out_path).read())
    print(
        f"{data['status']} ledger={data['ledger_total']:.4f} "
        f"bob={data['db_total']:.4f} delta={data['delta']:.4f}"
    )
    return 0 if data["status"] == "MATCH" else 2


if __name__ == "__main__":
    sys.exit(main())
