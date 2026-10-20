# Cursor host and SDK Grok Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Release native Cursor hosting and optional Grok seats through the supported local SDK with canonical enforced read proof.

**Architecture:** Keep host packaging separate from provider transport. A local SDK driver exposes one bounded reader backed by the canonical Python authorization and byte-matching code; raw SDK events feed the existing auditor and receipts. Existing transports, defaults and initialized runtimes remain unchanged.

**Tech Stack:** Python 3, Bash, Node >=22.13, optional pinned @cursor/sdk 1.0.38 and matching platform helper, existing macOS/Ubuntu CI.

**Spec:** ../specs/2026-10-20-cursor-grok-design.md, user-approved option A.

## Global Constraints

- Normal independent reviews only for Council code; no Council self review.
- Heavy tests, builds and process fixtures run in CI. Light checks use ci-local; exit75 is unrun.
- Actual expected-red CI precedes implementation. Current-head macOS and Ubuntu CI and live qualification precede release.
- No default roster change, hidden CLI controls, private endpoint client, silent model/effort downgrade, credential extraction or automatic credential minting.
- Optional SDK installation is explicit and isolated. Missing runtime/key/model/qualification fails availability before a seat call.
- Use a private empty cwd and store, empty ambient sources/MCP/agents, no additional directories, no resume and retries disabled.
- Preserve existing complete-artifact exceptions and dependency-context semantics. Do not invent universal line/byte caps or blanket bans beyond the canonical reader.
- New signed commits only, sole-user attribution, no amend, no em/en dashes.
- Verification and subsequent mutations are sequential; failed shell assertions must stop the script before any commit or launch.

## Review Focus

- Optional runtime or key missing: default reviews still work and no hidden paid call occurs. Task1 and Task3 test this.
- Complete packet/context reads differ from source excerpts: canonical completeness and citation credit remain exact. Task1 and Task2 test this.
- Caller edits a source or swaps a path after preflight: reject the mismatched immutable identity before delivering data. Task2 tests this.
- Model/catalog names differ between CLI and SDK: only the SDK selection and observed run identity authorize the seat. Task3 and Task4 test this.
- Cursor discovers the wrong installed plugin or stack falls through to another host: record and validate actual loaded package identity. Task1, Task5 and Task6 test this.

---

### Task1: Define regression contracts before implementation

**Files:** Create tests/test_cursor.py and tests/test_cursor_sdk.py. Create plugins/review-council/tests/fixtures/cursor-sdk-* synthetic stream/catalog fixtures. Existing Python discovery runs these in the complete verifier; no workflow change is needed to discover them.

**Interfaces:** Tests define build-cursor-plugin.py build(output:Path), the cursor host value, cursor-sdk adapter identity, cursor_read({path,offset?,limit?}) and the driver modes catalog/probe/seat. Fixtures are explicitly synthetic, never live-qualification proof.

- [ ] Add host assertions for self-contained rev/stack discovery, cursor manifest, explicit host selection, package file modes and no implicit native Claude Agent seat.
- [ ] Add SDK absence/key absence tests, exact catalog parameter resolution tests and unchanged default-roster controls.
- [ ] Add read tests for whole authorized artifacts, bounded source ranges, packet completeness, historical/dependency context, stale blobs, traversal, unauthorized roots, malformed bounds, unauthorized symlinks and output mismatch.
- [ ] Add stream tests for the custom-reader server, exact completed text/call IDs, metadata-only discovery, unknown tools/servers, truncation, duplicates, error/partial streams, schema extraction and absent usage.
- [ ] Make missing feature implementations produce explicit target assertions rather than unrelated import/setup crashes. Keep existing suites running.
- [ ] Commit the test-only packet, obtain normal independent review, push the expected-red checkpoint as a draft feature PR and inspect exact-head macOS/Ubuntu failures. Accept only intended contract assertions and passing controls; preserve raw logs.

### Task2: Canonical bounded reader and SDK evidence normalization

**Files:** Modify plugins/review-council/scripts/lib/review-read-audit.py. Create plugins/review-council/scripts/lib/cursor-read-helper.py and cursor-sdk-reader.mjs. Extend tests/test_cursor_sdk.py.

**Interfaces:** Fixed Python helper argv binds repository, session, prompt, declared dependency roots, manifest path and its SHA256. Stdin contains only a closed {path,offset?,limit?} request. A successful private IPC response carries exact text and controller metadata; the model receives only the exact text. The Node export createCouncilReader(options) returns one SDK-compatible callback. Options are controller-owned; model arguments cannot change roots, helper commands or source identity.

- [ ] Verify Task1 actual red before editing production.
- [ ] Reuse canonical prompt_permissions, allowed_roots and validate_call plus canonical LF/range and repository-snapshot byte logic. Keep complete-packet reads unbounded in arguments; preserve byte_exempt and context-only dependency credit.
- [ ] Validate requests before opening source paths. Authorize only frozen source/blob or existing prompt-artifact/context classes; reject mutable aliases and unrecognized escapes.
- [ ] Execute only the fixed controller Python helper, without a shell or model-supplied executable/argv. Enforce helper failures and cancellation.
- [ ] Decode raw SDK custom-reader events into the existing native-read audit path. Require exact returned content, pairing and nontruncation; reject unexpected execution and preserve all existing packet, segment, context and finding gates.
- [ ] Run the focused checks in CI, obtain normal SPEC and TASK QUALITY reviews, apply findings and commit the reader task.

### Task3: Optional local SDK driver and runtime

