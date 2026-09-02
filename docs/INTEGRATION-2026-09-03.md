# Live integration — 2026-09-03 (spec §10)

Machine: macOS, codex-cli 0.152.1 (ChatGPT login), grok 1.0.13 (grok.com session), no Gemini CLI, Claude Code 2.1.258.

| # | Check | Result | Evidence |
|---|---|---|---|
| U | unit suite | PASS | `run-tests.sh` 800/800 locally; CI green on macos-latest and ubuntu-latest (runs 33689097203, 33689186757) |
| V | `claude plugin validate --strict` | PASS | marketplace + plugin manifests |
| L1 | install from local marketplace; session banner | PASS | hook injected the policy block and `review-council seats: codex ✓ (gpt-5.6-sol@max, gpt-5.6-terra@max) · grok ✓ (grok-4.6@xhigh) · gemini ✗ not installed · claude ✓ (opus@max)`; `claude -p "/review-council:rev …"` resolved the skill (`LOADED codex, grok, gemini, agent`). First banner after install showed grok as a sign-out from a transient status failure → detector now retries once and reports `status check failed: …` distinctly |
| L2+L3 | one detached `stack.sh` leg driving `/review-council:rev branch 1` on a planted fixture | PASS | roster.json = codex-sol, codex-terra, grok, opus + codex-review, grok-code-review (gemini excluded: not installed); 3 rounds, all four base seats found both plants in round 1; `report.md` 9.5 KB; 0 stall kills; 6 status ticks; orchestrator collapsed 3 review commits → `e786e13d3 apply review findings`; `(NO_PUSH=1: not pushing)`; fixture ends at jest 12/12 |
| L4 | reinstall from GitHub (`marketplace add zoroswap/review-council`) | PASS | cache identical to HEAD; banner identical |
| L5 | Gemini seat | NOT RUN | no Gemini CLI on this machine; adapter fixture-tested only (see README caveat) |

Note for local iteration: `claude plugin update` is version-gated; uninstall + reinstall to refresh the cached copy without a version bump.
