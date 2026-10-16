"""Dashboard: load a bobverified run directory and serve an HTML status page."""
from __future__ import annotations

import argparse
import csv
import http.server
import json
import sys
import threading
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# load_run
# ---------------------------------------------------------------------------

def load_run(run_dir: str) -> dict:
    """Read a run directory and return a unified dict."""
    root = Path(run_dir)

    # plan.json
    plan_path = root / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
    else:
        plan = {}

    title = plan.get("title", "")
    target = plan.get("target", {})
    plan_steps: list[dict] = plan.get("steps", [])

    # ledger.csv
    ledger_rows: list[dict] = []
    ledger_path = root / "ledger.csv"
    if ledger_path.exists():
        with open(ledger_path, newline="") as f:
            ledger_rows = list(csv.DictReader(f))

    # Build step list – from plan if available, else from ledger order
    if plan_steps:
        step_ids = [s["id"] for s in plan_steps]
        step_meta: dict[str, dict] = {s["id"]: s for s in plan_steps}
    else:
        seen: dict[str, None] = {}
        for row in ledger_rows:
            seen[row["id"]] = None
        step_ids = list(seen.keys())
        step_meta = {}

    # Group ledger rows by step id (preserving order of appearance)
    from collections import defaultdict
    by_id: dict[str, list[dict]] = defaultdict(list)
    for row in ledger_rows:
        by_id[row["id"]].append(row)

    # gate/<id>.json
    def load_gate(step_id: str) -> dict | None:
        p = root / "gate" / f"{step_id}.json"
        if p.exists():
            return json.loads(p.read_text())
        return None

    # total_cost: sum session_costs for ALL ledger rows with status "done" or "fail"
    total_cost = sum(
        float(r.get("session_costs") or 0)
        for r in ledger_rows
        if r.get("status") in ("done", "fail")
    )

    steps = []
    commits: list[str] = []

    for sid in step_ids:
        meta = step_meta.get(sid, {"id": sid, "title": "", "verify": ""})
        rows = by_id.get(sid, [])
        last_row = rows[-1] if rows else None

        status = last_row["status"] if last_row else "not_run"
        attempt = int(last_row["attempt"]) if last_row else 0
        cost = sum(float(r.get("session_costs") or 0) for r in rows)
        commit_sha = (last_row.get("commit_sha") or "") if last_row else ""

        gate = load_gate(sid)
        if gate:
            gate_verdict: str | None = gate.get("verdict")
            gate_utc: str | None = gate.get("utc")
            gate_checks: list = gate.get("checks", [])
            gate_failed: list[str] = [c["name"] for c in gate_checks if not c.get("ok")]
            ctrl: dict = gate.get("control", {})
            control_ran: bool = bool(ctrl.get("ran", False))
            control_checks: list = ctrl.get("checks", [])
            control_weak: list[str] = ctrl.get("weak", [])
        else:
            gate_verdict = None
            gate_utc = None
            gate_checks = []
            gate_failed = []
            control_ran = False
            control_checks = []
            control_weak = []

        if status == "done" and commit_sha:
            commits.append(commit_sha)

        steps.append({
            "id": sid,
            "title": meta.get("title", ""),
            "verify": meta.get("verify", ""),
            "status": status,
            "attempt": attempt,
            "cost": cost,
            "commit_sha": commit_sha,
            "gate_verdict": gate_verdict,
            "gate_utc": gate_utc,
            "gate_failed": gate_failed,
            "control_ran": control_ran,
            "control_weak": control_weak,
            "gate_checks": gate_checks,
            "control_checks": control_checks,
        })

    # reconciliation.json
    recon_path = root / "reconciliation.json"
    reconciliation: dict | None = None
    if recon_path.exists():
        reconciliation = json.loads(recon_path.read_text())

    # reverify/<stamp>.json – pick the last by filename sort
    reverify_dir = root / "reverify"
    last_reverify: dict | None = None
    if reverify_dir.is_dir():
        files = sorted(reverify_dir.glob("*.json"))
        if files:
            last_reverify = json.loads(files[-1].read_text())

    return {
        "title": title,
        "target": target,
        "steps": steps,
        "total_cost": total_cost,
        "commits": commits,
        "reconciliation": reconciliation,
        "last_reverify": last_reverify,
    }


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

_VERDICT_CLASS = {
    "ACCEPT": "v-accept",
    "REJECT_CHECKS_FAILED": "v-reject",
    "CHECKS_TOO_WEAK": "v-weak",
}

