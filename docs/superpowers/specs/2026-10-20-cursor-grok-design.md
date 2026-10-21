# Cursor host and optional Grok seats

Status: user approved option A, native Cursor host plus local SDK Grok with strict qualification, on 2026-10-20. Existing default roster remains unchanged. Product implementation and dependency installation have not started.

## Intent and accepted scope

Support Council inside the Cursor application and support Grok reviewer seats accessed through Cursor. The user explicitly selected both scopes and requested a release. Council changes receive normal independent reviews, not Council self review. Existing wallet reviews retain their frozen runtime, resolved models, efforts and evidence.

Grok support is opt-in. No default roster change, replacement of an existing seat, lowered proof requirement or additional laboratory credit is implied. Native host orchestration and reviewer transport are separate capabilities.

## Verified constraints

The official Cursor CLI supports headless automation and code review. A live official CLI probe selected Grok 4.7 Extra High and returned an exact one-line native Read result. This establishes basic compatibility only.

Cursor staff confirm that the CLI lacks documented per-run controls establishing a no-hooks/no-plugins/no-subagents configuration. An internal context-exclusion flag was rejected for this account, team or model. Do not ship a production adapter that depends on undocumented flags, assumes private config directories remove managed startup resources, or claims stream monitoring prevents effects that precede telemetry.

Cursor recommends its local SDK for documented ambient-configuration and toolset controls. The current public package is 1.0.38 and requires Node >=22.13. Its normalized native Read declarations omit bounded ranges. Explicit SDK browser sign-in uses the existing Cursor account and stores its own expiring credential through the public SDK. No manually copied Cursor or Grok key is required. A private environment key override remains optional; app and CLI credentials are not extracted. No credential extraction or login has occurred.

## Architecture requiring a user choice

| Option | Cost | Risk | Result |
| --- | --- | --- | --- |
| A: Native Cursor host plus local SDK Grok seats | Optional pinned SDK runtime, Node 22.13+, explicit SDK browser sign-in, custom bounded reader | Qualification must establish tool inventory, delivered bytes and model identity | Recommended route to preserve enforced Council proof using documented controls |
| B: Native Cursor host plus official CLI Grok seats with partial coverage | Reuses existing CLI login and native stream | Cannot claim enforced startup isolation; must visibly remain partial and cannot satisfy enforced-seat gates | Basic Grok participation with an explicit proof limitation |
| C: Native Cursor host now, defer Grok transport | Smaller release, no new SDK credential | Does not complete requested Grok support until a supported CLI control exists | Host support only; Grok remains unavailable |

The recommendation is A. Choosing A changes the proposed seat transport from the originally investigated CLI to the official SDK. That is a proposed implementation choice, not a user-approved requirement. Release 0.7.0 is a proposed minor-version choice, not a user-selected number.

## Native Cursor host

Add an explicit cursor host identity and dedicated self-contained rev and stack skills, with the supported Cursor plugin manifest. Generate host packages from one canonical runtime and instruction source. Do not route Cursor implicitly through Claude native Agent behavior. Preserve Claude and Codex packages and their historical contracts.

Cursor-hosted Council can invoke existing supported transports even when the optional Grok transport is unavailable. Host discovery, skill identity, rev invocation and stack routing are separate acceptance gates. A manifest parse or CLI plugin flag alone does not prove application discovery. Use an isolated local plugin installation and verify actual loaded identity without changing shared installed versions used by other work.

## Recommended Grok transport

Use a local SDK child process with normal SDK stored-login resolution or an optional private environment key override, private empty workspace and private store. Supply empty settingSources, inline MCP servers and agents; no additional directories, resume or reload. Disable SDK agent retries. Do not invent a team identity, bypass account restrictions or use private service endpoints.

Expose exactly one custom bounded reader through the SDK's supported custom-tool facility. Offer the MCP capability group required for that reader and exclude native file, shell, web and delegation tools. Enumerate permitted discovery events and the synthetic custom-reader server explicitly. The documented backend toolset restriction and empty ambient sources are the prevention contract; the stream audit remains the acceptance gate. Do not describe the SDK as providing an independently proved local executor deny mechanism.

