# Cursor setup

Council's native Cursor package provides `rev` and `stack`. Grok through Cursor is
an optional reviewer transport. Installing the host package does not enable it or
change the default roster. Application discovery and an actual Cursor-hosted Grok
review are separate qualification gates; offline tests do not establish either.

## Build and load the native package

From a checkout, build a real directory rather than a symlink:

```bash
python3 scripts/build-cursor-plugin.py --output dist/cursor/review-council
```

The output includes `.cursor-plugin/plugin.json`, `cursor-skills/rev/SKILL.md`,
`cursor-skills/stack/SKILL.md`, generated canonical workflow documents, scripts,
schema and fixtures. Rebuilding atomically replaces an owned Cursor bundle; an
unrelated directory is refused. Claude hooks and other hosts' discovery manifests
are absent. The builder does not install dependencies, authenticate or start a
model call.

For an isolated local installation, copy the generated directory to
`~/.cursor/plugins/local/review-council`, reload the Cursor window, and inspect
Customize for both skills and the expected version. Local imports must be allowed
by the account's administrator. A marketplace installation with the same name
takes precedence; confirm which package is actually loaded before running a
qualification. External-target symlinks are not supported by Cursor's local plugin
loader. These are Cursor's documented [local plugin loading rules](https://cursor.com/docs/plugins#test-plugins-locally).

Keep active installations unchanged during other reviews. A successful build or
manifest validation establishes package structure, not actual application discovery.

The signed-in Cursor CLI can load a package directly for a discovery check:

```bash
agent --workspace /absolute/project --plugin-dir /absolute/review-council \
  --model grok-4.7-xhigh --mode ask --sandbox enabled --trust -p \
  'Read the loaded review-council manifest and both native skill entries.'
```

Use an available model slug for your account and a trusted project. This path has
loaded the native manifest and both skill entries with Grok 4.7 256K Extra High
using normal CLI sign-in. It establishes CLI discovery only. GUI Customize
discovery, Council invocation and enforced SDK reviewer qualification are separate
acceptance gates.

## Invoke Council in Cursor

In a fresh chat, select the native `rev` or `stack` skill, or ask:

```text
Use review-council to review this branch against origin/main.
Use review-council for one round, read-only, on my uncommitted changes.
Use review-council to review these repositories as a dependency stack.
```

The loaded skill binds every runner to `REVIEW_COUNCIL_HOST=cursor`. Anthropic
reviewers use the signed-in Claude CLI. No native Claude Agent seat is created.
Stack legs use `cursor-agent` or `agent` and load the same package's rev skill.
They default to `NO_PUSH=1 NO_SQUASH=1`; existing stack configs can override these,
so inspect a config before using it. The orchestrator's host model is separate
from each reviewer's frozen model and effort.

## Optional Grok runtime and authentication

The optional runtime pins `@cursor/sdk` 1.0.38 and its matching platform helper.
It requires Node >=22.13 and npm. Prepare an isolated runtime explicitly; the
destination must not exist and its parent must already exist:

```bash
python3 plugins/review-council/scripts/cursor-sdk/install.py /absolute/private/parent/council-sdk
export REVIEW_COUNCIL_CURSOR_SDK_RUNTIME=/absolute/private/parent/council-sdk
```

The installer downloads the pinned packages, retains authenticated archives and
verifies installed bytes and modes. It does not qualify a model. Keep the runtime
private and outside the checkout; do not install into the plugin source tree.

Sign in with your existing Cursor account through the official SDK browser flow.
Set `PLUGIN` to the loaded package directory, then run setup explicitly:

```bash
node "$PLUGIN/scripts/lib/cursor-sdk-driver.mjs" auth-status
node "$PLUGIN/scripts/lib/cursor-sdk-driver.mjs" login
```

