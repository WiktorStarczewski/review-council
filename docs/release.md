# Review Council release procedure

Review candidate N with the signed source of stable N-1. The candidate supplies the
deterministic gate and publication formatter, but never reviews or approves itself.

## Prepare the candidate and stable engine

Start from a clean candidate commit with matching Claude and Codex manifest versions.
Verify the stable tag before using any stable code:

```bash
git status --short
git verify-tag review-council--v0.4.3
STABLE_PARENT=$(mktemp -d /tmp/review-council-stable.XXXXXX)
STABLE_TREE="$STABLE_PARENT/review-council-0.4.3"
git worktree add --detach "$STABLE_TREE" review-council--v0.4.3
STABLE_PLUGIN="$STABLE_TREE/plugins/review-council"
```

The release roster is exactly Sol, Terra, Opus, and Sonnet at maximum effort. Grok and
Astra are excluded. Stop if a configured model is unavailable rather than substituting
another model.

Run the existing deterministic candidate gate:

```bash
python3 scripts/verify-review-council.py --root .
```

Any failure stops the release until the candidate is fixed and the complete gate passes.

## Run the stable review

Load and follow `$STABLE_PLUGIN/codex-skills/rev/SKILL.md` with
`REVIEW_COUNCIL_HOST=codex` on every runner invocation. Review the candidate read-only
and keep the session outside both worktrees. Use one four-seat panel with these composite
assignments:

1. correctness and boundaries, plus attacker behavior and trust boundaries;
2. security, state, and API, plus rollback and recovery;
3. concurrency, resources, and performance, plus duplication and exhaustion;
4. tests, observability, and regression, plus compatibility and integration.

Require valid results, audits, coverage, profiling, and a final report. Verify every
claim against candidate source. Only verified P0 and P1 findings may change or block
this release. Record P2 and P3 findings for follow-up without expanding the release.

If the first review has no verified P0/P1, do not run another review. If it has a
verified P0/P1, add a regression, apply the minimal repair, commit it, rerun the complete
candidate gate, and run exactly one stable read-only delta review. The delta covers the
repair, prior P0/P1 decisions, and one full-state integration assignment. Stop if that
review has a new or open P0/P1. Never launch a third generation.

An invalid audit, missing result, provider failure, or unavailable configured model ends
the current release attempt. It does not authorize a broader panel or candidate-powered
review.

## Publish, merge, and release

After the stable decision is clean, build `pr-review.json` from the verified decisions
and stable session artifacts according to [the PR review contract](../plugins/review-council/docs/pr-review.md).
Render and publish the canonical review on the open pull request:

```bash
python3 plugins/review-council/scripts/rev-pr-review.py render "$REVIEW_SESSION"
python3 plugins/review-council/scripts/rev-pr-review.py publish "$REVIEW_SESSION"
```

Read back the GitHub review and require the rendered body and reviewed commit to match.
Then push the candidate, wait for required CI, and squash-merge the pull request.

From a clean checkout of the merged commit, publish the signed release:

```bash
git tag -s review-council--v0.4.4 -m "review-council 0.4.4" "$MERGE_COMMIT"
git push origin review-council--v0.4.4
git verify-tag review-council--v0.4.4
gh release create review-council--v0.4.4 --verify-tag \
  --title "review-council 0.4.4" --generate-notes
```

Reinstall `review-council@review-council`. In fresh Claude and Codex sessions, require
both hosts to discover `rev` and `stack` at version `0.4.4`, and compare installed file
and mode identity with the released tag.

Finally remove the stable worktree while preserving external review and verifier
artifacts:

```bash
git worktree remove "$STABLE_TREE"
rmdir "$STABLE_PARENT"
```