Builder refinement: the reader accepts the existing native Read vocabulary, path with optional positive offset and limit. The controller binds the frozen manifest, roots and prompt through fixed helper arguments, rather than trusting model-supplied identity. Complete prompt-authorized packet artifacts omit bounds so the canonical complete-packet check remains effective. It validates types, bounds, byte ceiling, path membership and immutable source identity before accessing source bytes. It rejects traversal, unrecognized symlink escapes, special files, mutable aliases, extra fields and unknown roots. Preserve canonical declared dependency-root resolution and complete-artifact exemptions; dependency context never earns immutable source or citation credit. Existing canonical Council limits apply. It returns exactly the source or artifact text expected by the canonical auditor, without a metadata wrapper. Identity and range metadata stay in bound call arguments and the controller receipt. Implementation must reuse existing packet and source validation rather than introduce a second permissive validator.

The adapter records callback arguments, call identity and the exact return hash. Credit requires a matching SDK completed event containing the same delivered text and arguments. Callback logs alone do not prove delivery. Missing or conflicting IDs, unknown tools or servers, errors, truncation, malformed output, incomplete streams and source mismatch fail the seat. Canonical source-packet, segmentation, citation and finding checks remain mandatory.

Resolve the newest available Grok family and required xhigh effort from the authenticated SDK catalog. Freeze the resolved model ID, parameters, observed run model, SDK/native helper versions and integrity, transport and model lineage. Do not reuse CLI slugs without catalog proof. No Auto, fallback to an older model, silent downgrade or unrecorded retry. Record one Grok laboratory lineage, with Cursor as transport, rather than counting Cursor and the model laboratory twice. Missing usage or cost stays unknown.

## Installation and authentication

Keep SDK support optional so existing users do not require Node or SDK sign-in. Pin and verify the qualified SDK and matching platform helper as runtime dependencies; do not vendor proprietary implementation. An installation helper may prepare an isolated dependency directory after design approval. Shared Cursor configuration, login files and Keychain entries are not modified by a reviewer seat.

Provide explicit, cancellable SDK browser sign-in and sanitized local status as setup commands. Use the SDK's own stored-login resolution when an environment override is absent or blank. Accept an optional explicit API key through a private environment lease; never print it or place it in process arguments or artifacts. Authentication failure reports unavailable without creating a reviewer. No automatic login, renewal or persistent credential change is part of discovery or a review. Check account access and billing availability through supported APIs without extracting app or CLI credentials or treating their login state as SDK authentication.

## Qualification and release gates

1. CI regression tests fail before production changes for host routing, packaging, strict configuration, malformed streams and reader authorization. Preserve all thresholds and use full macOS and Ubuntu CI for the final head.
2. Reader tests prove authorization happens before file access and cover existing source-packet/range/hash limits and immutable-root edge cases. No helper can execute shell or fetch network data.
3. A tiny public live fixture proves SDK catalog and actual Grok model/effort agreement, complete approved tool inventory, exact bounded text delivery and call pairing, absent ambient canaries, terminal success and known truncation behavior. Never run Council against its own source for this acceptance.
4. Negative fixtures reject unknown native/MCP tools, non-custom servers, missing completions, malformed/error/truncated results, source mismatch, invalid final schema, cancellation and partial streams. Disable automatic agent retries and preserve failures.
5. Independent normal source reviews cover all code and fixes. Re-review material changes. No Council self review or claim that fixture participation is a Council code review.
6. Verify native application discovery and invocation, existing Claude/Codex compatibility, stack behavior, package content/modes and fresh host installation. Publish a signed release only after current-head CI and all applicable live gates pass.

If the SDK fixture cannot establish enforced evidence, stop that transport and preserve the failure. Do not silently ship option B under option A's label. If credentials or host interaction prevent a live gate, report the precise blocker and continue independent implementation or wallet work. The proposed release must accurately state what is qualified; it must not claim the requested Grok capability completed while its required live gate is unrun.

## Calls left to the builder

The builder chooses module layout, generated-file organization, exact documented SDK catalog API, stream normalization details, private dependency-store layout and CI fixture structure. These choices must preserve the constraints above. They may simplify the architecture after a source-backed check, but cannot replace enforced proof with partial coverage, change the roster or mint credentials without the user's choice.

## Primary references

- https://cursor.com/docs/cli/headless
- https://forum.cursor.com/t/does-using-oh-my-pi-s-cursor-provider-or-an-openai-compatible-proxy-to-the-same-endpoints-violate-cursor-s-tos/167778/5
- https://forum.cursor.com/t/cursor-cli-a-locked-down-headless-mode-file-tools-only-no-hooks-mcp-plugins-enforced-tool-allowlist/173496/14
- https://cursor.com/docs/sdk/typescript
- https://cursor.com/docs/plugins
- https://cursor.com/docs/reference/plugins

Source feasibility and public declaration identities are preserved under recon/; these are evidence, not proof that the unimplemented transport already works.
