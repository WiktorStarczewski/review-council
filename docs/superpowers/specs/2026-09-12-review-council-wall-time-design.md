# Review Council Wall-Time Design

**Status:** Approved, with the measured additions below included by the user's request to keep looking for low-risk savings.

## Goal

Reduce elapsed time and provider-processed tokens without changing the configured
reviewers, model effort, independent discovery, full-state integration coverage, or
project verification gates.

## Measured baseline

- Fifteen substantive four-seat panels consumed 7.14 hours on the critical path.
- Invalid panels consumed 4.54 hours. Valid panels consumed 2.59 hours.
- The three certification attempts processed 197,064,705 provider tokens while only
  four calls produced accepted audited results.
- Across ordinary wallet reviews, 265 of 295 rendered prompts produced usable results.
  The optimizer is the outlier: only 3 of 21 evidence-audited seats were valid.
- Seat duration correlates with tool turns at 0.90, compared with 0.61 for processed
  tokens. Existing provider cache reuse is already 92.4-96.5 percent.
- Five failed panels continued for 14.6-45.4 minutes after the first terminal failure.
- The full local shell suite takes about 9.5 minutes. Focused suites take 8-30 seconds,
  and the large evidence fixture takes about 3 minutes.

## Constraints

- Keep Sol, Terra, Opus, and Sonnet at maximum effort. Missing either configured Claude
  model remains a blocker. Historical
  measurements retain their original 2x Opus roster label.
- Every changed hunk receives full discovery once. Every semantic component receives
  specialist and full-state integration coverage.
- Every final finding remains bound to exact source bytes. Missing assigned patch bytes,
  missing required source, stale snapshots, scope escapes, and unsupported writes fail
  closed.
- Optimizations may remove repeated deterministic work. They may not reduce reasoning
  effort, reviewer count, risk bundles, or project gates.
- Provider calls are the last certification step. Local replay and focused tests must
  pass first.

## Design

### 1. Replay provider contracts before paid panels

Keep minimized, sanitized transcripts derived from actual Codex, Grok, and Claude
sessions. Replay them through the current auditor whenever the auditor, an adapter,
the evidence renderer, or the prompt protocol changes. Key the successful replay
receipt by the relevant file hashes, CLI version, adapter, model, effort, and audit
schema. Ordinary repository reviews reuse the receipt and make no canary call.

A live canary is allowed only when a changed provider boundary cannot be established
from a recorded transcript, such as a larger model-visible batch. Run one canary per
adapter, not one per repeated seat. A failing replay or canary blocks evidence mode for
that adapter before a full panel launches.

### 2. Separate evidence integrity failures from unused exploration deviations

An invalid call never earns patch, source, plan, or citation credit. The complete
review remains usable when all required proof succeeds through other calls and the
only remaining deviations are unused read-only exploration:

- a failed or blocked lookup,
- a read-only within-scope command whose output stayed within the hard byte ceiling but
  lacked a parseable source range,
- a provider rendering mismatch on a range that supplies no required proof.

Record these as an optional `advisories` field in audit schema 2. Keep `violations`
for fatal integrity failures so existing immutable schema-2 sessions remain readable. Fatal
failures include malformed or incomplete transcripts, unknown or write-capable shell
commands, path or session-scope escapes, stale or ambiguous manifests, missing or
mismatched assigned patch bytes, missing or mismatched required source, patch-before-
context phase violations, missing plan-source coverage, and unsubstantiated findings.

For evidence-backed reviews, compare ordinary source output with the frozen manifest
blob. Never compare it with a later live worktree state. Claude's explicit numbered
blank line at the end of a requested range represents that line even when the provider
omits only its final rendering newline.

### 3. Reduce deterministic proof turns

Use the existing 60 KiB deterministic-proof ceiling for provider-calibrated batches:

- Claude may return consecutive patch chunks or required-source segments in one turn
  while their combined exact bytes remain within the ceiling.
- Codex may concatenate consecutive immutable artifacts in one `cat` call only after a
  live canary proves the exact model-visible bytes. Until then it keeps one artifact per
  call.
- Gemini remains at one artifact pending a real transcript.

For Codex source expansion, permit one shell call to concatenate independent
byte-preserving `sed -n 'START,ENDp' 'FILE'` windows separated only by semicolons.
Each window and the aggregate must select at most 240 lines, combined output stays at
or below 32 KiB, paths remain literal and in scope, and ranges may not overlap or
repeat. Reject pipelines, transforms, searches, redirects, variables, substitutions,
and conditional operators. The auditor compares the concatenated output with the same
frozen source bytes used for individual reads. Keep this behind an exact Sol canary
until the provider returns the expected command envelope and bytes.

