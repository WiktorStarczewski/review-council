# Observable review quality score v1

The score compares adjudicated correctness and observable evidence without rewarding
verbosity or claiming to measure comprehension. Truth, rubrics and adjudications remain
outside reviewer prompts and reviewed source roots.

| Component | Points | Measurement |
| --- | --- | --- |
| Defect recall | 55 | Truth severity weights P0=8, P1=4, P2=2, P3=1 |
| Precision | 15 | True positives and valid extras divided by nonduplicate findings |
| Citation accuracy | 10 | Manual accurate verdict plus overlap with every matched truth range |
| Critical flow coverage | 15 | Every required file and line range exposed without gaps |
| Useful hypotheses | 5 | Verified or refuted predefined hypotheses with required source exposure |

The score_run API takes case, result, the existing raw correctness adjudication,
audit and behavior adjudication, plus optional verified_provenance. The existing
scorer validates every finding exactly once and binds the entire result including
its summary. All scores remain unknown before that adjudication. Missing truth
severities, citation adjudication or behavior evidence remain explicitly
unavailable; weights are never rescaled. A core score has a maximum of 80 and is
screening only. Retention requires the full score out of 100.

The behavior rubric has schema version 1, a measurement description, critical flows
with id, required_sources and rationale, and hypotheses with id, description and
required_sources. Each source is a literal relative path and an inclusive one-based
line range. IDs must be unique and both collections must be nonempty.

The manual behavior envelope binds schema version 1, canonical case_sha256,
rubric_sha256, findings_sha256, audit_sha256 and evidence_manifest_sha256. Absent
audit or rubric identities are null. Its citations adjudicate every finding exactly
once with finding, an accurate or inaccurate verdict, and a concrete source or
reproduction reason. Its hypotheses adjudicate every rubric hypothesis exactly once
with hypothesis, a verified, refuted or untested verdict, and a concrete reason.
Reasons are human judgments; the scorer rejects blank reasons and does not interpret
prose. A manual inaccurate citation always overrides range overlap. False positives
and duplicates do not earn citation points. Valid extras use manual citation
verdicts because they have no planted truth range.

Optional novel_scenarios contain unique id, verdict (verified, refuted or speculative),
reason and required_sources. A grounded novel scenario can replace at most one
untested predefined hypothesis per run. More scenarios or prose earn no additional
points. Grounded and speculative counts remain separate diagnostics.

The caller validates raw result, prompt and stream hashes, the frozen subject and
manifest, and the audit through replay when needed. Trusted verified_provenance
binds canonical case/result/audit hashes, manifest identity and snapshot_tree.
Raw result file hashes differ from canonical result JSON hashes.

Exposure uses gapless audited original ranges and optional qualified packet ranges.
The latter are snapshot_packet_ranges with path, line_start, line_end and blob_tree:
the caller qualifies completed assigned shards against the manifest. The scorer
excludes base-tree ranges and requires current-tree packet ranges to be contained in
audited packet exposure. Missing qualification falls back to original reads.
Repeated ranges do not increase credit. Filenames, summaries and aggregate audit
counters establish no coverage. This remains an exposure proxy, not proof of
reasoning, and trusts the caller's provenance verification.

Clean cases have no planted defects: the 55-point component measures specificity
and is earned only with zero adjudicated false positives. Fully adjudicated clean
empty output earns precision and citation points. Empty or duplicate-only output
on a defect case earns zero precision and citation points. Diagnostics state this
convention explicitly and keep clean-case weighted recall null.

The compare_quality API accepts baseline and candidate rows with valid and
run_quality. Its frozen default policy permits at most a 3-point loss, requires
candidate quality at least 90, weighted recall at least 0.90 on defect cases, all
P0/P1 truth defects found, no lost P0/P1 hits, and no added false positives. Lower
severity losses can pass only within these gates. Both runs require valid audits,
full scores and matching score/case/rubric identities. Policy changes are explicit
and returned with a canonical policy hash. Legacy core comparisons cannot retain
an optimization. Retrospective truth annotations are new hashed inputs and never
replace frozen original cases or artifacts.
