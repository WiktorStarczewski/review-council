# Review Council release procedure

Review Council never reviews changes to its own repository, plugin, skills, scripts,
or release artifacts. Use one independent normal reviewer for the completed candidate.
The reviewer is read-only. The release owner verifies findings against source and fixes
actionable issues before publication.

## Prepare and review the candidate

Start from a clean candidate commit and keep all three plugin manifest versions aligned.
The repository rule in `AGENTS.md` applies to every host and release path. Do not invoke
Review Council `rev` or `stack` for this repository.

Verify the latest signed stable release before using it as the candidate base:

```bash
git verify-tag review-council--v0.8.9
```

Run the complete deterministic candidate gate in CI for the exact candidate commit on
macOS and Ubuntu:

```bash
python3 scripts/verify-review-council.py --root .
```

The pull request workflows run the gate and package validation. Require both operating
system results and the Cursor package job to pass on the current PR head. Any failure
stops the release until the candidate is fixed and the required gates pass.

## Merge and publish

Open a pull request with a concise description of current behavior. After the independent
normal review is clean and all required CI checks pass on the current head, squash-merge
the pull request.

From a clean checkout of the merged commit, publish the signed release:

```bash
git tag -s review-council--v0.8.10 -m "review-council 0.8.10" "$MERGE_COMMIT"
git push origin review-council--v0.8.10
git verify-tag review-council--v0.8.10
gh release create review-council--v0.8.10 --verify-tag \
  --title "review-council 0.8.10" --generate-notes
```

Reinstall `review-council@review-council` for Claude and Codex, and run
`install-cursor.sh` for Cursor. In fresh sessions on each host, require `rev` and
`stack` at version `0.8.10`, and compare installed file and mode identity with the
released tag.
