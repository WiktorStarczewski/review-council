# Native Pi /rev

## Intent and scope

Add first-class Pi hosting for Review Council, installed in one command and invoked as `/rev`. The author authorized proceeding with `/rev` only. Stack hosting, new reviewer transports and provider credential migration are out of scope.

## Approaches

A native Git package is preferred to a copying shell installer: Pi owns installation, updating and removal without a second package manager. A root package manifest exposes one small command extension and one uniquely named Pi skill. Existing shared `rev` skills must not shadow this package's workflow.

## Design

- Install with `pi install git:github.com/WiktorStarczewski/review-council`, optionally pinned to a release tag.
- Register only `/rev`. Forward arguments unchanged as review scope, not shell code. Help and setup diagnostics are `/rev --help` and `/rev --setup`, not additional commands.
- Resolve the bundled runtime from the installed extension, never the reviewed checkout or another host's installed plugin.
- Generate a Pi-specific skill and phase files from the canonical Codex review contract, with drift checks. Use the name `review-council-rev` to avoid shared-skill collisions.
- Explicitly bind all runner invocations to `REVIEW_COUNCIL_HOST=pi`. Pi has no implicit Anthropic Agent fallback. Use existing external reviewer and writer transports with unchanged evidence, effort, recovery, receipt and publication requirements.
- Pi core lacks subagents and persistent execution handles. Keep orchestration in the active session; run CLI seats through bash with durable PID/exit/log files and bounded polling. Do not invent subagent tools or silently switch orchestration hosts. Preserve user authorization and report incomplete reviews truthfully.
- Setup checks report required tools and explain separate provider CLI authentication without model calls or secret access. No automatic provider installation or sign-in.
- Existing Claude, Codex and Cursor installs remain unchanged. Release manifests and the Pi package version stay aligned.

## Acceptance

Tests exercise command registration, argument preservation, busy/nested rejection, installation-relative paths, help/setup without model calls, generated contract drift, Pi roster/workhorse host behavior and phase routing. CI runs all existing deterministic gates plus Node extension tests and actual Pi loader discovery. An independent normal reviewer checks completed code; Council self-review is prohibited. Merge only after current-head required checks, then publish a signed release and install that release here. No stack command or skill is exposed.
