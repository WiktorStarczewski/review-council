# Pi Council Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent Council footer and session-wide ECO/HIGH selection, with `/council` starting reviews.

**Architecture:** Extend `pi/rev.mjs` using Pi command, session-entry and prompt-section APIs. Reuse the existing panel-request parser through explicit default-mode instructions; retain `/rev` as a compatibility alias and preserve frozen review rosters.

**Tech Stack:** JavaScript ES modules, Node built-in test runner, existing Pi extension APIs.

**Spec:** `docs/superpowers/specs/2026-11-12-pi-council-mode-design.md`

## Global Constraints

- No Ponytail dependency, new package dependencies or permanent roster-config writes.
- Footer text is `⚖  council: 🌿 ECO` or `⚖  council: 🔥 HIGH`, with exactly two spaces after `⚖`; assert this spacing in the status tests.
- ECO is the existing four-Luna normal preset; HIGH is the existing Opus/Sol/Sonnet/Luna preset.
- Selection affects new reviews only; explicit per-review instructions override the default without changing it.
- `/council` starts a review; exact mode subcommands only select a mode.
- Keep `/rev`, help/setup, unchanged request arguments and busy/nested review guards.
- Use guarded local checks; no Council self-review. Do not claim visual verification without observing Pi rendering.

## Review Focus

- Missing Ponytail: Council status still renders under Council's own key.
- New/resumed/tree-selected sessions: no mode leakage from a previous branch or session.
- Conversational/direct-skill reviews: selected default reaches agent context, not just slash-command text.
- Explicit review overrides and initialized reviews: preserve caller selection and frozen rosters.
- Busy sessions, headless UI, malformed persisted values and invalid command arguments: no accidental review launch or crash.

---

### Task 1: Implement and test the session control

**Files:** Modify `pi/rev.mjs`, `tests/pi-rev.test.mjs`.

**Interfaces:** Existing default extension factory consumes `pi`; register one shared review handler for `council` and `rev`, subscribe to session lifecycle and `before_agent_start`, persist `review-council-mode` entries containing `{ mode: 'eco' | 'high' }`.

- [ ] Read complete relevant Pi extension documentation and lifecycle/state/status examples before editing. Inspect parser and all extension callers. Create an isolated implementation worktree; leave existing untracked `package-lock.json` untouched.
- [ ] Extend the existing harness with event handlers, session branch entries, append-entry recording, themed status recording and structured prompt sections.
- [ ] Add failing tests: bare `/council` sends one review request; `/rev` remains equivalent; ECO/HIGH changes append one valid session entry, update status and send no review; status/help/setup start no review; autocomplete offers modes.
- [ ] Add failing tests: default ECO status without Ponytail; HIGH restore across startup/reload/tree; new session ECO reset; malformed entries ignored; headless operation safe; busy/nested reviews still refused; scope arguments preserved byte-for-byte.
- [ ] Add failing tests: selected default is present in structured agent context and review command messages, with existing parser-compatible `mode: normal` or `mode: high` instructions; explicit review overrides and frozen-roster precedence stated; fallback prompt injection works when structured sections are unavailable.
- [ ] Run `~/.codex/bin/ci-local run -- node --test tests/pi-rev.test.mjs` in the worktree and confirm the new behavioral assertions fail for the intended reason.
- [ ] Implement the minimal shared handler, mode restore/persistence, independent footer, autocomplete and session-default prompt section in `pi/rev.mjs`. Preserve all existing diagnostics and review protections.
- [ ] Rerun the same focused test through `ci-local`; require a nonzero passing test count and no failures. Inspect the diff for accidental provider/config changes.
- [ ] Commit the feature and tests with the user's identity, without attribution trailers.

### Task 2: Document, inspect and install the completed change

**Files:** Modify `docs/pi.md`, `README.md`; inspect `tests/check-pi-package.py` and `.github/workflows/pi-package.yml` for command-name assumptions. Update a loader assertion only if it requires `/rev` to be the sole command.

**Interfaces:** Task 1's commands, status and session entries are the public Pi behavior; no new runtime interface.

- [ ] Update Pi usage to lead with `/council`, document ECO/HIGH/status, `/rev` compatibility, session persistence and Ponytail independence; preserve other hosts' examples.
- [ ] Run focused guarded extension tests and generated-skill drift checks if touched. Use repository CI for heavier gates, with exact revision and a live watcher if dispatched.
- [ ] Obtain one independent normal code review if available, never Council self-review; otherwise disclose that the reviewer capability is missing. Resolve actionable source-backed findings and rerun affected checks.
- [ ] Install the verified change into the active package without overwriting unrelated user files. Verify package identity and explain any release-pin/update implications; do not silently change shared provider settings.
- [ ] Observe a real Pi footer with Ponytail absent and both modes selected, plus reload restoration, before calling it visually verified. If the current toolset cannot control or capture the TUI, state that limit and give `/reload` plus the exact commands for the user to check.
- [ ] Record final tested revision, executed test counts and unverified limits; commit documentation separately as appropriate.

## Plan self-review

All requested behavior is covered by Task 1 tests and Task 2 documentation/installation. No shared Python roster change is needed because both presets already exist. Explicit overrides preserve the installed parser's precedence. Native execution is recommended: the change is one small extension and its harness, and this Pi session has no subagent tool.
