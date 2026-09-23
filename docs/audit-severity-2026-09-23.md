# Read-audit severity: conduct costs credit, not the panel

Status: accepted after one read-only panel, 2026-09-23. Target: 0.5.2.

## Problem

A seat whose read audit has any fatal code is a hard evidence-audit failure. The rev contract
then stops the whole panel, forbids a paid retry and a coverage repair, and latches the session.
Recovery means a new session and a re-run of every panel so far.

Every code outside `ADVISORY_CODES` (`scripts/lib/review-read-audit.py:23`) is fatal. Some of
those codes describe how a seat read, not whether its review can be trusted and shown complete. On
one 14-file web-sdk pull request, 3 of 7 codex launches across three fresh runs failed hard, each
on a different code:

| Run | Seat | Fatal codes | Cause |
|---|---|---|---|
| 1 | codex-terra | unsupported-shell-shape, unsupported-source-batch, missing-required-source-read | auditor gaps, fixed in 0.5.1 |
| 2 | codex-sol | tool-output-too-large, tool-turn-output-too-large | `rg ... dist/ \| head -80` returned about 1 MB of minified lines |
| 3 | codex-terra | path-outside-scope | `ls -d` and bounded reads of the pinned crate under `~/.cargo/registry/src`, which prompt step 6 invites |

## Rule

Fatality is mechanical: an audit whose codes are all in `ADVISORY_CODES` is valid, and any other
code makes it invalid. `ADVISORY_CODES` is the only classification. This document explains its
contents, but the set in the code is what counts.

A code stays fatal when it means one of these:

- the review cannot be shown complete;
- the transcript, prompt, or result cannot be trusted as this seat's own independent work (for
  example, the seat read another seat's prompt or result);
- the audit cannot see what a tool call did (an opaque program, an unresolvable path, a tool call
  with no command or path).

A code becomes an advisory only when it is pure conduct (size or pacing) on a call whose effect the
audit can see in full.

### Credit rule (new, enforced)

A call that raises any violation, fatal or advisory, earns nothing. It gets no source range, no
patch-chunk, packet, segment, or evidence-index proof, and no citation. Pacing codes are the one
exception, described below. `direct_source_range` is capped at `READ_LINES`, as `limiter_range`
already is.

The rule matters for size codes. An oversized output may not have reached the model in full,
because providers truncate what they show. The bytes in the transcript do not prove the model read
them. With this rule, softening a code can never make an incomplete review complete, because
completeness still has to be proved by calls that raise no violation.

Pacing codes (`patch-chunk-batch-too-large`, `required-source-segment-batch-too-large`,
`evidence-proof-batch-too-large`, `source-packet-batch-too-large`) are counted after the fact,
over reads that were each byte-proved on their own. A pacing code does not remove credit from
those reads. It is the only exception to the credit rule.

### Safety ordering

`shell_violations` runs `READONLY_POLICY.validate(command, allow_source_batch=True)` before the
redirection, parse, and batch checks. So a refused program (a `python3` heredoc, `cat x; python3 -c`)
always reports `unsupported-shell-command` and cannot hide behind a shape code.

### Pinned dependencies

`path-outside-scope` stays fatal. It is the admission control against reading secrets. The
sanctioned root for pinned dependency source is `REV_DEPS_DIR`, which the audit already honours
(`allowed_roots`). If the reviewed repository has a `Cargo.lock` and `REV_DEPS_DIR` is unset,
preflight records `$CARGO_HOME/registry/src` (default `~/.cargo/registry/src`) in `scope.env`,
provided that directory exists. `rev-seat.sh` exports it for every seat. Prompt step 6 names that
directory as the only place for pinned-dependency reads. Run 3's reads fall inside it.

## Classification

Stays fatal (unchanged or confirmed):

- Transcript integrity: missing-transcript, malformed-transcript, unsupported-transcript-shape,
  missing-tool-call-id, missing-tool-output, duplicate-tool-call, duplicate-tool-output,
  orphan-tool-output, invalid-tool-call-shape, invalid-hook-payload, no-recognized-review-tools.
- Binding: missing-prompt, invalid-prompt-artifact-set, invalid-evidence-manifest-declaration,
  invalid-assignment-prompt-binding, invalid-plan-prompt-binding, invalid-plan-evidence,
  invalid-plan-first-call, invalid-source-context, invalid-required-source-identity,
  invalid-review-result.
- Completeness: every missing-, partial-, reordered-, redirected-, and unassigned- chunk, packet,
  segment, and range code; assigned-patch-output-mismatch, source-packet-output-mismatch,
  required-source-output-mismatch, missing-plan-cluster-search, missing-plan-cluster-source,
  unsubstantiated-finding-range, invalid-plan-finding-range.
