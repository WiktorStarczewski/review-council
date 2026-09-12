# Evidence-Efficient Review Council Design

## Goal

Reduce reviewer input tokens after the adaptive schedule change without reducing the
required Sol, Grok, Opus, and Opus-2 panel, the four risk bundles, or source-level
verification. The first evidence phase targets another 25-40% reduction on fix-heavy
reviews. Semantic component routing, finding ownership, enforced bounded reads, and
stable prompt prefixes target a further 1.3x-1.7x reduction on suitable reviews. Every
narrowing rule falls back to the current full review whenever completeness is not
demonstrable.

## Constraints

- Every material hunk receives a complete independent discovery review before it may
  be omitted from a later seat's starting patch.
- Every semantic hunk is assigned to at least one specialist seat as well as the
  full-state integration seat. When safe components cannot keep every specialist
  meaningfully occupied, components are duplicated or the semantic cumulative patch
  is used.
- Every adaptive verification keeps exactly one full-state integration seat.
- All four risk bundles still receive valid results. Delta scope changes navigation,
  not the bundle or reasoning requirement.
- Mechanical routing assigns lockfiles, generated output, snapshots, and locale
  copies to one recorded seat. Other seats may open them to prove an interaction.
- Evidence packets contain deterministic repository facts only. They are navigation
  indexes, never evidence for a finding.
- Risk bundle coverage is independent of roster size. All four bundles are covered at
  least once; a three-seat panel combines two bundles for one seat, and surplus seats
  receive deterministic repeated coverage.
- Missing, malformed, stale, incomplete, or unsafe state widens review to the full
  cumulative patch.
- Explicit numeric schedules and document reviews keep their current full scope.
- A path review captures only its validated literal path scope. Out-of-scope tracked,
  staged, unstaged, and untracked content never enters review artifacts.

## Snapshot model

`rev-evidence.py` owns snapshots for both hosts. For a live worktree it creates a
temporary Git index, reads `HEAD`, and overlays tracked changes, deletions, and
untracked files. Regular files and symlinks are hashed with `git hash-object
--no-filters`, then entered with `git update-index --cacheinfo`. Objects and the
temporary index live below the review session through `GIT_OBJECT_DIRECTORY` and
`GIT_INDEX_FILE`; the repository index, refs, and object database remain unchanged.

Diffs use fixed behavior: no external diff, text conversion, rename inference, indent
heuristic, or color; Myers algorithm; three context lines; binary output. A supplied
Git ref can seed a resumed session from a previously reviewed commit.

Each patch hunk is identified by SHA-256 over canonical JSON containing its change
kind, path, and exact body. Line coordinates and the function-header suffix are
excluded, while context lines remain. Hashes are a multiset so duplicate hunks do
not collapse. Binary, mode, symlink, submodule, and unparseable changes become opaque
file atoms.

## Commands and artifacts

The script exposes five commands:

```text
rev-evidence.py prepare SESSION LABEL --phase discovery|risk|verification|repair|plan
  [--head REF] [--assignment SEAT=BUNDLE] [--full-seat SEAT]
  [--plan FILE --plan-sha256 SHA256]
rev-evidence.py render MANIFEST SEAT [--plan-source FILE]
rev-evidence.py verify MANIFEST
rev-evidence.py verify-panel SESSION LABEL
rev-evidence.py receipt SESSION LABEL
```

`prepare` writes atomically:

- `r<LABEL>-evidence.json`: the full deterministic fact set and scope assignments.
- `r<LABEL>-evidence.md`: a compact index with omitted counts and a pointer to JSON.
- `r<LABEL>-full.patch`: the cumulative diff from the pinned base.
- `r<LABEL>-semantic.patch`: the cumulative diff without confidently mechanical
  files.
- `r<LABEL>-delta.patch`: the change since the latest valid coverage receipt,
  without confidently mechanical files.
- `r<LABEL>-patch-p<SET>-<INDEX>.txt`: an ordered byte slice of one assigned
  patch, emitted only when chunk mode satisfies every bound and saves at least 10%
  of proof reads. Assignments with identical patch hashes share one chunk set.
- `r<LABEL>-evidence.manifest.json`: hashes, snapshot tree, phase, assignments,
  fallback reason, word counts, patch-set identities, and chunk metadata.

`render` validates the manifest, artifact hashes, snapshot freshness, requested seat,
and exact plan snapshot when `--plan-source` is present. It emits adapter-specific
first-read instructions with the assigned patch and evidence index.
A present invalid manifest is an error. An absent `--evidence` flag preserves legacy
full-diff prompt behavior.

`receipt` requires a successful exit and schema-valid result from every assigned
seat, at least one valid full-state result, exactly four distinct bundles for a risk
or verification panel, unchanged snapshot state, and prompts containing the exact
manifest hash. It writes immutable `r<LABEL>-coverage.receipt.json` and advances
`coverage-head.json` only after every check succeeds. A failed receipt leaves the
previous coverage head unchanged.

