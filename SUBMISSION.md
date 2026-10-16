# Submission: Bob, verified

**Track:** Modernize What Matters

**Description (98 words):**
Bob, verified lets a team hand a legacy codebase to IBM Bob and trust the result. Bob plans the modernization, then implements one step at a time. After every step an independent gate runs the step's check and the app's smoke checks, then repeats them on a deliberately broken copy; checks that cannot tell working from broken are refused. Costs are reconciled against Bob's own task store, and a dashboard shows plan, verdicts, credits and commits, with a zero-cost "re-verify now". On a real 2017 Flask app Bob modernized three steps, all gated and accepted, for 2.25 credits.

**Tech stack:** Python 3.12 (standard library only at runtime), IBM Bob Shell (plan and agent modes), git, pytest, Flask, Flask-RESTful and SQLAlchemy (installed inside the demo target only), systemd or Docker for deployment.

**Improvements made during the hackathon period (16 to 18 October 2026):** the entire repository: the verification gate with negative control, the ledger reconciliation, the wiring from plan to runner, the run dashboard with re-verify, the target fetch script and the deployment files. Only the task runner was ported, from a version the team wrote on 15 October (not by Bob); see docs/BUILD_HISTORY.md.

**Live demo:** https://18-216-235-168.sslip.io/
