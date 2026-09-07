# Changelog

## 0.2.2

- The `simplicity` lens is rewritten from a two-case held-out evaluation (`docs/simplicity-lens-eval-2026-09-06.md`): the burden of proof sits on each new mechanism; native engine or framework features over hand-rolled ones; proportionality to the named consumer; one value or one implementation means no parameter and no generic; migrations from schemas created on the same unreleased branch fold into the original; public surface follows the file's re-export convention; test axes, helpers and divergence tests must still have two sides; consistency with siblings is not a justification. Structural recall on the held-out cases went from 1/3 and 1/5 to 2/3 and 3/5 with no case-specific wording.
- `REV_SEAT_OFFLINE=1` at prompt-render time adds an offline paragraph to every seat prompt for blind evaluations: no network, no other checkout, no published versions of the repository's own packages, no whole-registry searches.

## 0.2.1

- Preflight no longer assumes the change was cut from `origin/HEAD`: the base is `--base <ref>` (or `REV_BASE_REF`), else the open PR's base via `gh`, else the nearest fork point among the default branch, `next`, `develop`, `dev` and `release`. A branch cut from a `next` line was previously reviewed with everything `next` carried past `main`. `scope.env` gains `REV_BASE_BRANCH`, the preflight line prints `base_branch=<name> (<how>)`, and HEAD sitting on the chosen base is refused like any shared branch.

## 0.2.0

- The fix-plan gate: triage now clusters accepted findings by root cause, and after round 1 (and any later round that accepts a P0/P1 or opens a new cluster) the orchestrator writes `fix-plan.md` — one rule per cluster with every site, branch, realm and doc copy enumerated by search, what it must not break, and the test that fails without it — and the same seats review the plan before any code is written. Fixes then land one cluster per commit with every listed site in it.
- `rev-prompt.sh --plan <file>` renders the plan-review prompt; four plan lenses (`plan-completeness`, `plan-soundness`, `plan-simplicity`, `plan-tests`) are dealt like any round's. Every seat's `suggested_fix` must now state the general rule and its sibling sites, not a patch for the cited line.
- A `simplicity` lens leads round 1: a checklist for shrinking the change by reuse — workarounds whose stated reason no longer holds on the pinned dependency, parameters every caller passes identically, forwarding-only wrappers, single-value test axes — accepted at triage only with the existing symbol named at a location and version; scope cuts are deferred to the author.
- Why: measured over 11 past runs, 56% of findings were fixes of an earlier round's fix (68% from round 5 on), 55% of them incomplete fixes. `docs/churn-analysis-2026-09-06.md` has the numbers and method.

## 0.1.3

- Stack: a blank or failing status script is reported on the status line (`(status unavailable — see status.err)`) and its stderr is kept, instead of an empty field; `idle` can no longer print negative when a file mtime runs a second ahead of the clock.

## 0.1.2

- Graceful degradation: a machine with fewer than three seats is no longer refused. The roster pads the panel up to three with Claude seats (`claude-1`, `claude-2`, … , each dealt its own lens) and marks itself `degraded` with a one-sentence reason, which the session banner, preflight's `WARNING` line and the report's `Degraded panel:` opener all carry. A Claude-Code-only machine can now use the plugin.
- `min_labs` (default 1) is the opt-in hard floor that brings the old refusal back: below it the roster exits 5 with `strict: <k> lab(s) available, min_labs=<N>` and preflight stops the run.
- `roster.json` gains `labs`, `padded` and `degraded` (plus `degradation` when degraded), and padded seats carry `"padded": true`.

## 0.1.1

- Installing through `install.sh` now turns on auto-update for the review-council marketplace, so new releases arrive on their own; `--no-auto-update` (or `REVIEW_COUNCIL_NO_AUTO_UPDATE=1`) opts out and leaves `settings.json` untouched.
- The plugin's version lives only in `plugins/review-council/.claude-plugin/plugin.json`; the marketplace entry no longer pins one, where it would silently have overridden the manifest.
- Opt-in update notice: with `check_updates: true` in the config, the session banner adds one line when a newer version is published. Off by default, cached for a day, and silent on any failure.

## 0.1.0

- Initial release: `/review-council:rev` multi-model review-and-fix loop and `/review-council:stack` cross-repo orchestrator, ported from the in-harness `rev` skill.
- Roster built at run time from whichever of the Codex, Grok, Gemini and Claude (Opus) seats are installed and signed in, instead of a hardcoded seat list.
- `SessionStart` hook injects the standing review policy and a one-line roster summary every session.
- Portable across macOS and Linux; shimmed unit test suite with no network access, run in CI on both platforms.