The auditor validates the concatenation once, then credits each ordered artifact. The
bytes and coverage are identical; fewer model turns avoid replaying the growing context.

Do not align every source read to fixed 240-line blocks. Historical replay showed a
43.5 percent call reduction but an 82.5 percent increase in delivered source lines. Ask
reviewers to avoid reopening a previously read range, while preserving narrow exact
reads.

### 4. Precompute deterministic plan discovery and route cluster closure

Run each plan cluster's repository-wide sibling search once against the frozen snapshot.
Store the command contract, exit status, saturation state, exact NUL-delimited result,
and hashes in the manifest. Every reviewer receives the same immutable result and may
run additional independent searches. The result establishes the mechanical sibling
inventory; reviewers still reason independently about completeness and correctness.

Every reviewer sees the complete inline plan. Deal plan clusters across the three
specialist seats and give the full plan-completeness seat every cluster. Each cluster
therefore receives one specialist review plus the full-state review, matching the
accepted component-coverage rule used for code panels. The c3 plan would fall from
three duplicated 657 KiB specialist closures to one aggregate 657 KiB specialist
closure, while retaining the 1.32 MiB full-state owner.

### 5. Recover at seat granularity

Retain every valid seat bound to the panel's manifest. Retry only a failed assignment
against the same immutable prompt, snapshot, bundle, model, and effort. If the same
evidence failure repeats, create a full-scope child assignment bound to that parent
assignment. A panel receipt selects exactly one immutable generation per assignment
and rejects mixed snapshots, rosters, bundles, lenses, or prompt generations.

Keep one persistent provider-attempt budget per seat generation across wrapper and
orchestrator retries. The existing intended ceiling is four calls; restarting the
wrapper must not reset it. Exhaustion is terminal and explicit.

When one seat fails, start its repair while other original seats continue. Cancel
siblings only for a panel-global failure such as a stale manifest or changed snapshot.
Preserve all partial streams for usage accounting. Triage completed valid seats during
straggler time, but do not edit until the panel receipt seals.

### 6. Remove avoidable host delay

- Run focused 8-30 second tests after each edit, the 3-minute evidence fixture after a
  coherent evidence cluster, and the 9.5-minute full suite once per material tree before
  certification.
- Reuse a successful gate receipt only when source tree, command argv, lockfiles,
  toolchain, relevant environment, and output-log hash all match.
- Probe unique adapter/model/effort tuples concurrently and restore configured seat order
  in the result.
- Allow only the Codex, Gemini, and Claude CLI adapters in live dispatch. Handle Agent
  seats through the host dispatcher and preserve Grok only in historical decoders.
  Disable Claude slash commands. The complete review protocol is already in the rendered
  prompt.

### 7. Keep bounded inline specialist evidence behind its measured gate

The earlier projection estimates 13-17 percent savings from placing bounded specialist
patches and source packets in the initial prompt. Enable it only after the repaired
batched panel produces four valid reviews with no lost findings. Keep the integration
seat on audited artifact reads and retain at least 100k tokens of context reserve.

## Expected effect

- Stable repository reviews: 15-30 percent less elapsed time, with unchanged or lower
  processed tokens.
- Fix-heavy reviews with a plan panel: about 25-40 percent less plan-panel input and
  20-35 percent less total elapsed time.
- Failure-heavy self-review and certification: 60-75 percent less elapsed time and
  45-65 percent fewer processed tokens by preventing broken panels, retaining valid
  seats, and removing whole-panel retry multiplication.

The c3 Sol trace contained 136 bounded source calls in 41 consecutive runs. Packing
only already-consecutive reads under the stricter 240-line aggregate removes 48 of 223
Sol tool turns, or 21.5 percent. Byte-cap packing projects 39.9 percent. This is a
seat-level turn projection until the exact Sol canary and final panel measure adoption.

These ranges overlap and must not be multiplied. Certification compares prompt size,
evidence bytes, proof calls, tool turns, retries, and local suite time with the named
baseline. It reports wall time, accepted seats, provider calls, processed tokens, cost,
and finding yield under the active roster signature. Cross-roster differences in those
provider-dependent fields are not attributed to workflow changes alone.

## Rejected alternatives

- Lower effort, fewer reviewers, shorter risk coverage, or removal of the plan gate.
- Always-on paid canaries.
- Forced aligned 240-line reads because they increase delivered source substantially.
- More prompt-cache work before deterministic turn reduction. Cache reuse is already
  high and does not explain the critical path.
- Undocumented provider fast modes or speculative timeouts.
