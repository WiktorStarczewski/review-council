# Token-Efficient Review Council Design

## Goal

Reduce the default review loop's processed-token usage by at least 3.5x while
preserving independent provider coverage at discovery and verification.

## Evidence

Six preserved sessions contained 193 metered reviewer runs and about 1.05
billion provider-reported processed tokens. Completed eight-round sessions used
58-62 seat launches. Plan reviews were 43% of schema-valid calls. The PR #812
session also repeated its cumulative ledger in every prompt, producing average
prompt sizes of 2,910 words for code and 5,927 words for plans.

The existing held-out evaluation establishes two constraints. Four independent
simplicity seats recover findings that a single seat misses, and removing the
fix-plan gate increases partial fixes and later churn. Both mechanisms remain.

## Schedule

The default loop is adaptive:

1. Run a four-seat simplicity discovery panel.
2. For a large or high-risk change, run one four-seat risk discovery panel.
3. When accepted findings require nontrivial changes, run one four-seat plan
   panel over an immutable, compact root-cause plan.
4. Apply fixes and run the relevant gates.
5. One four-bundle verification panel reviews the latest material state: directly
   after discovery when no nontrivial fix follows, or after the latest nontrivial fix.
6. Repeat a plan, fix, and verification cycle only for a new P0/P1 root cause,
   an open P0/P1, or another nontrivial fix.
7. Run project gates for a P3 or one-line P2 follow-up. Every other adaptive fix
   receives a full verification panel.

A normal review therefore plans 12 seat launches: four simplicity, four conditional
plan, and four final verification launches. A large or high-risk review plans 16 by
adding four risk-discovery launches. An explicit round count remains a minimum
override and exclusively selects that host's legacy numbered schedule. Numeric
mode continues past the minimum while a new or open P0/P1, a nontrivial last fix,
or an unreviewed lens or major file remains. It stops after the minimum, two
consecutive rounds without a new P0/P1, no open P0/P1, and gates at baseline or
better. Plan panels are not numbered rounds.

Large means more than 25 changed files or more than 1,500 changed lines.
High-risk means the change crosses a security, persistence, concurrency,
transaction, or public API boundary. Either condition adds the risk discovery
panel.

Adaptive completion requires valid results for every verification bundle after
discovery or the latest nontrivial fix,
no new or open P0/P1 findings, no unreviewed material changes, and gates at or
better than baseline.

## Review coverage

Every discovery seat keeps the simplicity checklist. The risk and verification
panels distribute four bundles while retaining the common evidence rules:

- correctness, boundaries, and error handling
- security, state, and API contracts
- concurrency, resources, and performance
- tests, observability, maintenance, and regression

Adaptive certification requires valid results for all four bundles. After a risk or
verification panel returns at least three valid reviewers, coverage is computed from
valid outputs for any roster size. Every missing bundle runs as an `r<N>x-*` repair
on a distinct surviving seat before completion.

The verification panel reads the cumulative change when needed, with priority
on changes since the last completed panel and their consumers.

## Prompt contract

Reviewer prompts contain the pinned scope, changed files, one lens bundle, a
concise baseline, one-line rejected decisions, and a compact session digest when
`context.md` exists. They never contain the cumulative findings ledger.

Providers with native structured-output support receive the schema through the
adapter. The rendered prompt includes it once for Agent and Gemini seats because
those paths lack a native schema option. Plan prompts contain an immutable,
line-numbered snapshot and name its stable session path for citations.

Each reviewer starts from the diff, follows only the evidence paths needed to
finish its checks, combines sibling sites under one root cause, and returns no
more than five distinct findings. The prompt does not invite unlimited work.

Generated code prompts warn above 1,800 words. Plan prompts warn above 3,000
words. Warnings do not truncate evidence.

## Measurement

A session profiler reports prompt words, completed calls, metered attempts,
completed seats whose usage is unavailable, provider input and output tokens,
cost when exposed, and findings per code or plan phase. Completion and finding yield
for a current session require a schema-valid result and a successful exit receipt.
When an older session is reopened, its roster policy records the filename and exact
hash of each preexisting receiptless result; only unchanged allowlisted bytes retain
the historical schema-only fallback. Usage-bearing failed attempts remain metered.
Each CLI retry keeps an immutable stream, so every terminal usage record contributes
once. Preflight health probes are outside the reviewer-artifact metric.

Historical simulation must show 12 planned launches for normal completed runs
and 16 for large or high-risk runs, compared with 58-62 previously. PR #812
generated prompts must shrink by at least 2x without omitting its plan text.

Exact model and repeated Opus counts are validated before padding. The configured
panel combines those checks with `min_labs: 3` and Gemini exclusion so required Sol,
Grok, and two-Opus coverage cannot fail open to another provider. Effort,
first-pass simplicity, and the plan gate remain unchanged. Lower effort and hard
turn caps require a separate blinded quality evaluation before becoming defaults.

Strict roster failures retain their cause. Exit 5 represents retryable availability:
missing binaries or sign-in, model-cache failure, probe failure, and lab-floor loss.
Exit 6 represents permanent configuration: malformed exact values, unknown or
unsupported configured models, required exclusions, and incompatible or duplicate
pins. The roster stores the winning cause in `strict_reason`, emits it in `--brief`,
and decides known permanent conflicts before paid probes. Preflight preserves the
status. Config wins in mixed cases, and stack legs fail it without an auth wait.
