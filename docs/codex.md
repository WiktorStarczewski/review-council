# Codex port

## Install and update

Marketplace:

```bash
codex plugin marketplace add WiktorStarczewski/review-council
codex plugin add review-council@review-council
```

One-liner (no checkout required):

```bash
curl -fsSL https://raw.githubusercontent.com/WiktorStarczewski/review-council/main/install-codex.sh | bash
```

The repository contains a Codex marketplace manifest. Codex fetches a Git snapshot
of this repo and installs the selected plugin into its cache. The one-liner runs the
same two marketplace commands. This is a repository marketplace you explicitly add;
it does not submit the plugin to the public curated catalog.

Start a new Codex chat after installation. To update:

```bash
codex plugin marketplace upgrade review-council
codex plugin add review-council@review-council
```

To try a branch before it is merged, pass `--ref <branch>` to `marketplace add`, or
pipe that branch's installer to `bash -s -- --ref <branch>`. The script also accepts
`REVIEW_COUNCIL_REF`; it defaults to `main`.

For local development, `python3 scripts/install-codex-plugin.py` builds
`~/plugins/review-council`, adds it to the personal marketplace, and installs
`review-council@personal` with a fresh version build suffix. Keep only one variant
enabled in a session. Use `codex plugin remove review-council@personal` to remove a
previous local installation after switching to the repository marketplace.

Build without installing with `python3 scripts/build-codex-plugin.py --output
/tmp/review-council`. The output is generated; rebuilding replaces it. An unrelated
output directory or conflicting personal marketplace entry is refused.

To uninstall the repository version:

```bash
codex plugin remove review-council@review-council
```

## Invocation

Ask Codex to use review-council; select its `rev` or `stack` skill from the skills
picker when available. Examples:

```text
Use review-council to review this branch against origin/main.
Use review-council for one round, read-only, on my uncommitted changes.
Use review-council to review these design documents.
Use review-council to review the SDK and wallet branches as a dependency stack.
```

Code fix loops use adaptive discovery, plan, fix, and verification panels. With four
core seats, normal changes plan 12 seat launches: four simplicity, four conditional
plan, and four final verification launches. A large or high-risk review plans 16 by
adding four risk-discovery launches. One four-bundle verification panel reviews the
latest material state: directly after discovery when no nontrivial fix follows, or
after the latest nontrivial fix. Read-only reviews default to one panel. Explicit round counts remain minimum
overrides and select the Codex host's legacy numbered schedule. Numeric mode continues
while a new or open P0/P1, a nontrivial last fix, or an unreviewed lens or major file
remains. It stops after the minimum, two consecutive rounds without a new P0/P1, no
open P0/P1, and gates at baseline or better. Plan panels do not count. Actual reviewer
calls consume the corresponding provider's usage.

Adaptive code panels use hashed scope manifests and semantic dependency components.
Mechanical lockfiles, generated output, snapshots, and locale copies go to one named
full-state seat. Specialists receive component patches, and later fixes return to the
seat that found the issue. Every seat proves gap-free reads of its assigned patch in
ordered hash-bound chunks when doing so saves at least 10% of proof reads. Chunk bytes
reconstruct the canonical patch exactly and remain under the audited provider-output
ceiling. Other patches use windows of at most 240 lines. Literal source packets contain exact enclosing
declarations, callers, tests, and gates. Oversized omitted bodies become mandatory
integration-seat reads bound to the exact tree, blob, content hash, and returned
bytes. These bodies are published as manifest-hashed session artifacts in ordered,
gapless segments of at most 240 lines and 16 KiB predicted visible output, one segment
per Codex turn. Later verification uses the semantic fix delta only when a valid receipt proves
prior coverage and the delta plus its evidence is smaller. Otherwise, safe cumulative
evidence keeps one full integration seat and gives specialists semantic components.
Invalid predecessor state or any current-evidence error restores full cumulative scope
for the whole panel. Numeric and document reviews keep full scope.

