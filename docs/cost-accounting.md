# Cost accounting and compact session state

The first cost controls reduce invalid launches and repeated orchestration context
while retaining the configured reviewers, efforts, evidence and certification gates.

## Usage

```bash
python3 plugins/review-council/scripts/rev-profile.py /tmp/rev-SESSION \
  --host-log /path/to/host-session.jsonl --json
```

Host logs currently accept native assistant JSONL records, not terminal-only host
streams or cumulative token-count envelopes. They are optional, explicitly supplied,
local inputs. Nothing scans a home
directory or exports transcript content. Repeating `--host-log` accepts several
logs; resolved duplicate paths and shared native assistant message IDs are deduplicated.
Reviewer leaf messages are excluded from the host totals.

| Quantity | Interpretation |
| --- | --- |
| Processed tokens | Input plus output, not the billed amount |
| Uncached input | Input remaining after provider cache categories |
| Reasoning output | A subset of output, never added again |
| Cache writes | Total plus reported 5-minute and 1-hour categories |
| Known cost calls | A reported dollar amount, including an explicit zero |
| Unknown cost calls | No reported dollar amount; not a free call |
| Host envelope | All supplied host messages, including unrelated work |
| Council operations | Host messages with an executable Council command and exact canonical session path |

The host operation subset still includes the full context of each matching request.
It is associated usage, not exclusive causal cost. Native streaming assistant records
use message IDs to avoid counting repeated partial records; terminal CLI totals and
native records represent alternatives, not additive usage. Separate terminal CLI
attempts without shared request identities remain separate observations.

Reviewer cost counters describe attempts. A native attempt is known only when every
included assistant request reports dollars; otherwise it is unknown even when the
reported-dollar sum includes some requests. Host counters describe deduplicated
assistant requests. Both retain any explicitly reported partial dollar sum.

Failed or incomplete results can have metered usage. A schema-valid result headed
`INCOMPLETE PROOF` is not a completed review. Malformed usage records are disclosed.
Reported dollars are not converted to subscription quota or Codex credits. Compare
measurements with the same roster signature and accounting basis.

## Launch prechecks

For changes within the existing provider-boundary scope, preflight runs deterministic
fixture replay before paid availability probes. The reusable static pass is keyed by
checker inputs, replay runner and policy. Static results cannot certify a review.
After probing, the authoritative receipt still binds the subject, exact roster and
provider versions. A matching checked static result avoids running the fixture suite
twice during one preflight. Ordinary repositories retain the existing scope rules.

Codex availability probes use private homes and the same configuration isolation
as review launches. Claude probes disable dynamic sections and slash commands in
addition to their existing isolation controls. Authentication, requested models and
requested efforts remain part of the original provider contract.

## Session briefing and local watch

```bash
python3 plugins/review-council/scripts/rev-context.py /tmp/rev-SESSION
python3 plugins/review-council/scripts/rev-context.py /tmp/rev-SESSION \
  --watch --duration 600 --json
```

The briefing reads current state and roster identities and names canonical artifacts.
It does not copy logs or the findings ledger into another state file. Missing results,
invalid results, audit failures and incomplete proof remain visible even after exit 0.
`ready-for-collection` means the result is ready for existing collection checks;
certification is always `not evaluated`.

The watch emits initial state, changes and scheduled ten-minute events locally.
Changes never reset that schedule. Keep the host's required status mechanism armed
and relay every scheduled event. The default duration is ten minutes; extend it in
bounded executions as needed. A declared terminal phase stops watching without
inferring that coverage or receipts passed. Foreground updates remain required.

## Prompt compilation and structured baseline

The prompt renderer includes only obligations for the active adapter, lens and
evidence delivery mode. It derives read and refutation budgets from the shared
limits. Assigned evidence, hashes, independence, counterexamples, result schema and
incomplete-proof handling remain required.

An optional `baseline.json` replaces `baseline.md` in the reviewer prompt:

```json
{
  "schema_version": 1,
  "checks": [
    {
      "command": "python3 -m unittest discover -s tests -v",
      "outcome": "failed",
      "applicability": "Existing provider contract tests",
      "failure": "One pre-existing fixture assertion fails",
      "log": "baseline-unittest.log"
    }
  ]
}
```

The checks list is nonempty. Outcomes are `passed`, `failed` or `skipped`. Every check
includes a nonempty command and applicability; only failed checks include required
failure evidence. A log reference is
optional. Duplicate keys, unsupported fields and invalid types fail rendering rather
than silently losing baseline information. Keep all applicable checks and explicitly
record why any check was skipped. Sessions without JSON retain `baseline.md`.

## Measuring savings

Prompt words and briefing size provide deterministic comparisons. They do not prove
provider cost savings or equal review recall. Live comparisons need the same source,
roster, cache conditions and accounting categories, repeated cases and retained
material findings. This first wave makes no reduction to seat count, phase coverage,
maximum effort or final certification.