Complete normal Cursor sign-in in the browser. The SDK manages its stored login;
you do not obtain or paste a Grok key or API key. After runtime verification, login
has a five-minute operation deadline and a short cancellation grace. Ctrl+C cancels
setup. The driver discards the returned credential and
prints only a closed success state. See the [official authentication guide](https://cursor.com/docs/sdk/typescript#authentication)
and [browser sign-in API](https://cursor.com/docs/sdk/typescript#cursor-auth-login).

Public probe and reviewer calls also forward Ctrl+C or termination to their owned
SDK process. They retain the thirty-minute attempt deadline and allow two seconds
for cleanup before terminating that process. Cancellation returns a nonzero status;
it does not guarantee remote rollback or cleanup of detached helpers.

`auth-status` reports local SDK login presence, absence or an environment override.
It does not verify remote entitlement, revocation, model access or qualification.
Discovery and reviewer calls never start or renew sign-in automatically. If the
stored login expires or is revoked, run setup explicitly again. App/CLI sign-in is
not extracted or assumed to authenticate the SDK.

An explicit user or service-account `CURSOR_API_KEY` remains an optional private
environment override. A blank override uses the SDK's stored login. Never print a
credential, put it in arguments, commit it or include it in review artifacts.

## Qualification before opt-in

With the runtime and SDK sign-in available, the driver can read the authenticated catalog:

```bash
node plugins/review-council/scripts/lib/cursor-sdk-driver.mjs catalog
```

Use that catalog's exact `ModelSelection` for the newest available Grok at `xhigh`,
including its actual parameter IDs and values. Save a private JSON object with
`effort` equal to `"xhigh"` and `selection` equal to that complete `ModelSelection`.
Do not copy a CLI slug or invent a parameter. The output's parent must already be
a private directory owned by you, and the output file must not exist. The bounded
public probe then makes a real model call:

```bash
node plugins/review-council/scripts/lib/cursor-sdk-driver.mjs probe \
  --selection /absolute/private/grok-selection.json \
  --output /absolute/private/grok-qualification.json
export REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION=/absolute/private/grok-qualification.json
```

Retain the receipt and its sibling evidence directory. A valid receipt binds the
runtime, SDK catalog, model, effort and successful source-delivery proof; moving or
editing its evidence can invalidate it. Synthetic fixtures cannot create live
qualification. After a valid probe, add these keys to the existing Council config:

```json
{
  "cursor_sdk_models": ["latest-grok"],
  "cursor_sdk_effort": "xhigh",
  "extras": false
}
```

Other configured seats remain in the roster. A missing runtime, authentication, exact model,
effort or qualification refuses availability before a reviewer launch. Invalid
settings are configuration errors. There is no fallback to a direct xAI adapter,
older model, lower effort or unqualified CLI transport. See [configuration](config.md).

SDK seats support prepared code reviews, including read-only code, numbered rounds
and Cursor CLI stack legs. A numbered panel binds its requested minimum, actual
seat order, legacy lenses and final emphases in one manifest; every seat receives
the full cumulative patch. Its numeric receipt cannot become adaptive verification
or an adaptive coverage predecessor. Existing bounded repair preserves its exact
parent assignment and valid siblings.

SDK document-list reviews are unsupported and refuse before authentication,
catalog discovery or provider probes. Code fix-plan manifests remain supported.
The opaque `codex-review` extra cannot consume numeric SDK evidence and refuses
when its configured round is scheduled. The example explicitly removes extras;
the default remains `extras:true`. A dormant extra does not block other rounds.

The driver offers one bounded custom reader in a private workspace with ambient
settings, MCP servers and agents empty and SDK retries disabled. Backend tool
restrictions are the prevention contract. Stream auditing must separately prove
approved tools, exact completed text, call pairing and terminal success; callback
logs alone prove no delivery. Missing usage or cost remains unknown. This does not
establish a separate local executor deny mechanism.

A completed probe still leaves the native application gate: invoke Council from
the actually loaded Cursor package, run a Grok reviewer, inspect the frozen model
and enforced evidence receipts, and exercise stack routing. Until both live gates
pass, describe the feature as unqualified rather than claiming Grok support is
complete.
