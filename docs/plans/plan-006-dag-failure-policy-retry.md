# Plan: DAG Failure Policy and Retry Semantics

## Metadata

- ID: plan-006-dag-failure-policy-retry
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-005 are closed with local YAML DAG execution, bounded tool nodes, structured reports, hardened workflow schema validation, and immutable run provenance. The runner can mark failed nodes, but production failure policy remains implicit: workflows do not yet declare halt/continue behavior, retry attempts, retry exhaustion evidence, or verification/report semantics for failure handling.
- Owner: engineering
- Created: 2026-06-16T01:04:43.629591+00:00
- Updated: 2026-06-16T01:29:12.252847+00:00

## Goals

- Add explicit DAG failure policy semantics for node execution while keeping DAG Workflow as the production-first outer orchestrator.
- Support bounded retry for executable DAG nodes and persist attempt-level evidence for success, retry, and retry-exhausted outcomes.
- Expose halt/continue/retry behavior through CLI reports, SDK reports, and verification checks so operators can localize failures without trusting mutable runtime context.

## Non-Goals

- No web API or frontend UI.
- No MCP implementation beyond preserving future interface boundaries.
- No LLM-backed ReAct runtime, PlanExec runtime, or Super-Agent runtime.
- No distributed scheduler, remote queue, background worker, or external artifact store.

## Exit Criteria

- Workflow YAML can declare node-level failure policy for halt, continue, and bounded retry, with deterministic schema validation and actionable errors.
- DAG execution records attempt-level evidence for failed attempts, retry success, retry exhaustion, and continue-after-failure behavior in SQLite node events.
- ai-infra report <run-id> summarizes retry attempts, failed nodes, and failure policy outcomes for both successful retry and retry-exhausted runs.
- ai-infra verify <run-id> can validate persisted retry/failure evidence through workflow-declared validations.
- Tests cover schema validation, runtime halt/continue/retry behavior, report output, verify checks, and CLI examples.

## Commitment Phase State

### Stable State Now

- Closed plan-005 provides immutable run provenance, structured reporting, bounded tool execution, schema validation, and SQLite-backed evidence.

### Active Change Pressure

- Production DAG workflows need explicit failure policy and bounded retry semantics so node failures are controlled, auditable, and localizable.

### Target Stable State

- DAG workflow runs have deterministic halt/continue/retry semantics with persisted attempt evidence, report summaries, and verification checks.

### Conversion Proof

- Failing-first tests, CLI retry examples, SQLite-backed retry events, report/verify evidence, ABH verification, and independent audit prove the failure policy boundary.

### Residual Pressure

- Artifact contracts, run resumption, API/UI, MCP integration, LLM-backed ReAct, PlanExec, and Super-Agent remain future phases. | Non-blocking rationale:

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/retry_workflow.yaml
- uv run ai-infra run examples/retry_workflow.yaml --input-file examples/retry_input.json
- uv run ai-infra validate examples/retry_exhausted_workflow.yaml
- uv run ai-infra run examples/retry_exhausted_workflow.yaml --input-file examples/retry_input.json
- uv run python scripts/verify_cli_retry_policy.py

## Closure Evidence

- Passing tests covering DAG failure policy and retry semantics.
- Passing CLI validate/run/report/verify evidence for retry success and retry exhaustion workflows.
- Independent audit confirms failure policy hardening aligns with the active attractor and phase boundaries.
- audit-006-dag-failure-policy-retry

## Verification Runs

- ver-56e65cc83bb7

## Audits

- audit-006-dag-failure-policy-retry