- Independence and scope: unnamed-session-artifact, path-outside-scope, unresolved-path-variable.
- Visibility and safety: unsupported-shell-command, unrecognized-review-tool,
  unsupported-shell-input-redirection, unsupported-shell-shape, missing-read-path,
  missing-shell-command, ambiguous-assigned-patch-read.

Becomes an advisory, joining the current set. Under the credit rule, each of these earns nothing
for its call:

- Size: tool-output-too-large, tool-turn-output-too-large, unbounded-read, unbounded-search.
- Batch conduct: unsupported-source-batch, source-batch-lines-too-large,
  overlapping-source-batch, source-batch-output-mismatch. The last is the batch form of the
  existing advisory source-output-mismatch.
- Pacing: patch-chunk-batch-too-large, required-source-segment-batch-too-large,
  evidence-proof-batch-too-large, source-packet-batch-too-large.

The mixing rule does not change: when any fatal code is present, every code is reported as a
violation and `advisories` is empty.

An exhaustive catalog test lists every code the auditor can emit: `violation(...)` literals plus
`SourceBatchBlocked` codes. It requires each code to be in `ADVISORY_CODES` or in a documented
fatal list in the test file. A new code with no classification then fails the suite.

## Incidents under the new rule

- Run 2: tool-output-too-large and tool-turn-output-too-large become advisories. The oversized
  call earns nothing. The seat is valid only if its other calls prove completeness.
- Run 3: with `REV_DEPS_DIR` set to the registry, the registry reads are in scope. The `ls -d` glob
  must resolve inside that root, or the implementation must treat a listing (`ls -d`, no content
  output) there as in scope.
- Run 1: already fixed in 0.5.1.

## Contract text

In both SKILL.md copies, replace the advisory sentence and the "oversized" and "unparseable"
clauses in the same paragraph with:

> A seat's evidence read audit with status `invalid` is a hard evidence-audit failure. A valid
> audit may carry advisories: these never discard the review, stay visible in the receipt, and
> never earn credit. A call that raises any violation, except a pacing count, proves no range, no
> patch chunk, packet or segment, and no citation.

Prompt step 6 names `REV_DEPS_DIR` (when set) as the only directory for pinned-dependency reads.

## Tests (test-first, synthetic)

The tests are synthetic transcripts in `t-read-bounds.sh` style, modelled on the incidents. Each
test parses the audit JSON and asserts `status`, `violations`, and `advisories` exactly. No test
relies on substring greps.

1. For each newly advisory size or batch code: the violating call is the only read of a required
   range. Expect invalid with the matching completeness code in `violations`, and the advisory
   code also in `violations`. A sibling transcript adds a clean read of that range. Expect valid,
   with the code only in `advisories`.
2. The credit rule on every proof surface: an oversized or batch-violating read that is the only
   proof of a patch chunk, a packet, a required segment, or a citation leaves that proof missing.
   A Read of 2000 lines earns at most `READ_LINES` lines.
3. Pacing: an over-limit batch of individually exact chunk or segment reads is valid, with only
   the pacing code in `advisories`. The same batch with one chunk altered is invalid with the
   completeness code for that evidence type.
4. Mixed codes: a fatal code plus an advisory code gives `status` invalid, both codes in
   `violations`, and `advisories` empty.
5. Safety ordering: a `python3 - <<'PY'` heredoc, an unparseable command containing an
   interpreter, and a batch containing `python3 -c` each report `unsupported-shell-command`.
6. Independence stays fatal: reading a sibling `r<N>-<seat>.json`, a sibling prompt, or
   `findings.md` gives unnamed-session-artifact, and the audit is invalid.
7. Dependencies: a bounded read under `REV_DEPS_DIR` is valid. The same read under another home
   directory path gives path-outside-scope (fatal). Preflight writes the registry root to
   `scope.env` only when `Cargo.lock` exists.
8. Catalog: every emitted code is classified.

Mutation check: re-hardening or over-softening any single code, or removing the credit guard,
fails at least one test.

## Rejected alternatives

- Soften scope and visibility codes. The panel showed that a sibling-result read, an unresolvable
  path, or an opaque command would then pass unseen, and codex seats have no pre-execution hook.
- Keep patching one gap per incident. 0.5.1 fixed one gap, and the next run found another.
- Use explicit numeric rounds to skip evidence mode. That works today, but it drops narrowed
  scope and proof machinery for every seat, not just the one that misbehaved.
