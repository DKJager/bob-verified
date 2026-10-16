# Security scan

Scan run by the build session on 2026-10-16T16:15:05Z (UTC), before publication. Scope: every tracked file in the working tree (48 files at the time of the scan, plus the licence and this file; the PDF is scanned as extracted text) and the complete git history (every commit on every branch, full patches with `git log -p --all`, 23 commits). Matching is case-insensitive. The repository history was rewritten once before this scan to remove hits found by an earlier pass (test-fixture key strings and a personal default address in one source file).

## Patterns (regular expressions)

| Group | Pattern |
|---|---|
| Absolute paths | `/op[t]/`, `/hom[e]/`, `/roo[t]` |
| Host and account names | `ec2-use[r]`, `3dog[s]`, `nexu[s]`, `\bre[x]\b`, `committe[e]`, `harnes[s]`, `forema[n]`, `agentbuil[d]`, `auror[a]`, `bedroc[k]`, `\blarg[e]\b`, `\bxx[l]\b`, `joyel[y]`, `amazonaw[s]` |
| Credentials | `(?<![0-9A-Za-z])\d{12}(?![0-9A-Za-z])` (twelve-digit numbers), `\b(AKI[A]\|ASI[A])[A-Z0-9]{8,}`, `\bsk[-]`, `api_ke[y]`, `token[=]`, `BOB_API_KEY["']?\s*[=:]\s*["']?[A-Za-z0-9_-]{8,}` (the key name followed by a value) |
| Network | any dotted-quad IPv4 address |
| Model and provider names | `\b(c[l]aude|a[n]thropic|g[p]t|o[p]enai|g[e]mini|g[e]mma|q[w]en|d[e]epseek|g[l]m|k[i]mi|m[o]onshot|l[l]ama|m[i]stral|n[e]motron|n[o]va|o[p]enrouter|s[o]nnet|o[p]us|h[a]iku|g[r]ok|c[o]here|t[i]tan)\b` |

## Result

0 unexplained hits. Counts exclude this file. Raw matches were all reviewed and fall into these documented groups:

- IPv4 addresses (106 lines): only 127.0.0.1 and 0.0.0.0 (local test servers and the container bind address). Any other address would have been reported.
- The identifier api_ke[y] (68 lines): variable and test names such as "does not leak api key". Zero lines contain a key value; the key-with-value pattern matches only clearly labelled fake test fixtures (6 lines, values beginning "fake-").
- The company name, which is also the team name in the pitch, script and submission text (6 lines), intentionally public.
- The owner's git author identity in commit metadata (46 lines), needed so the commits are attributed to the owner.

No credentials, account numbers, internal hostnames, internal paths or other AI model names were found in any file or any commit. No credentials are contained in the repository or in its history.