Adaptive plan panels hash-bind every parsed fix-plan cluster. The plan-completeness
seat keeps the full cumulative patch; all other seats receive one identical closure of
the named sites, tests, regression paths, and changed local-import boundaries. Every
seat still reads the complete plan and navigation index, runs each cluster's bounded
repository-root sibling search, and proves its named source ranges. Each search is one
`rg` or recursive `grep` expression whose only path operand is literal `.`. Traversal
filters, extra operands, file-sourced patterns, engine substitutions, filename
suppression, redirects, saturated results, absent named sites, and producer errors fail
closed. Successful shell proof uses `--null` and contains fewer than 80
`path<NUL>line:text` match records; native text search cannot certify it.
`verify-panel` validates the complete attempt without writing a receipt or advancing
code coverage. Any parse, binding, audit, or validation failure reruns the entire plan
panel at fresh legacy full scope. Agent-adapter plan panels use legacy full scope because
their native read hooks cannot be enforced.

## Provider and orchestration differences

| Behavior | Claude Code | Codex |
| --- | --- | --- |
| Anthropic seat | Built-in Opus agent | Installed, signed-in Claude CLI |
| Other seats | Detected Codex/Grok/Gemini CLIs | Same |
| Thin-panel padding | Opus agents | Repeated surviving CLI runs, reported as degraded |
| No usable external CLI | Built-in Claude panel | Refuse if no actual provider survives |
| Session policy | Claude SessionStart hook | Native skills, no global review hook |
| Stack engine | `claude -p` | `codex exec` |
| Stack finishing defaults | Squash and push | Keep history and changes local |

By default, Codex selects its newest visible model generation from its local model
cache, up to two seats, using the existing supported effort ladder. Set
`codex_models` to an ordered list of one or two unique visible slugs when the council
must use exact models. Invalid values, unknown slugs, pins outside that list, and
missing configured seats refuse the roster before padding. Set `claude_seats` to an
integer from 0 to 4 for an exact number of independent Opus runs; a missing positive
configured count also refuses before padding. Identical adapter/model availability
probes are cached. To require Sol, Grok, and two Opus runs, set the exact model and
count, exclude Gemini, disable extras, and set `min_labs` to 3. A single-provider panel
without strict settings is reported as degraded. See
[configuration](config.md) for pins, exclusions, and environment variables.

Strict availability failures exit 5 and may clear after a provider signs in, a probe
recovers, or a model cache becomes available. This includes a satisfiable lab floor that
current provider availability cannot meet. Permanent configuration failures exit 6,
including malformed exact settings, an invalid `min_labs`, a floor above the maximum
allowed by exclusions and disable settings, unknown configured models, exclusions of
required seats, and incompatible pins. The roster stores the matching `strict_reason`,
appends it to `--brief`, and decides known permanent conflicts before paid probes.
Preflight keeps the same status. Stack legs retry only exit 5.

Both hosts install the same plugin directory. The Codex manifest selects
`codex-skills/`; Claude keeps its existing `skills/`. Claude's hook config lives in
`.claude-plugin/hooks.json` and is explicitly registered by its manifest, so Codex
does not discover it as a default startup hook. The review scripts and schema have
one shared source.

The Claude CLI adapter permits Read/Glob/Grep and Bash checked by the original
allowlist hook. It disables inherited settings/plugins and MCP configuration,
uses plan mode, and excludes editing tools. Codex seats retain the read-only sandbox.
Both emit the shared findings schema; missing/malformed answers fail validation.
A Claude structured-output event alone does not count as inspecting source files.

Stack legs use Codex's workspace-write sandbox, network access to contact reviewers,
and write access to their session directory. The runner keeps the existing activity
and CPU stall detector. A fresh report is required for every attempt, so an old
receipt cannot make a failed pass look successful. Profiling accepts receiptless legacy
results only when the roster is absent or is a valid historical object without receipt
metadata. Present unreadable, corrupt, non-object, or malformed receipt metadata requires
receipts and cannot grandfather a result. Some sandbox/platform setups may
restrict nested CLIs or repository gates; these failures remain visible and do not
implicitly enable unrestricted execution. A full multi-repository live stack can
consume substantial usage; automated tests exercise its orchestration with doubles.
The profiler reports full, assigned, delta, evidence, and avoided words as projected
scope fields, plus patch proof calls, turns, visible bytes, chunks, and delivery modes.
Provider input, output, processed tokens, and cost remain separate actual measurements.

## Development checks

```bash
plugins/review-council/tests/run-tests.sh
python3 -m unittest discover -s tests -v
```

Both run on macOS and Linux in CI. The second suite exercises Codex roster fallback,
Claude auth and stream parsing, adapter permissions, packaging/installation, and
stack receipts. Live reviewer smoke tests should use disposable files and a known
failure; never treat stub responses as proof of provider compatibility.
