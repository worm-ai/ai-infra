# Plan: Evidence Bundle Integrity and Offline Verification

## Metadata

- ID: plan-019-evidence-bundle-integrity-offline-verification
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-018 are closed with a production-oriented local YAML DAG stack: LangGraph-backed execution, bounded python/shell/http/MCP tool nodes, bounded ReAct atomic nodes with OpenAI-compatible provider boundary, structured reports, SQLite evidence, provenance snapshots, redaction/governance, local artifact evidence bundles, and a production-facing README/demo contract. Evidence bundles can be exported, but they are not yet self-verifying audit artifacts: manifests do not provide full content digests, there is no standalone offline bundle verifier, and tampering/missing-file detection is not exposed through CLI/SDK.
- Owner: engineering
- Created: 2026-06-17T12:38:16.869968+00:00
- Updated: 2026-06-17T13:53:11.748637+00:00

## Goals

- Turn exported DAG evidence bundles into self-verifying local audit artifacts with manifest digests and deterministic offline verification.
- Add CLI and SDK verification for evidence bundle integrity that works without the SQLite run store or original workflow source.
- Detect tampered, missing, malformed, or secret-leaking bundle contents with actionable verification evidence while preserving current DAG execution semantics.
- Keep the enhancement bounded to DAG evidence/auditability so it strengthens traceability and governance without introducing new orchestration layers.

## Non-Goals

- No API, frontend UI, hosted service, remote scheduler, distributed execution, A2A, PlanExec runtime, or Super-Agent runtime.
- No change to DAG scheduling/execution semantics, node contracts, ReAct reasoning behavior, provider calls, MCP runtime behavior, or workflow validation semantics except where bundle verification requires read-only parsing.
- No signing service, external trust authority, remote artifact store, encryption system, or credential manager.
- No live OpenAI-compatible provider or live remote MCP dependency in tests, verification, or closure.

## Exit Criteria

- Exported evidence bundles include a deterministic manifest with per-file SHA-256 digests, bundle schema/version metadata, run id, workflow id, provenance summary, redaction summary, and verification input summary.
- A new CLI command can verify an evidence bundle offline and report pass/fail with actionable checks without requiring the local SQLite state directory or original workflow file.
- Python SDK exposes bundle verification so applications can validate exported evidence without parsing CLI output.
- Tampered file content, missing required files, malformed JSON/YAML where applicable, manifest/run mismatch, and redaction-sensitive leaked values are detected and surfaced as structured verification failures.
- Existing export-bundle behavior remains backward compatible for consumers of the zip layout, and existing examples/verifiers continue to pass.
- Production demo or focused verifier demonstrates export-bundle then offline verify for success and representative tamper/missing-file/redaction failure cases.

## Commitment Phase State

### Stable State Now

- Closed plan-018 provides a production-facing local DAG kernel and demo contract with exportable evidence bundles, but exported bundles are not yet independently verifiable audit artifacts.

### Active Change Pressure

- Production-grade delivery needs evidence bundles that remain trustworthy after leaving the local run store; otherwise auditability depends on mutable local state and manual inspection.

### Target Stable State

- A DAG run evidence bundle can be exported, copied, and verified offline with deterministic integrity and redaction checks, making the local orchestration kernel more auditable and production-deliverable.

### Conversion Proof

- Manifest digest generation, offline bundle verifier, SDK/CLI surfaces, tamper/missing/redaction tests, focused verifier script, ABH verification, independent audit, close, commit, and push prove the stable state.

### Residual Pressure

- Cryptographic signing, external trust roots, remote artifact stores, release packaging, API/UI, live provider smoke tests, remote MCP transports, PlanExec, Super-Agent, A2A, and distributed governance remain future phases outside plan-019 scope. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run python scripts/verify_cli_bundle_integrity.py
- uv run python scripts/verify_cli_production_demo.py
- uv run python scripts/verify_cli_redaction_governance.py

## Closure Evidence

- Passing tests covering manifest digests, offline verify success, tamper detection, missing-file detection, malformed content detection, run mismatch detection, redaction leak detection, CLI output, and SDK API.
- Passing CLI verifier proves evidence bundle export and offline verification from temporary local state without relying on live external services.
- ABH verification confirms plan-019 exit criteria against the active industrial agent orchestration attractor.
- Independent audit confirms bundle integrity work strengthens DAG auditability without introducing API/UI, PlanExec, Super-Agent, A2A, distributed execution, or live external dependencies.
- audit-019-evidence-bundle-integrity-offline-verification

## Verification Runs

- ver-3a9ffe7ea4ee

## Audits

- audit-019-evidence-bundle-integrity-offline-verification
