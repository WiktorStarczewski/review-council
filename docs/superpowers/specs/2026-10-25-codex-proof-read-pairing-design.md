# Pair bounded Codex proof reads within one turn

## Intent

Reduce reviewer wall time spent on repeated bounded proof reads while preserving the exact evidence and audit requirements. The next large-batch Luna run should spend fewer model turns reading the same assigned patch chunks and required source segments, without changing the human review scope.

## Evidence

The preserved #1830 Luna plan attempt on 0.8.4 completed with a valid read audit, 62 tool calls, 39 source-read calls, and 23 required source segments. The current protocol allowed one Codex proof read per turn, so every required artifact needed its own turn. Release 0.8.9 memoizes repeated source-context reconstruction during preparation, but does not reduce reviewer proof-read turns.

Compound shell source batches are retired. A preserved mutation-and-restore reproduction showed that joined output can be credited to the wrong source path even when the source tree is restored before audit. This design does not use compound shell commands or concatenated output.

## Proposed behavior

Allow a Codex reviewer to issue up to two separate, ordered proof-read tool calls in one model turn. Each call reads exactly one assigned immutable artifact through the existing native `cat -- <path>` action. The auditor binds each call and its output to its own path and exact expected bytes, then verifies the existing artifact order.

Keep compound commands disabled. The reviewer must not combine paths, ranges, reads and searches, or commands with `&&`, `;`, or a source-batch payload. A pair is valid only when both calls are independently recognized, consecutive in the required order, and within the existing per-response and combined turn byte ceilings. A single oversized one-line segment is always read alone.

The pairing limit applies only to ordered patch-chunk, required-source-segment, and evidence-index reads. Source-context packets keep their current one-packet limit. Repository expansion calls, mandatory proof obligations, evidence scope, output caps, review budgets, and provider escalation remain unchanged.

## Goals

- Reduce Codex proof-read turns for large assignments by pairing consecutive independent reads.
- Preserve exact per-path source identity, byte matching, read order, and fail-closed behavior.
- Keep each output below 32 KiB and each ordered proof turn within the existing 60 KiB ceiling; ordinary source-context packets retain their 32 KiB turn limit.
- Measure actual savings on the already-authorized matched #1830 Luna replay after its merge. Do not make a speed claim from synthetic transcripts alone.

## Non-goals

- Re-enable compound shell or native joined-output source batches.
- Change manual review scope, locale or copy policy, repository expansion budgets, mandatory reads, or proof limits.
- Edit or re-review the Wallet PR from this Council session.
- Claim Review Council issue #77 is resolved before the fresh post-0.8.9 failure-rate evidence is below 5%.

## Acceptance

- Offline transcript regressions prove two separate exact reads in one Codex turn and reject reordered, repeated, missing, oversized, or over-limit reads.
- Existing compound-shell and mutation-restoration regressions continue to reject source credit.
- Current full CI and the required independent normal review pass on the exact candidate head.
- A matched post-merge #1830 replay records runtime identity, first-attempt audit results, read-call and tool-turn counts, and preparation and reviewer wall time separately. The replay retains the Sol run's exact source tree and human scope.
- No performance or reliability claim is made until that replay and the post-0.8.9 audit denominator support it.

## Calls left to the implementer

The implementation chooses the smallest existing metric and transcript changes needed to enforce and report the two-call limit. It must not weaken byte, path, ordering, mutation, or completion checks to make a batched transcript pass.
