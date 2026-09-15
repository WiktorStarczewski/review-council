# Review Council Procedural Stable Release Lane Design

## Goal

Release Review Council without letting a candidate review itself and without building a
second review platform. Candidate releases use the existing deterministic verifier and a
short operator procedure driven by the signed previous-stable tag.

Ordinary Review Council behavior remains adaptive. The session-wide hard-audit stop,
immutable evidence-session inputs, promoted adversarial coverage, and canonical GitHub
review publication remain part of 0.4.4.

## Incident finding

The original 0.4.4 review path became a self-amplifying loop. The first correction then
introduced a separate 2,870-line release authority that validated stable installations,
translated review and canary receipts, and composed a final certificate. That control
plane took longer to build and review than the release behavior it governed.

The existing frozen-tree verifier already supplies the deterministic candidate proof.
The signed previous-stable tag already supplies the independent review engine. A custom
authority between those boundaries duplicates both systems without improving the release
decision enough to justify its surface.

## Chosen architecture

Use a procedural bootstrapping lane:

1. Verify the signature on the previous-stable tag.
2. Materialize that exact tag in a temporary detached worktree.
3. Run the candidate's existing frozen-tree verifier.
4. Use the stable worktree's review skill and scripts for one complete read-only P0/P1
   review of the candidate.
5. If verified P0/P1 repairs are required, rerun the verifier and allow exactly one
   stable delta review.
6. Stop if the delta has a new or open P0/P1 or if either review is incomplete.
7. Publish the canonical review on the pull request, wait for CI, squash-merge, sign and
   publish the release tag, reinstall, and verify fresh-session discovery.

There is no release authority script, mutable release database, custom review-receipt
translation, canary-receipt format, or final release certificate.

## Stable engine boundary

The stable review engine comes directly from the signed tag, not from a cache whose
identity must be reconstructed.

For 0.4.4, the previous stable tag is `review-council--v0.4.3`. The operator runs
`git verify-tag review-council--v0.4.3` before creating a detached worktree at that tag.
Review prompts, provider launchers, evidence builders, and receipt validators all come
from that worktree.

The review target remains the candidate checkout. Stable scripts may read candidate
source and write session artifacts outside both worktrees. Candidate review scripts do
not make or certify the release decision.

The release roster is exactly Sol, Terra, Opus, and Sonnet at maximum effort. Grok and
Astra remain excluded. An unavailable configured model is a blocker rather than an
implicit substitution.

## Candidate boundary

The candidate is a clean commit with matching Claude and Codex manifest versions. Its
deterministic gate is the existing command:

```text
python3 scripts/verify-review-council.py --root .
```

That verifier freezes one source tree, reconciles the shell-test inventory, runs shell
and Python suites, builds the Codex bundle, validates plugin manifests and static
contracts, checks command logs, and emits its existing hash-bound receipt. No second
program revalidates or wraps that receipt.

CI runs the same verifier on macOS and Linux. Local verification proves the candidate
before review; hosted CI proves the pushed branch before merge.

## Review generations

Generation 1 is one complete read-only review using the stable worktree. The four seats
cover these composite assignments:

1. correctness and boundaries, plus attacker behavior and trust boundaries;
2. security, state, and API, plus rollback and recovery;
3. concurrency, resources, and performance, plus duplication and exhaustion;
4. tests, observability, and regression, plus compatibility and integration.

Every finding is verified against candidate source. Only verified P0 and P1 findings
may change or block this release. P2 and P3 findings are recorded for follow-up and do
not expand the release.

If generation 1 is clean, no second review runs. If P0/P1 repairs change the candidate,
the deterministic verifier runs again and generation 2 reviews the exact repair delta,
prior P0/P1 decisions, and one full-state integration assignment. Generation 2 is the
last permitted review. A new or open P0/P1 stops the release.

An incomplete roster, invalid audit, provider failure, or missing receipt stops the
current release attempt. It does not authorize a broader panel or a third generation.

## Runtime proof

The release does not precompute a changed-path canary matrix or create custom canary
receipts.

Runtime behavior is proved at the natural boundaries:

- host workflow behavior is covered by the candidate test suite and the stable review;
- GitHub publication is exercised by posting the actual canonical review to the release
  pull request after the stable decision is clean;
- installation is exercised after publication by installing the tagged release;
- fresh Claude and Codex sessions must discover `rev` and `stack` at version `0.4.4`.

The candidate publication code formats and transmits the already-made stable review
decision. It does not act as a reviewer or authorize the release.

## Release sequence

The operator checklist is authoritative and intentionally short:

1. Confirm a clean candidate commit and matching `0.4.4` manifests.
2. Verify the signed `review-council--v0.4.3` tag.
3. Create a temporary detached worktree at that tag.
4. Run the existing candidate verifier.
5. Run generation 1 with the stable worktree and exact four-seat roster.
6. Apply only verified P0/P1 repairs. If repairs occur, rerun the verifier and run one
   delta generation.
7. Publish the canonical review on the pull request exactly once.
8. Push, wait for required CI, and squash-merge.
9. Create and verify the signed `review-council--v0.4.4` tag, then publish the release.
10. Reinstall 0.4.4 and verify fresh-session discovery on both hosts.
11. Remove the temporary stable worktree.

Session artifacts and verifier receipts stay outside the candidate repository. They are
diagnostic evidence, not inputs to another authority.

## Failure handling

- Invalid previous-stable signature: stop before review.
- Dirty candidate or mismatched manifests: stop before verification.
- Deterministic verifier failure: fix the candidate and restart from verification.
- Initial review P0/P1: repair once, reverify, and run the one delta generation.
- Delta review P0/P1: stop the release.
- Review infrastructure failure: stop the release attempt without widening or silently
  substituting the roster.
- GitHub publication failure: preserve the existing durable retry state and use its exact
  retry command without rerunning the review.
- CI failure: diagnose and fix before merge.
- Installation or discovery failure: keep the published evidence and repair through a
  new release rather than mutating the tag.

## Removed subsystem

Delete these authority-only files:

- `scripts/verify-release-lane.py`
- `tests/test_release_lane.py`

Rewrite these references around the procedural lane:

- `docs/release.md`
- `README.md`
- `CHANGELOG.md`
- `tasks/todo.md`
- this design and its implementation plan

No production module imports or invokes the deleted authority, so removal needs no
compatibility layer or migration.

## Verification strategy

Do not add a brittle test that asserts documentation prose or merely checks that deleted
files remain absent.

Verification consists of:

- correcting the three already-red stale shell fixtures;
- running their focused tests to green;
- scanning the tracked tree for remaining `verify-release-lane` references;
- running the complete existing frozen-tree verifier;
- running the stable signed-tag review with P0/P1 as the release threshold;
- verifying the actual GitHub publication, CI, signed tag, installation, and fresh-session
  discovery at their natural release boundaries.

## Success criteria

- The 2,870-line authority and its custom receipt formats are gone.
- No tracked file invokes or documents `verify-release-lane.py`.
- Ordinary review safety and adversarial-coverage improvements remain.
- The complete deterministic gate passes without errors.
- The signed 0.4.3 worktree produces a complete release review with no open P0/P1.
- PR publication, CI, squash merge, signed 0.4.4 tag, reinstall, and discovery all
  complete without using candidate review code as the release decision-maker.
