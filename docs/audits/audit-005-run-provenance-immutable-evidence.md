# Audit: plan-005-run-provenance-immutable-evidence

## Metadata

- Audit ID: audit-005-run-provenance-immutable-evidence
- Plan: plan-005-run-provenance-immutable-evidence
- Auditor: independent-read-only-subagent
- Auditor Context: Subagent Copernicus 019ecb32-d5c9-7833-9809-26300c7299f6; read-only ABH re-audit after initial fail findings were fixed; reviewed active attractor boundaries, plan-005, provenance implementation, report/verify behavior, tests, scripts/verify_cli_provenance.py, and verification ver-27b81446d240.
- Independence: independent
- Verification ID: ver-27b81446d240
- Status: complete
- Created: 2026-06-15T12:25:43.368883+00:00
- Updated: 2026-06-15T12:40:30.148981+00:00

## Scope

Audit plan-005 run provenance and immutable evidence against the active industrial Agent orchestration attractor, plan goals, non-goals, exit criteria, code diff, tests, CLI report/verify behavior, and verification ver-27b81446d240. Do not edit files.

## Evidence Reviewed

- docs/plans/plan-005-run-provenance-immutable-evidence.md
- .abh/verifications/ver-27b81446d240.json
- src/ai_infra/config.py
- src/ai_infra/provenance.py
- src/ai_infra/store.py
- src/ai_infra/runtime.py
- src/ai_infra/reporting.py
- tests/test_runtime_store.py
- tests/test_run_report.py
- tests/test_cli.py
- scripts/verify_cli_provenance.py

## Semantic Conservation

- Check whether any in-scope commitments disappeared, weakened, or moved to non-authoritative artifacts.
- Distinguish J-flow-only evidence from R-flow evidence that reduces uncertainty through proof, decision, or owner-doc alignment.
- Cite repository evidence for any semantic conservation gap.

## Findings

| Severity | Finding | Evidence | Recommendation |
| --- | --- | --- | --- |
| P3 | ABH script artifact readability was initially opaque; now improved by compact stdout summary. | scripts/verify_cli_provenance.py prints run id, workflow/input hashes, verify status, and drift summary; ver-27b81446d240 records that stdout. | No blocking follow-up; future ABH ergonomics can add richer structured artifacts if dynamic command chaining is supported. |

## Verdict

- Result: partial
- Rationale: Independent read-only re-audit found no P1/P2 blocking findings after provenance fixes. Workflow now stores load-time source snapshots, source-only SDK workflows persist snapshot/hash and validate from persisted evidence, report exposes snapshot/hash/input hash/git/env provenance, tests cover precise hash, source mutation, source-only SDK, and CLI drift, and fresh verification ver-27b81446d240 includes a real CLI provenance script with report/verify evidence. Result is pass-with-notes because the audit used a non-blocking P3 note about artifact readability, which was addressed by printing a compact CLI provenance summary.

## Follow-Ups

- No blocking follow-up. Future audit ergonomics can add richer structured artifacts if ABH supports dynamic command chaining.

## Supplemental Final Audit

- Auditor Context: Subagent Newton 019ecb43-5ec2-7ba3-8a7e-cdb21c65fa93; final read-only audit after fallback snapshot coverage, CLI stdout summary, and verification refresh.
- Verification ID: ver-2581b7555848
- Findings: No P1/P2/P3 findings.
- Verdict: pass
- Evidence: fallback snapshots are schema-compatible and reloadable, hand-constructed Workflow fallback is covered by tests, CLI provenance script prints readable run/hash/drift evidence, ABH plan status reports fresh pass verification, and attractor boundaries remain limited to DAG run provenance without API/UI/MCP/ReAct/PlanExec/Super-Agent expansion.
