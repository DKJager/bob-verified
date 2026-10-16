# Demo video script (under 3 minutes)

Target length 2:45. Screen: dashboard in a browser, then a terminal for two short moments.

**0:00 to 0:20. The problem.** "AI agents can modernize legacy code quickly. The hard part is trusting that each step really worked. I am Alan Finney of 3Dogs Nexus, and this is Bob, verified: a layer that lets you hand a legacy codebase to IBM Bob and get a modernization you can trust."

**0:20 to 0:50. How it works.** Show the README stages. "Bob plans in plan mode, at most three steps, each with one verification command. Bob then implements one step at a time. After every step an independent gate runs that step's check and the app's smoke checks. Then it does something unusual: it runs the same checks on a deliberately broken copy. If the checks still pass on broken code, they are too weak, and the step is refused."

**0:50 to 1:30. The recorded run.** Open the dashboard. "The target is simple_api, a 2017 Flask todo service that no longer starts on current Flask. Bob's plan has three steps. Step one makes it run on Python 3.12. Step two fixes the database layer and a real bug. Step three adds nine tests. All three were accepted. Open any step: the broken copy failed every check, four out of four. Total cost 2.25 credits, and the ledger matches Bob's own task store exactly."

**1:30 to 2:00. The gate says no.** Terminal: show the saved rejection. "Here I put the old broken import back. The gate rejects it: the step check, the tests, the server start and the URL all fail. A step that claims success without working does not get in."

**2:00 to 2:30. Re-verify.** Back in the dashboard press Re-verify now. "No AI call, no cost. It re-runs every check against the modernized app and writes a timestamped log. All accepted."

**2:30 to 2:45. Close.** "Bob wrote the gate, the ledger, the dashboard and this modernization, from tests we wrote first. The runner was ported from our own 15 October version and is credited as such. The primary contribution is the verification layer. Thank you."