For a resumed session, `prepare --head <reviewed-ref>` plus `receipt` may seed coverage
only when the preserved prompts already contain the new manifest hash and all result
artifacts validate. Legacy prompts cannot be upgraded after execution because that
would certify instructions the reviewers did not receive. An unknown ref, a changed
base, or legacy prompt keeps the next panel on full scope.

## Scope selection

Discovery and risk panels give the full-state seat the cumulative patch. Other seats
receive deterministic semantic component patches. Components are connected sets of
changed semantic files joined by lexical references, resolved local imports, related
tests, or direct changed-symbol call sites. Components are assigned by descending
patch weight to the least-loaded specialist in stable seat order. Every semantic file
appears in at least one specialist patch and in the full-state patch. If there are
fewer components than specialists, the smallest deterministic component is repeated
until every specialist receives reviewable content. This routes mechanical files once
while keeping ordinary code under independent specialist and integration review.

Verification activates delta mode only when a valid prior coverage receipt exists,
the current snapshot differs, the delta is nonempty, all changes are safely
represented, the four bundles are assigned exactly once, and the delta plus evidence
is smaller than the semantic cumulative view. The seat assigned
`tests-observability-maintenance-regression` receives the full cumulative patch.
Other seats receive the semantic delta. If the head is absent, the snapshot is
unchanged, the semantic delta is empty, or delta delivery is not smaller, safe current
evidence keeps the integration seat on the full cumulative patch and routes cumulative
semantic components to every specialist. This benign semantic mode can establish a new
coverage receipt. Only delta mode stores a predecessor and reuses prior finding
ownership. Invalid predecessor state, unsafe current evidence, incomplete bundle
coverage, unknown reviewed refs, or absent cumulative semantic coverage assigns the
full cumulative patch to every seat.

Each coverage receipt records the stable identity and seat owner of every reported
finding. On later verification, a changed component that contains a prior finding's
file or its deterministic dependency boundary returns to that finding's seat. A
finding owned by the integration seat is already covered by that seat, so the
component also goes to the least-loaded specialist. Components with multiple owners
may be repeated. Unmatched components follow the normal stable load-balancing rule.
Missing or invalid ownership data widens to normal component routing, never to less
coverage.

Repair panels with one seat always receive the full cumulative patch. This lets a
replacement establish integration coverage. A verification receipt still requires
the complete four-bundle result set before it advances coverage.

## Mechanical classification

Classification is conservative and deterministic:

- Lockfiles use exact known basenames such as `Cargo.lock`, `package-lock.json`,
  `pnpm-lock.yaml`, `yarn.lock`, `go.sum`, `Package.resolved`, and
  `.terraform.lock.hcl`.
- Snapshots use `__snapshots__`, explicit snapshot directories, and `.snap` forms.
- Locale copies require a locale, i18n, l10n, or translations path plus a
  translation-specific extension or locale-tagged data file. Support code such as
  `i18n/config.ts` remains semantic.
- Generated output requires a generated or do-not-edit header, an explicit generated
  directory or suffix, a source map, or minified output.

Ambiguous build directories, dependency patches, fixtures, golden files, vendored
source, binaries, symlinks, oversized files, and unsupported formats remain semantic.
The manifest records the owner and every categorized path. The default discovery
owner is the first surviving core seat. Risk and verification use the full-state
bundle owner.

## Deterministic evidence packet

The packet derives:

- changed enclosing symbols from hunk headers and language-specific declaration
  patterns;
- direct call sites, explicitly labeled as lexical `name(` matches rather than
  resolved dynamic dispatch;
- related tests from test-path references and same-stem or sibling conventions;
- gate candidates from package scripts, manifests, Make and just targets, CI command
  lines, and exact lint, test, type, and coverage config files.

The JSON keeps every deterministic match. The Markdown view limits each section and
states the omitted count. Unsupported or ambiguous symbol extraction falls back to a
file-scope seed. Reviewers may search beyond the packet whenever the assigned check
requires it.

Snapshot work uses a bounded raw hashing pass and writes only changed or untracked
blobs into the session object store. This preserves same-size and restored-mtime
changes without running clean filters. Evidence lookup may search the tracked tree,
but it must use a near-linear pass instead of a nested file by symbol scan. A
wallet-sized repository is part of the performance regression check.

For path scope, snapshot construction begins from the complete pinned tree and overlays
only paths matched by the validated literal pathspec. Paths outside that set remain at
their pinned values. The manifest binds the preflight file and untracked inventories,
and validation refuses an artifact containing an out-of-scope path. Sparse entries
remain unchanged unless Git reports a real scoped worktree change. A representable
gitlink update is stored as an opaque atom; dirty or unsupported special states abort
evidence preparation before publication so the host uses its legacy full-scope path.

