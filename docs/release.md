# Review Council release procedure

This is the operator sequence for certifying candidate `0.4.4` against the exact
installed `0.4.3` bundle. The candidate is never its own reviewer: the stable
`rev` skill and stable scripts perform the N-1 review, while candidate scripts are
used only for the deterministic gate and final certification.

## Release lane contract

- Review candidate N with the verified previous stable N-1 bundle, tagged
  `review-council--v0.4.3`.
- Apply P0/P1-only repairs. P2 and P3 findings are recorded as deferred and never
  block this release lane.
- Allow a two-generation cap: generation 1 is the initial stable review; generation 2
  is one stable read-only delta review after a repair. A nonclean second receipt ends
  the lane. Do not launch generation 3.
- Run the deterministic gate on the candidate tree and run targeted canaries against
  the stable bundle for every changed boundary.
- A clean certification receipt authorizes the later squash merge, signed tag, and
  fresh-session discovery checks. Those publication and installation actions are
  separate from certification.

## Prepare and inspect the candidate

Run from the candidate repository root on a clean checkout. Set `STABLE_PLUGIN` to
the direct path of the installed, exact `0.4.3` plugin bundle. Keep the review session
and receipt paths outside the repository, and make each receipt immutable after it is
written.

First ask the release authority which canaries are required for the candidate:

```bash
python3 scripts/verify-release-lane.py requirements --root . \
  --candidate-commit "$(git rev-parse HEAD)" \
  --stable-tag review-council--v0.4.3
```

Run every returned canary with `run-canary`, using the stable bundle's scripts and
recording each receipt before certification. The `host-claude` and `host-codex`
receipts are required when their host skill boundaries changed.

Run the candidate's deterministic verifier once over the same clean tree:

```bash
python3 scripts/verify-review-council.py --root .
```

The verifier receipt must be retained as `$VERIFY_RECEIPT`. A failed or incomplete
gate stops the lane and is fixed before another review generation.

## Stable N-1 review and receipts

Launch one complete read-only review with the exact installed `0.4.3` bundle. The
reviewer must not load the candidate's scripts, skills, or receipts. The review covers
all four composite assignments and is the candidate non-self-review boundary.

Immediately after each stable read-only review, before another review launch, record
its decision from the session artifacts:

```bash
python3 scripts/verify-release-lane.py record-review --root . \
  --candidate-commit "$(git rev-parse HEAD)" \
  --stable-plugin "$STABLE_PLUGIN" \
  --stable-tag review-council--v0.4.3 \
  --session "$REVIEW_SESSION" \
  --new-p0 "$NEW_P0" --new-p1 "$NEW_P1" \
  --open-p0 "$OPEN_P0" --open-p1 "$OPEN_P1" \
  --out "$REVIEW_RECEIPT"
```

The first receipt is either clean or authorizes P0/P1-only repairs. If it authorizes
repairs, apply them, rerun the deterministic gate and affected targeted canaries, then
launch exactly one stable read-only delta review on the new candidate commit. Record
generation 2 immediately. A nonclean second receipt, an infrastructure-blocked
receipt, or any new P0/P1 after generation 2 ends the lane without certification.

## Certify the candidate

With one clean receipt, use `$FINAL_REVIEW_RECEIPT`; with a repair followed by a clean
delta, use the two receipts in order as repeated `--review` arguments. The final
candidate must still equal `HEAD`, and all receipts must identify the same stable tag,
candidate tree, verifier receipt, and canary set.

```bash
python3 scripts/verify-release-lane.py certify --root . \
  --candidate-commit "$(git rev-parse HEAD)" \
  --stable-plugin "$STABLE_PLUGIN" \
  --stable-tag review-council--v0.4.3 \
  --review "$FINAL_REVIEW_RECEIPT" \
  --verification-receipt "$VERIFY_RECEIPT" \
  --canary host-claude="$CLAUDE_CANARY" \
  --canary host-codex="$CODEX_CANARY" \
  --out "$RELEASE_RECEIPT"
```

Certification is the deterministic release gate. It must be clean before the later
squash merge. After the merge, verify the signed tag and then perform fresh-session
discovery for both hosts: each must discover `rev` and `stack`, report version `0.4.4`,
and match the released file and mode identity.
