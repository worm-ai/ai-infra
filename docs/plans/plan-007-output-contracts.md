# Plan: DAG Output Contract and Artifact Evidence

## Metadata

- ID: plan-007-output-contracts
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-006 are closed with local YAML DAG execution, bounded tool nodes, structured reports, hardened workflow schema validation, immutable run provenance, and explicit failure policy/retry semantics. Nodes can complete with arbitrary outputs, but downstream nodes and audit verification cannot yet rely on a declared output shape or persisted contract evidence.
- Owner: engineering
- Created: 2026-06-16T01:47:42.269314+00:00
- Updated: 2026-06-16T02:56:58.515877+00:00

## Goals

- Add YAML-declared node output contracts for local DAG nodes while keeping DAG Workflow as the production-first orchestration layer.
- Validate node outputs at runtime and persist deterministic contract evidence in SQLite node events.
- Expose output contract pass/fail status through reports and verification checks so operators can audit downstream trust boundaries from persisted evidence.

## Non-Goals

- No web API or frontend UI.
- No MCP implementation beyond preserving future interface boundaries.
- No LLM-backed ReAct runtime, PlanExec runtime, or Super-Agent runtime.
- No remote artifact store, distributed artifact service, scheduler, or background worker.
- No full JSON Schema engine; keep the first contract format minimal and deterministic.

## Exit Criteria

- Workflow YAML can declare node output contracts with deterministic schema validation and actionable errors.
- Runtime validates node outputs, records contract evidence in SQLite node events, and treats contract failures as node failures under existing DAG failure policy semantics.
- ai-infra report <run-id> summarizes output contract status and reasons per node.
- ai-infra verify <run-id> can validate persisted output contract evidence through workflow-declared validations.
- Tests and CLI examples cover output contract pass and fail behavior.

## Commitment Phase State

### Stable State Now

- Closed plan-006 provides immutable run provenance, structured reporting, bounded tool execution, schema validation, and explicit DAG failure policy/retry semantics.

### Active Change Pressure

- Production DAG workflows need declared output contracts so downstream nodes and audits can trust output shape without reading mutable runtime context.

### Target Stable State

- DAG workflow nodes can declare minimal output contracts that produce persisted pass/fail evidence, report summaries, and verification checks.

### Conversion Proof

- Failing-first tests, CLI output contract examples, SQLite-backed node event evidence, report/verify support, ABH verification, and independent audit prove the artifact contract boundary.

### Residual Pressure

- Richer artifact stores, run resumption, API/UI, MCP integration, LLM-backed ReAct, PlanExec, and Super-Agent remain future phases. | Non-blocking rationale:

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/output_contract_workflow.yaml
- uv run ai-infra run examples/output_contract_workflow.yaml --input-file examples/output_contract_input.json
- uv run ai-infra validate examples/output_contract_failure_workflow.yaml
- uv run ai-infra run examples/output_contract_failure_workflow.yaml --input-file examples/output_contract_input.json
- uv run python scripts/verify_cli_output_contract.py

## Closure Evidence

- Passing tests covering output contract schema, runtime evidence, reporting, verification, and CLI examples.
- Passing CLI validate/run/report/verify evidence for output contract success and failure workflows.
- Independent audit confirms output contracts align with the active attractor and phase boundaries.
- audit-007-output-contracts

## Verification Runs

- ver-e742c8ccb854
- ver-14979069e971
- ver-889c6f31f526
- ver-8dfe868a915d

## Audits

- audit-007-output-contracts