_CSS = """
:root { --bg:#fff; --fg:#111; --tbg:#f5f5f5; --border:#ccc; }
@media (prefers-color-scheme:dark) {
  :root { --bg:#1a1a1a; --fg:#eee; --tbg:#2a2a2a; --border:#555; }
}
* { box-sizing:border-box; }
body { font-family:sans-serif; margin:1rem auto; max-width:960px;
       padding:0 1rem; background:var(--bg); color:var(--fg); }
h1 { word-break:break-word; }
table { border-collapse:collapse; width:100%; overflow-x:auto; display:block; }
th,td { border:1px solid var(--border); padding:.35rem .5rem; text-align:left; vertical-align:top; }
th { background:var(--tbg); }
.v-accept  { color:#1a7a1a; font-weight:bold; }
.v-reject  { color:#b00020; font-weight:bold; }
.v-weak    { color:#7a5000; font-weight:bold; }
@media (prefers-color-scheme:dark) {
  .v-accept { color:#5fd85f; }
  .v-reject { color:#ff6b6b; }
  .v-weak   { color:#ffb347; }
}
.done { color:#1a7a1a; } .fail { color:#b00020; } .not_run { color:#666; }
@media (prefers-color-scheme:dark) {
  .done { color:#5fd85f; } .fail { color:#ff6b6b; } .not_run { color:#aaa; }
}
details { margin-top:.4rem; }
summary { cursor:pointer; }
pre { white-space:pre-wrap; word-break:break-word; background:var(--tbg);
      padding:.5rem; border-radius:4px; }
.section { margin-top:1.5rem; }
form { margin-top:.5rem; }
button { padding:.4rem .9rem; font-size:1rem; cursor:pointer; }
"""


def _verdict_span(verdict: str | None) -> str:
    if verdict is None:
        return "-"
    cls = _VERDICT_CLASS.get(verdict, "")
    v = escape(verdict)
    if cls:
        return f'<span class="{cls}">{v}</span>'
    return v


def _control_cell(step: dict) -> str:
    if step["gate_verdict"] is None:
        return "-"
    if not step["control_ran"]:
        return "not run"
    if step["control_weak"]:
        names = escape(", ".join(step["control_weak"]))
        return f"checks too weak: {names}"
    return "broken copy failed every check"