**Files:** Create plugins/review-council/scripts/lib/cursor-sdk-driver.mjs, scripts/seats.d/cursor-sdk.sh, optional runtime package.json/package-lock.json and installation helper under plugins/review-council/scripts/cursor-sdk/. Extend tests/test_cursor_sdk.py.

**Interfaces:** Driver supports catalog, probe and seat commands. Catalog emits bounded sanitized model/variant/parameter JSON. Probe emits a versioned qualification receipt without secrets. Seat writes raw SDK events plus an explicit terminal record and returns the existing adapter exit classification. It never silently installs or logs in. The shell adapter consumes existing frozen MODEL/EFFORT/ROOT/PROMPT/session bindings.

- [ ] Pin package integrity/version and matching native helper; preserve user-supplied keys only in process environment. Refuse implicit app/CLI auth fallback.
- [ ] Configure local-only explicit key, private empty cwd/store, settingSources:[], mcpServers:{}, agents:{}, one custom reader, approved MCP metadata tools, no native reads/writes/shell/web/task and enableAgentRetries:false.
- [ ] Resolve exact ModelSelection id/params/maxMode from the supported account catalog. Select newest Grok with required xhigh; reject ambiguity or unavailable effort rather than using a CLI slug, Auto or fallback.
- [ ] Persist raw events and exact optional usage; require terminal run.wait() and disposal. Reject incomplete identity, unexpected tools/resources and malformed final findings.
- [ ] Test against an injected offline SDK double in CI. Keep double evidence distinct from actual provider qualification. Obtain normal review and commit.

### Task4: Roster, evidence, status and stack integration

**Files:** Modify scripts/lib/roster.py, rev-seat.sh, rev-evidence.py, rev-contract-check.py, lib/stream-summary.py, usage/profile integration as needed and stack.sh. Extend existing roster, evidence, seat, status and stack fixtures without weakening them.

**Interfaces:** Opt-in cursor-sdk adapter, one Grok model lineage and frozen SDK catalog/model/effort/runtime identities. Explicit cursor host never falls through to another host. Existing replacement contracts preserve exact resolved model/effort and require the same enforcement evidence.

- [ ] Add strict opt-in configuration with documented validation and unavailable/config error separation. Do not add the retired standalone grok adapter or change defaults.
- [ ] Bind SDK qualification and version identities into roster/probe/assignment/receipt validation. Missing qualification cannot receive enforced credit.
- [ ] Integrate canonical SDK auditing, final-schema extraction, statuses and unknown-cost handling; retain raw legacy Grok fixtures as historical data.
- [ ] Add explicit Cursor stack orchestration using supported Cursor-host instructions and existing CLI transports; never invoke a native Claude seat by fallthrough.
- [ ] Run integration cases in CI, normal-review cumulative changes and commit fixes separately.

### Task5: Native Cursor package and documentation

**Files:** Create scripts/build-cursor-plugin.py, plugins/review-council/.cursor-plugin/plugin.json, cursor-skills/rev/SKILL.md and cursor-skills/stack/SKILL.md. Update package inventory, README, docs/config.md, docs/seats.md and Cursor installation guide. Preserve existing Codex/Claude generation.

**Interfaces:** build(output:Path) produces a self-contained directory named review-council, explicit cursor host markers and native rev/stack skill entries using the canonical runtime. It validates ownership, staging and atomic replacement like the current Codex generator.

- [ ] Generate Cursor packaging without copying Claude discovery hooks or relying on external-target symlinks. Share canonical skill/runtime content rather than maintaining a divergent review protocol.
- [ ] Extend package/verifier inventory and mode checks, native manifest validation and no-default-change tests.
- [ ] Document optional SDK setup, supported authentication, strict availability refusals and known proof limits. Keep implementation details out of normal review instructions unless needed to act.
- [ ] Obtain normal independent review and current complete macOS/Ubuntu CI for the coherent feature head.

### Task6: Qualify, merge and release

**Files:** Add a bounded public live-qualification fixture/harness and release documentation; update synchronized version metadata only after feature qualification. Keep private credentials and run evidence outside tracked source.

- [ ] Prepare concrete SDK credential setup using the supported API-key or browser-login flow. If user interaction is needed, present the exact setup at that point; do not extract an existing CLI credential.
- [ ] Run a tiny actual Grok custom-reader fixture. Verify catalog/run model and xhigh agreement, exact read text/ranges/call IDs, approved live tool inventory, absent harmless ambient canaries, no retries, disposal and terminal success. Preserve failure evidence and refuse availability if it fails.
- [ ] Verify actual native Cursor application discovery and rev/stack invocation with loaded package/version identity. Metadata parsing alone is insufficient. Preserve existing host acceptance.
- [ ] Finish normal cumulative source reviews and fixes; require current-head full macOS/Ubuntu CI and all applicable live gates. A missing credential or failed live proof blocks Grok completion.
- [ ] Squash-merge after all gates, verify actual merge parent/tree, create signed minor release tag and GitHub release, and perform fresh isolated host/package readback. Proposed version is 0.7.0 unless repository compatibility requires another justified minor version.
- [ ] Record exact release identity and keep active wallet review runtimes unchanged. Update task/review results with actual checks and limits.

## Self-review and execution

Spec coverage maps to the six tasks above. Complete-artifact and dependency refinements preserve existing proof semantics; they do not lower requirements. Task interfaces use the native path/offset/limit vocabulary, while manifest/root binding stays controller-owned. Tests explicitly distinguish offline synthetic evidence from live qualification. No plan review will be run through Council.

Execution follows the user's approved architecture and request to carry the job through release. Use scoped workers and normal independent reviews, with root-owned integration, CI acceptance and release operations. No additional implementation-choice approval is needed for these routine steps.
