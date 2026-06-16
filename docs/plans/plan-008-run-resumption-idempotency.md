# Plan: DAG Run Resumption and Idempotent Execution

## Metadata

- ID: plan-008-run-resumption-idempotency
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-007 are closed with local YAML DAG execution, bounded tool nodes, structured reports, hardened workflow schema validation, immutable provenance, explicit failure policy/retry semantics, and node output contract evidence. Runs are still one-shot: an interrupted or failed run cannot safely reuse completed node evidence and rerun only failed or missing DAG nodes.
- Owner: engineering
- Created: 2026-06-16T03:11:46.497751+00:00
- Updated: 2026-06-16T04:26:14.053368+00:00

## Goals

- Support local DAG run resumption from persisted SQLite evidence while preserving the production-first DAG boundary.
- Reuse completed node outputs and contract evidence when safe, and rerun failed or missing nodes under existing failure policy semantics.
- Persist resume evidence and expose skipped/rerun/resumed node behavior through CLI/SDK reports and verification.

## Non-Goals

- No web API or frontend UI.
- No remote scheduler, distributed queue, background worker, or external idempotency service.
- No MCP runtime, LLM-backed ReAct runtime, PlanExec runtime, or Super-Agent runtime.

## Exit Criteria

- CLI and SDK can resume a prior run by run id using persisted SQLite evidence.
- Completed nodes are skipped only when persisted evidence is compatible with the current workflow provenance and output contract expectations.
- Failed or missing nodes execute again and create auditable resume/rerun evidence in SQLite node events.
- ai-infra report summarizes resume attempts, skipped nodes, and rerun nodes.
- ai-infra verify can validate resume behavior from persisted evidence.
- Tests and CLI examples cover interrupted or failed resume paths.

## Commitment Phase State

### Stable State Now

- Closed plan-007 provides immutable provenance, structured reporting, bounded tool execution, failure policies, and output contract evidence for local DAG workflows.

### Active Change Pressure

- Production DAG workflows need controlled run resumption so failed or interrupted runs do not waste cost or lose audit continuity.

### Target Stable State

- DAG workflow runs can resume from persisted evidence with deterministic skip/rerun semantics and inspectable evidence.

### Conversion Proof

- Failing-first tests, CLI resume example, SQLite-backed resume events, report/verify support, ABH verification, and independent audit prove the resumption boundary.

### Residual Pressure

- API/UI, remote scheduling, MCP integration, LLM-backed ReAct, PlanExec, Super-Agent, and distributed idempotency remain future phases. | Non-blocking rationale:

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/resume_workflow.yaml
- uv run ai-infra run examples/resume_workflow.yaml --input-file examples/resume_input.json
- uv run python scripts/verify_cli_resume.py

## Closure Evidence

- Passing tests covering run resumption, skip/rerun behavior, reporting, verification, and CLI examples.
- Passing CLI validate/run/resume/report/verify evidence for resume workflows.
- Independent audit confirms run resumption aligns with the active attractor and phase boundaries.
- audit-008-run-resumption-idempotency

## Verification Runs

- ver-da24314ae384
- ver-73db0673e075
- ver-d754ee539e27
- ver-5c35c9e7c221
- ver-6194e721e5ec

## Audits

- audit-008-run-resumption-idempotency
