# rev — live integration results

Date: 2026-09-02 · codex-cli 0.152.1 (ChatGPT login) · grok 1.0.13 (grok.com session) · claude 2.1.258
Fixture: branch `rev-selftest` (worktree /Users/celrisen/miden/miden-wallet-rev-selftest), planted off-by-one in `clamp.ts:4` + vacuous test in `clamp.test.ts:6`.

| # | Check | Result | Evidence |
|---|---|---|---|
| T1 | preflight on `main` | PASS | exit 1: `preflight: HEAD is on shared branch 'main' — cut a working branch first` |
| T2 | preflight `--write` on `rev-selftest` | PASS | exit 0; base f95c485…, 4 seats (sol@max, terra@max, grok@xhigh, opus@max); scope.env + files.txt written |
| T3 | codex-sol (r5, clean run) | PASS | exit 0, 2 findings: clamp.ts:4 P1 + clamp.test.ts:5 P1 |
| T3 | codex-terra (r5, clean run) | PASS | exit 0, 2 findings: clamp.ts:4 P1 + clamp.test.ts:6 P1 |
| T3 | grok (r1) | PASS | exit 0, 6 tool calls, 3 turns, 2 findings: clamp.ts:1 P1 + clamp.test.ts:4 P1 |
| T3 | opus (r1, rev-reviewer agent) | PASS | JSON validates, 2 findings: clamp.ts:4 P0 + clamp.test.ts:5 P1 |
| T3 | codex-review (r2, native prompt → converter) | PASS | exit 0 after converter; see line below |
| T3 | grok-code-review (r3) | PASS | exit 0, 2 findings: clamp.ts:1 P1 + clamp.test.ts:4 P1 |
| T4 | bogus effort | PASS | `grok --effort bogus` → exit 2 (CLI rejects, no output) |
| T9 | status line mid-fan-out | PASS | `r1/2 collect \| sol: running 3m ← git log --oneline --deco \| terra: running 3m ← git diff --name-status f \| grok: running 3m ← grep \| opus: done 2f 3m \| cx-rev: pending \| grok-cr: pending \| open P0:0 P1:0 P2:0 fixed 0` |

Notes: the first codex-sol/terra r1 runs produced valid JSON but no `.exit` because the wrapper was edited in place while they ran (bash lazy-reads scripts) — re-run cleanly as r5. Three defects found live and fixed: `grok -p --prompt-file` is a usage error; `codex exec review` takes no `-s`, no custom prompt, and ignores `--output-schema` (converter added); the unit-test runner did not tally subshell test bodies.
| T3 | codex-review findings | PASS | P2 src/lib/rev-selftest/clamp.ts:4; P2 src/lib/rev-selftest/clamp.test.ts:5 |
| T10 | Monitor status event relayed | PASS | event arrived at 16:05 from the seat-test session's monitor and was relayed verbatim; monitor stopped via TaskStop afterwards |
| T5 | round 1 (`/rev branch 2` from this session) | PASS | 4/4 seats returned valid JSON; F-001 (upper bound) + F-002 (vacuous test) unanimous; fixed; jest 4/4, eslint clean, tsc = baseline 38; commit 88ffec41a |
| T5 | round 2 grok seat | HARDENED | grok answered on turn 1 with zero tool calls ("I'll inspect the diff…", 0 findings). Wrapper now retries once then fails the seat; unit test t-grok-notools.sh; seat re-run live |
| T5 | full `/rev branch 2` loop | PASS | 3 rounds (min 2 + two consecutive clean rounds); F-001/F-002 P1 fixed r1, F-003/F-004 P3 pinned r2/r3; jest 6/6, eslint clean, tsc = baseline; `rev-squash.sh --apply` collapsed 3 commits → e458b0579 "apply review findings"; push skipped; report.md written; 2 Monitor ticks relayed |
| T9 | status line during the loop | PASS | ticks at collect/verify phases rendered every seat incl. opus's last tool from its transcript |
| T7 | `REV_ACTIVE=1 claude -p "/rev branch 1"` | PASS | refused: "A review is already running here. `REV_ACTIVE=1` was set…" (3 turns, no seats launched) |
| T7 | `REV_STACK_LEG=1` / `REV_ACTIVE=1` `rev-stack.sh` | PASS | both exit 1: "rev-stack: refusing to nest" |
| T6 | headless stack leg (attempt 1) | KILLED (harness) | orchestrator ran inside a background Bash command; harness killed it after ~56 min mid round 3; stall detector never fired (cpu moving). Fixed: self-detach; re-run below |
| T6 | headless stack leg (attempt 2, detached) | INCOMPLETE → FIXED | leg resumed from its ledger through round 4, then ended its turn "waiting for the gate notification" — print mode delivers none (0 task-notifications across 5 background launches) → `claude -p` returned success mid-round: no report.md, round-4 edits uncommitted. Fixes: SKILL stack-leg rules (foreground polling, never end a turn while work is pending, report.md before the final message) + rev-stack treats exit-0-without-report as incomplete and retries with resume (unit-tested). Re-run pending |
| T8 | `REV_STACK_LEG=1` leg + orchestrator finish | PASS | leg made per-round commits and no push; `finish_repos` collapsed 3 commits → 82aaaa89f "apply review findings"; `(NO_PUSH=1: not pushing)`; `origin/rev-selftest` absent |
| FR | final whole-deliverable review via read-only `/rev` panel (4 seats over 32 files) | PASS (fixed) | 26 findings: 21 fixed in one wave (scope.env quoting, allowlist Bash guard, classifier ignores model text, NaN validation, squash index/pattern safety, stack failure semantics + auth check, ledger-preserving resume, extra-seat prompts, path/untracked scope, effort ladder from the cache, codex-review sandbox pin, preflight fallbacks, shim env assertions, converter path parsing, stall race, runner early-exit, read-only code scopes, deleted-path scope); 5 rejected with reasons; scoped re-review left A2 open on 4 proven bypasses → closed by the controller with t-guard2 (30 blocked / 33 allowed); suite 528/528 |
| T6 | headless stack leg (re-run under fixed scripts, detached) | PASS | `=== DONE wallet pass1 exit=0` (4206s, 4 rounds, 16 fixes, report.md 8 KB, 4 round blocks in findings.md); 0 STALLED; 7 `[status]` ticks; leg polled seats in the foreground per the new stack-leg rules |
| T8 | orchestrator finish (re-run) | PASS | 4 review commits collapsed → ed1d1e2f6 "apply review findings"; `(NO_PUSH=1: not pushing)`; `origin/rev-selftest` absent; jest 118/118 on the leg's final fixture |