## Bounded evidence protocol

Every code prompt uses this positive recipe:

1. Discover every assigned hunk, including untracked files.
2. Locate the enclosing symbol or named section, then search definitions, direct
   references, related tests, and config gates.
3. Read the smallest useful line window around each match.
4. Expand to another block, file, or pinned dependency only to answer a concrete
   question that could prove or refute a finding.
5. Stop that evidence path when the question is answered, while finishing every
   assigned check and expanding whenever evidence is insufficient.

Clean-room review drafts its independent design before starting this recipe. Document
reviews continue to read the supplied documents in full. Active reviewer instructions
must not add unlimited-work wording or a blanket whole-file rule.

The protocol is enforced where each host exposes a boundary. Read calls use an
explicit offset and a maximum line window, search calls use a bounded result count,
and shell source reads use bounded ranges. The prompt and compact evidence index are
full-read exceptions. Listed source packets and assigned patch chunks may also be read
in full, but patch chunks remain subject to the 32 KiB model-visible output ceiling.
A reviewer may expand after naming the concrete symbol
or invariant being tested; the next bounded window is recorded in the transcript.
Adapters whose native tools cannot be intercepted receive the same contract and a
post-run transcript audit. A result that violates the contract is not counted as a
valid narrow review and is retried at full scope.

## Assigned patch chunks

The complete assigned patch remains the canonical identity and citation-neutral review
artifact. For valid UTF-8 without NUL bytes, evidence preparation partitions its exact
bytes into ordered, gapless chunks with a 24 KiB raw ceiling, a 30 KiB predicted
model-visible ceiling, and at most 1,000 displayed lines. The prediction reserves eight
bytes per displayed line for provider prefixes; the 32 KiB audited output ceiling is
still authoritative. Boundaries prefer newlines. A physical line longer than a chunk
splits only between UTF-8 scalars, and metadata records whether either edge is mid-line.

Chunk mode activates only when the chunk count is at most 90% of the 240-line window
count. Concatenating chunk artifacts without delimiters must reproduce the assigned
patch and its SHA-256 exactly. Reviewers read each chunk once, in order, before source
packets or source expansion. Audit strips only known provider line prefixes and an
optional terminal newline before comparing delivered bytes, and counts chunks as patch
proof only. They never establish original-source coverage or support a finding citation.
Invalid encoding, NUL bytes, unsafe metadata, reconstruction failure, stale or redirected
artifacts, missing, duplicate, reordered, partial, or oversized reads retain or restore
window mode and whole-panel fail-full behavior. `REV_PATCH_CHUNKS=1` enables the
held-out adoption candidate; the default remains `0` until certification.

## Semantic components and cacheable prompts

Component patches are first-class hashed artifacts in the evidence manifest. The
manifest records each component's files, dependency edges, word weight, assigned
specialists, prior finding owners, and full-state owner. Validation proves that the
union of specialist component patches covers every semantic hunk and that no component
contains an out-of-scope path. The full-state owner always receives the complete
cumulative patch.

Every code prompt begins with one byte-identical reviewer contract containing the
read-only rule, bounded-read protocol, evidence standard, severity meanings, and JSON
output rules. Seat lens and repository-specific scope follow that stable prefix.
Clean-room prompts retain their pre-tool ordering through an invariant instruction in
the prefix. Adapters enable provider-supported cache-stability options without changing
models, effort, tools, or repository instructions. The profiler reports raw input,
cache-write input, cache-read input, and billed cost separately; cache hits are never
reported as raw-token reduction.

## Literal source-context packets

Each evidence assignment may include hash-bound source excerpts selected from the exact
snapshot. Excerpts keep their original path and one-based line numbers, merge overlapping
ranges, preserve complete lines, and record the snapshot blob or tree identity and the
reason each range was selected. Packet bytes are original source evidence rather than a
summary. A reviewer may cite a packet line as the corresponding original file line.
`REV_SOURCE_CONTEXT=1` enables the held-out adoption candidate; the default remains `0`
until certification.

Selection gives every changed symbol a declaration seed before adding one production
caller per symbol, one related test per component, every detected gate, and then stable
extra caller and test windows. A specialist receives at most one 32 KiB shard. The
full-state integration seat receives at most three 32 KiB shards. Any omitted or
ambiguous match is recorded as `source read required`; dynamic dispatch, long symbols,
binary or special files, and control flow outside an excerpt always require a bounded
source expansion when relevant.

An oversized mandatory range keeps one parent tree, blob, range, and content hash.
Its delivery is partitioned into ordered, gapless child segments of at most 240 lines
and 16 KiB predicted visible output, including an eight-byte reserve per line. The
renderer supplies exact reads from the session's immutable Git object repository, and
the audit permits two consecutive segments per turn for Claude and Grok and one for
Codex and Gemini. Preparation fails closed
when one source line cannot fit a segment. Parent receipts are issued only after every
segment validates and reconstructs the parent's exact bytes.

