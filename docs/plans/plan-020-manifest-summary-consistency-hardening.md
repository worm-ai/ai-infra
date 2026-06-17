# Plan: Manifest Summary Consistency Hardening

## Metadata

- ID: plan-020-manifest-summary-consistency-hardening
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-019 are closed with a production-oriented local YAML DAG stack, bounded tool/ReAct/MCP/provider boundaries, structured reports, SQLite evidence, provenance snapshots, redaction/governance, production demo contract, and offline evidence bundle verification. Plan-019 independent audit left one non-blocking follow-up: manifest status, redaction_summary, and verification_input_summary are not cross-checked against report.json and inputs.json, so summary-level manifest tampering can be internally consistent after digest refresh while weakening audit semantics.
- Owner: engineering
- Created: 2026-06-17T13:59:57.072410+00:00
- Updated: 2026-06-17T14:47:51.846216+00:00

## Goals

- Strengthen evidence bundle offline verification by cross-checking manifest summary fields against bundled report and inputs evidence.
- Detect tampering of manifest status, redaction_summary, and verification_input_summary with structured CLI/SDK verification failures.
- Keep the enhancement bounded to DAG evidence/auditability and preserve existing bundle layout compatibility.

## Non-Goals

- No API, frontend UI, hosted service, scheduler, distributed execution, A2A, PlanExec runtime, or Super-Agent runtime.
- No change to DAG execution semantics, workflow validation semantics, ReAct/provider/MCP behavior, or SQLite run-store behavior.
- No signing service, external trust authority, encryption, remote artifact store, credential manager, or live external dependency.

## Exit Criteria

- verify_evidence_bundle fails when manifest status differs from report.json status.
- verify_evidence_bundle fails when manifest redaction_summary differs from report.json summary.redaction or expected zero-redaction summary.
- verify_evidence_bundle fails when manifest verification_input_summary differs from the computed summary of inputs.json and bundled report input_summary.
- ai-infra verify-bundle exposes the same summary consistency failures with actionable structured checks and nonzero exit code.
- Existing clean bundles and prior tamper/missing/malformed/run-mismatch/redaction-leak cases continue to verify as expected.
- Focused verifier demonstrates clean bundle success and status/redaction/input-summary tamper failures without live external services.

## Commitment Phase State

### Stable State Now

- Plan-019 provides offline evidence bundle verification with per-file digests, file coverage, document schema checks, run identity checks, and redaction leak checks.

### Active Change Pressure

- Independent audit identified that manifest summary fields are not yet cross-checked against bundled evidence, leaving a small but concrete audit hardening gap.

### Target Stable State

- An offline evidence bundle verifier rejects both content tampering and summary-level manifest tampering while preserving deterministic local audit behavior.

### Conversion Proof

- Failing-first tests, verifier implementation, focused CLI script, full pytest, ABH verification, independent audit, close, commit, and push prove the hardening.

### Residual Pressure

- Cryptographic signing, external trust roots, release packaging, API/UI, live provider smoke tests, remote MCP transports, PlanExec, Super-Agent, A2A, and distributed governance remain future phases outside plan-020 scope. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run python scripts/verify_cli_bundle_integrity.py
- uv run python scripts/verify_cli_production_demo.py
- uv run python scripts/verify_cli_redaction_governance.py

## Closure Evidence

- Passing tests covering status, redaction_summary, and verification_input_summary consistency failures for SDK and CLI.
- Passing focused verifier proves summary tamper failures and clean bundle compatibility.
- ABH verification confirms plan-020 exit criteria against the active industrial agent orchestration attractor.
- Independent audit confirms the work strengthens DAG evidence auditability without introducing API/UI, PlanExec, Super-Agent, A2A, distributed execution, or live dependencies.
- audit-020-manifest-summary-consistency-hardening

## Verification Runs

- ver-4f5310df7478
- ver-84cae4c509dc
- ver-57a3fd0f34aa
- ver-37d42a7004c2
- ver-0e3473f40ea5

## Audits

- audit-020-manifest-summary-consistency-hardening
