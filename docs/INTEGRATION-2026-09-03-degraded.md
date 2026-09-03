# Live integration — degraded (Claude-only) panel, 2026-09-03

Plugin 0.1.2 installed from GitHub. Config `{"exclude": ["codex", "grok"]}` (no Gemini on the machine), so the roster had a single lab.

| Check | Result | Evidence |
|---|---|---|
| Roster | PASS | `opus`, `claude-1` (padded), `claude-2` (padded); `degraded: true`, `degradation: "only Claude is available — 3 Claude seats, no cross-lab decorrelation"`; banner carries `DEGRADED: …`; exit 0 |
| One detached `stack.sh` leg, `/review-council:rev branch 1` on a planted fixture | PASS | 3 rounds in 65 min; all three Claude seats found the plants in round 1; 5 fixes; `report.md` opens with `Degraded panel: …` and Coverage quotes the degradation sentence verbatim and lists the padded seats and the config exclusions; 0 stall kills; orchestrator collapsed 3 review commits → `9308fd038`; `(NO_PUSH=1: not pushing)`; fixture ends at jest 14/14 |
| `min_labs: 2` with one real lab | PASS (unit + direct) | roster exits 5 with `strict: 1 lab(s) available, min_labs=2` even though padded Claude seats are present |
| Status line robustness | FIXED in 0.1.3 | one tick printed an empty status field when the status script produced nothing; now reported as `(status unavailable — see status.err)` with stderr kept; negative `idle` clamped |