Generation fails closed if a line differs from the manifest snapshot, a range escapes
the seat scope, a component or hunk mapping is missing, a line is truncated, a shard
exceeds 32 KiB, or hashes and ordering do not validate. The whole panel then uses the
existing no-packet source-reading flow. Post-run evidence records every hash-bound source
range opened through a packet or tool. A finding citation must intersect one such range.
Malformed or stale packet, prompt, stream, range, or result evidence invalidates the
whole narrowed panel, advances no coverage receipt, and triggers the existing full-scope
fallback.

## Adaptive plan closure

Plan evidence uses a dedicated `plan` phase bound to one immutable session-local plan
source, its SHA-256, and an atomically copied snapshot. Every cluster must have a unique
identifier, `Findings`, `Rule`, `Sites`, and at least one of `Test`, `Tests`, or
`Regression`. Every named path must resolve in the pinned snapshot. Basenames resolve
only when unique. Site locations may use one line, an inclusive range, or shorthand
ranges after the first path. Missing, ambiguous, escaping, special, stale, hard-linked,
opaque, non-UTF-8, or oversized inputs reject adaptive preparation.

The `Sites` row also names one representable `rg` or recursive `grep` expression used
to enumerate siblings. The only path operand is the literal repository root `.`.
`grep`, `egrep`, and `fgrep` require `-r`, `-R`, or `--recursive`. Tool-specific
allowlists reject file-sourced patterns, multiple patterns or path operands, working
directory changes, traversal filters such as globs or maximum depth, and ambiguous
commands. Every reviewer receives the complete plan and navigation index, then runs
each cluster expression from the repository root under the 80-result bound. Audit
records the canonical search engine and pattern, result hash, and hash-bound source
coverage for every named site or range. It rejects engine substitutions, pattern
semantics changes, redirects, and output modes that omit filenames or line numbers.
Proof uses the shell command's `--null` filename mode and must contain 1-79
`path<NUL>line:text` match records and every named `Sites` path. Native text search
cannot certify this proof because it cannot represent every filename unambiguously.
Producer errors cannot satisfy the search proof even when a later pipeline command exits
successfully.

The unique plan-completeness seat receives the full cumulative patch. Every other core
seat receives the same closure containing the changed patch for all resolved plan paths
and their changed one-hop local-import neighbors. This preserves every cluster under
each independent plan lens. Plan specialists may receive up to three literal source
shards. Surplus seats repeat soundness, simplicity, or tests deterministically; they do
not duplicate completeness. Adaptive plan evidence activates only when its aggregate
assigned patches save at least 10% against an all-full panel of the same size and the
closure stays within its byte ceiling.

`verify-panel` reuses the code panel's fresh manifest, prompt, stream, result, patch,
packet, citation, and source-proof validation without writing a receipt or advancing
`coverage-head.json`. Plan-artifact citations remain separate from original-source
citations and are valid only for exact lines of the manifest-bound plan snapshot. A
prepare, render, audit, or validation failure discards every narrowed result and reruns
all plan seats under a fresh legacy full-scope label. Agent-adapter plan panels always
use that legacy path because their native read hooks cannot be enforced.

## Measurement and acceptance

`rev-profile.py` reports per-panel full, assigned patch, delta, evidence, and avoided
word counts alongside actual provider input and output tokens. It also reports patch
proof calls, turns, visible bytes, expected and opened chunks, and chunk versus window
seat counts. It labels projected scope savings separately from metered provider usage.

Development regression uses the existing eight benchmark cases and preserved review
sessions. A true held-out claim requires fresh post-cutoff cases and a paired baseline
and candidate run with an identical exact roster. Adoption gates are:

- no lost baseline-hit P0/P1 or load-bearing truth row;
- structural recall no more than five percentage points below baseline;
- candidate passing-case count at least baseline;
- wrong plus contradicted findings at most baseline plus one;
- at least 10% fewer processed tokens in total and median paired case;
- incomplete, contaminated, or roster-mismatched pairs are invalid rather than wins.

The source-context packet is adopted only if paired exact-roster runs also use no more
than 70% of baseline source tool-output bytes and 80% of baseline tool rounds. Packet
mutation tests must prove that stale hashes, escaped paths, malformed ranges, overflow,
and truncated lines trigger the whole-panel no-packet fallback without advancing
coverage.

Before PR #812 measurement, static and synthetic tests must prove routing, freshness,
receipts, fallback, and exact roster and bundle preservation. The optimizer's final
four-seat panel must run with the new bounded protocol. PR #812 then supplies the
first same-PR measured result, including whether delta mode was smaller enough to
activate.