def render_html(run: dict) -> str:
    """Render a self-contained HTML dashboard page for the given run dict."""
    title_safe = escape(run["title"] or "Run Dashboard")
    target = run.get("target") or {}

    # Summary counts
    done = sum(1 for s in run["steps"] if s["status"] == "done")
    fail = sum(1 for s in run["steps"] if s["status"] == "fail")
    not_run = sum(1 for s in run["steps"] if s["status"] == "not_run")
    total_cost = run["total_cost"]

    recon = run.get("reconciliation")
    if recon:
        rs = escape(recon.get("status", ""))
        rl = recon.get("ledger_total", "")
        rd = recon.get("db_total", "")
        recon_str = (
            f'<span class="{"v-accept" if recon.get("status") == "MATCH" else "v-reject"}">'
            f"{rs}</span> (ledger {escape(str(rl))}, Bob {escape(str(rd))})"
        )
    else:
        recon_str = "not reconciled"

    # Build step rows
    step_rows = []
    for s in run["steps"]:
        sc = s["status"]
        status_html = f'<span class="{escape(sc)}">{escape(sc)}</span>'
        verdict_html = _verdict_span(s["gate_verdict"])
        ctrl_html = escape(_control_cell(s))
        commit_short = escape(s["commit_sha"][:7]) if s["commit_sha"] else ""

        row = (
            f"<tr>"
            f"<td>{escape(s['id'])}</td>"
            f"<td>{escape(s['title'])}</td>"
            f"<td>{status_html}</td>"
            f"<td>{verdict_html}</td>"
            f"<td>{ctrl_html}</td>"
            f"<td>{s['cost']:.4f}</td>"
            f"<td>{s['attempt']}</td>"
            f"<td>{commit_short}</td>"
            f"</tr>"
        )

        # details element if gate result exists
        if s["gate_verdict"] is not None:
            check_rows = "".join(
                f"<tr><td>{escape(c['name'])}</td>"
                f"<td>{'✓' if c.get('ok') else '✗'}</td>"
                f"<td>{escape(c.get('detail',''))}</td></tr>"
                for c in s["gate_checks"]
            )
            ctrl_rows = "".join(
                f"<tr><td>{escape(c['name'])}</td>"
                f"<td>{'✓' if c.get('ok') else '✗'}</td>"
                f"<td>{escape(c.get('detail',''))}</td></tr>"
                for c in s["control_checks"]
            )
            details = (
                f'<tr><td colspan="8"><details><summary>Gate checks &amp; control</summary>'
                f"<strong>Checks:</strong><table>{check_rows}</table>"
                f"<strong>Control checks:</strong><table>{ctrl_rows}</table>"
                f"</details></td></tr>"
            )
        else:
            details = ""

        step_rows.append(row + details)

    step_rows_html = "\n".join(step_rows)

    # Target info
    tname = escape(target.get("name", ""))
    turl = escape(target.get("url", ""))
    tcommit = escape(target.get("commit", ""))
    tlicense = escape(target.get("license", ""))
    target_html = ""
    if tname or turl:
        link = f'<a href="{turl}">{tname}</a>' if turl else tname
        target_html = (
            f"<p><strong>Target:</strong> {link}"
            f" &mdash; pinned commit: <code>{tcommit}</code>"
            f" &mdash; license: {tlicense}</p>"
        )

    # Re-verify section
    last_rv = run.get("last_reverify")
    rv_history = ""
    if last_rv:
        rv_utc = escape(str(last_rv.get("utc", "")))
        rv_ok = "yes" if last_rv.get("all_ok") else "no"
        rv_log = escape(str(last_rv.get("log", "")))
        rv_history = (
            f"<p>Last run: {rv_utc} — all_ok: {rv_ok}</p>"
            f"<pre>{rv_log}</pre>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_safe}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{title_safe}</h1>
{target_html}
<p>
  Steps: <span class="done">{done} done</span> /
  <span class="fail">{fail} failed</span> /
  <span class="not_run">{not_run} not run</span> &mdash;
  total cost: {total_cost:.2f} credits &mdash;
  reconciliation: {recon_str}
</p>
<table>
<thead><tr>
  <th>ID</th><th>Title</th><th>Status</th><th>Gate verdict</th>
  <th>negative control</th><th>credits</th><th>Attempts</th><th>Commit</th>
</tr></thead>
<tbody>
{step_rows_html}
</tbody>
</table>
<div class="section">
<h2>Re-verify</h2>
<p>This re-runs the checks against the target. It makes no AI call and costs nothing.</p>
<form method="post" action="/reverify">
  <button type="submit">Re-verify now</button>
</form>
{rv_history}
</div>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# make_server
# ---------------------------------------------------------------------------

_reverify_lock = threading.Lock()


def make_server(
    run_dir: str,
    host: str = "127.0.0.1",
    port: int = 8080,
    reverify_fn=None,
) -> http.server.ThreadingHTTPServer:
    """Create a ThreadingHTTPServer serving the dashboard for *run_dir*."""

    root = Path(run_dir)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence default logging
            pass

        def _send(self, code: int, ctype: str, body: bytes, headers: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if headers:
                for k, v in headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                run = load_run(run_dir)
                body = render_html(run).encode("utf-8")
                self._send(200, "text/html; charset=utf-8", body)
            elif path == "/api/run":
                run = load_run(run_dir)
                body = json.dumps(run).encode("utf-8")
                self._send(200, "application/json", body)
            else:
                self._send(404, "text/plain", b"Not Found")

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path != "/reverify":
                self._send(404, "text/plain", b"Not Found")
                return

            fn = reverify_fn
            if fn is None:
                from bobverified import reverify as _rev
                fn = _rev.reverify

            reverify_dir = root / "reverify"
            reverify_dir.mkdir(exist_ok=True)
            before = set(reverify_dir.glob("*.json"))

            record: dict[str, Any]
            with _reverify_lock:
                try:
                    result = fn(run_dir)
                    if isinstance(result, dict):
                        record = result
                    else:
                        record = {"utc": _now_utc(), "all_ok": False, "results": [], "log": ""}
                except Exception as exc:
                    now = _now_utc()
                    record = {
                        "utc": now,
                        "all_ok": False,
                        "results": [],
                        "log": f"{now} error: {exc}",
                    }

                after = set(reverify_dir.glob("*.json"))
                if not (after - before):
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    (reverify_dir / f"{stamp}.json").write_text(json.dumps(record))

            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def do_PUT(self):
            self._send(405, "text/plain", b"Method Not Allowed",
                       {"Allow": "GET, POST"})

        def do_DELETE(self):
            self._send(405, "text/plain", b"Method Not Allowed",
                       {"Allow": "GET, POST"})

        def do_PATCH(self):
            self._send(405, "text/plain", b"Method Not Allowed",
                       {"Allow": "GET, POST"})

    srv = http.server.ThreadingHTTPServer((host, port), Handler)
    return srv


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI dashboard server."""
    parser = argparse.ArgumentParser(description="Serve a bobverified run dashboard.")
    parser.add_argument("--run", required=True, help="Path to the run directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    srv = make_server(args.run, args.host, args.port)
    host, port = srv.server_address
    print(f"serving {args.run} on http://{host}:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
