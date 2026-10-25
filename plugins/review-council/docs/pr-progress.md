# Explicit controller-owned PR progression

A PR preflight pins its initial head, base, branch and repository. Ordinary `prepare` still refuses a different head or any uncommitted changes. Later review-owned regression commits and fixes require an explicit declaration; ancestry alone does not establish ownership.

Use a runtime containing this contract, between completed assignments. First record the exact prior manifest SHA-256 and obtain the current live PR head from GitHub. Then inspect the observed checkout:

```sh
python3 "$P/scripts/rev-evidence.py" pr-progress-inspect "$S" \
  --from "5:PRIOR_MANIFEST_SHA256" --live-head LIVE_PR_HEAD
```

Inspection returns HEAD, live head, full worktree snapshot and index trees, and the exact changed path/mode/blob identities. It creates no review generation, changes no source or real index, and makes no ownership claim. The controller must compare every reported path with the authorized review work. Resolve unrelated changes rather than declaring them review-owned.

Declare all returned identities and paths when preparing the next generation. For example, append these options to the normal plan or verification preparation command:

```sh
  --pr-progress-from "5:PRIOR_MANIFEST_SHA256" \
  --pr-progress-head LOCAL_HEAD \
  --pr-progress-live-head LIVE_PR_HEAD \
  --pr-progress-tree SNAPSHOT_TREE \
  --pr-progress-path src/provider.ts \
  --pr-progress-path src/provider.test.ts \
  --pr-progress-reason 'Controller-owned regression and fix for the accepted finding.'
```

Every changed path must appear exactly once. The set includes paths changed in intervening commits, the index, worktree and untracked files, including staged changes absent from the final worktree. Existing snapshot handling preserves Git path and mode identities. Unmerged or unrepresentable source, unfinished provider launches, changed base/branch/repository, unrelated live-head drift and stale expected identities refuse preparation.

Successful preparation binds `r<label>-pr-progress.json` into the new manifest. The record includes its phase/label, frozen scope hash, prior manifest hash, declared ownership reason and exact source/index identities. New generation files are published atomically and a differing generation cannot replace them or their referenced predecessor. Initial scope, provider output, manifests and receipts remain historical evidence. This declaration supplies no coverage by itself; ordinary assignment, audit and receipt gates still apply.

Fresh ordinary validation rechecks the checkout, index, snapshot and live PR identity. It accepts only the recorded historical live head or publication catch-up to the exact declared local HEAD, preserving the original observation. Prepare and inspect still require the exact live head supplied by the controller. Historical predecessor validation retains artifact, Git, ancestry and path bindings without requiring the old checkout to be current. `--offline` remains a separate read-only compatibility mode and must not replace ordinary gate validation.

This source change does not migrate an initialized 0.8.6 session or authorize changing its private runtime. That version has no progression command. Preserve its artifacts, finish any active assignment, and use only a separately authorized runtime/session recovery. Never replace scripts or switch runtimes while seats are active. The route currently requires a whole-branch pinned PR scope.

Commit final fixes before the final verification prepare. Final publication requires a sealed current verification generation for the exact clean local HEAD and tree, published at that same HEAD. A pending ancestor, another descendant even with an identical tree, missing coverage or mutated record refuses publication. Earlier dirty plan/fix generations do not grant permission to publish uncommitted bytes.

Creation idleness uses actual lifecycle records, not pending seat metadata. A failed prepare that left four seats listed but launched none does not block inspection or preparation. Running seats may still validate their own fixed manifest; the creation idle check does not replace their audit gates.

New managed launches carry one outer-launch token through internal retries. The attempt record binds terminal completion to that token and reserved calls. Concurrent tokens, duplicate terminal records and a stale token completing a later reservation refuse. A completed bound record can prove terminality after a raw exit file was lost; inspection does not manufacture that exit file.

Legacy compatibility is narrower. Under the managed `rev-seat` protocol, which removes the prior raw exit before reserving a launch, inspection requires valid canonical prompt identity, exact call/outcome counts and a matching existing raw exit. It never infers a completion watermark or rewrites historical records. Missing or mismatching artifacts and ambiguous counts refuse. This is compatibility with that managed protocol, not universal proof against unsupported manual reserve/record calls or artifact mutation. New token-bound launches do not silently adopt legacy attempt records.

Prepare, inspect and managed attempt commands share the session input lock. Attempt commands acquire it before panel and record locks, so a reservation cannot enter between the final idle scan and immutable generation publication. Terminal recording and check-triggered lifecycle writes follow that same order. The session lock is released before the provider runs.
