# Plan review workload and recovery

## Goal

Keep large fix-plan reviews inside verifiable bounds, make the cost visible before launch, and keep plan review moving through the configured replacement chain after an invalid seat.

## Findings from #1752

- The patch was already split into nine bounded artifacts. Prepared task capacity estimated 35 turns and twelve mandatory source windows; it did not exceed the deterministic source-read cap.
- Codex has no provider turn limit configured, so the 35-turn estimate was visible only in the manifest and did not trigger a refusal. Sol later completed the same assignment with a valid audit, so the evidence does not support splitting this PR.
- Luna's audit failed after it combined two exact, one-line reads in one shell command. The audit intentionally rejects compound source batches.
- A subsequent plan edit invalidated the prepared evidence. Council already detects the hash mismatch, but the workflow needs to state clearly that any plan correction requires a fresh evidence label and render.

## Changes

- Add a repository rule requiring one independent normal reviewer for Council changes.
- Render the existing workload estimate in the assignment prompt, including patch chunk count, mandatory source reads, projected turns, and whether a provider hard limit exists.
- Make Codex source-read wording explicit: separate tool calls may be batched within the turn budget, but a shell command may contain only one source-producing pipeline. Show the exact invalid `sed ... && sed ...` pattern.
- Replace the plan gate's one-replacement stop with repeated escalation through the configured chain. Preserve completed evidence; each new attempt uses a fresh label and binds to the original failed assignment. If the plan changes, reprepare and rerender before another launch.
- Make `phase=fix` reject a plan manifest whose plan hash no longer matches the current `fix-plan.md`, including successful replacement labels.

## Verification

- Inspect the rendered prompt-generation path and the escalation helper contract.
- Run the independent normal reviewer on the completed Council diff. Do not run Review Council against this repository.
- Do not run the test suite unless the user asks for verification.
