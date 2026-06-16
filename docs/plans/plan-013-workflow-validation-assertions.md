# Plan: Workflow Validation Assertions

## Metadata

- ID: plan-013-workflow-validation-assertions
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-012 are closed with local YAML DAG execution, bounded tool nodes, structured reports, hardened schema validation, immutable provenance, retry/failure policies, output contracts, resumption, local artifact evidence, governance, maintenance, and a reserved MCP tool boundary. Verification currently supports named checks for run status and specific evidence families, but it lacks a compact field-level assertion DSL for persisted run evidence, so operators cannot declaratively verify arbitrary node output, metadata, tool invocation, or report summary fields without adding new validation types for each case.
- Owner: engineering
- Created: 2026-06-16T08:04:20.803088+00:00
- Updated: 2026-06-16T08:58:01.680246+00:00

## Goals

- Add a deterministic workflow validation assertion DSL for persisted DAG run evidence while keeping DAG Workflow as the production-first orchestration layer.
- Support field-level assertions for run, node output, node metadata, tool invocation, and report evidence using bounded operators and explicit paths.
- Expose assertion results through existing CLI/SDK verification records so audit checks remain traceable and failure-localized.

## Non-Goals

- No ReAct runtime, PlanExec runtime, Super-Agent runtime, API, frontend UI, real MCP runtime, remote scheduler, or distributed execution.
- No general-purpose expression language, arbitrary code execution, regex engine, or unbounded query language in YAML validations.
- No change to DAG execution semantics, run storage schema, or existing validation behavior except adding assertion validation support.

## Exit Criteria

- Workflow YAML can declare field-level validation assertions with deterministic schema validation and actionable errors.
- ai-infra verify evaluates assertions from persisted run evidence, including node output fields and tool_invocation fields, and records pass/fail VerificationCheck messages.
- CLI examples demonstrate assertion success and assertion failure without requiring raw log inspection.
- Python SDK validate_stored_run and validate_run support the same assertion DSL without CLI-specific parsing.
- Existing validation types and existing examples continue to validate, run, report, and verify.
- Tests and a CLI verification script cover schema validation, assertion pass/fail behavior, nested paths, tool invocation evidence, and error messages.

## Commitment Phase State

### Stable State Now

- Closed plan-012 provides a production-oriented local DAG evidence stack with normalized tool invocation evidence and explicit MCP reserved boundary.

### Active Change Pressure

- Production operators need richer declarative verification over persisted evidence without adding bespoke validation types for every audit question.

### Target Stable State

- DAG workflow verification can assert bounded field-level evidence paths with deterministic pass/fail records and clear failure localization.

### Conversion Proof

- Failing-first tests, YAML examples, CLI verification script, ABH verification, and independent audit prove the assertion boundary.

### Residual Pressure

- ReAct runtime, PlanExec, Super-Agent, real MCP runtime, richer policy engines, API/UI, and distributed verification remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/validation_assertion_workflow.yaml
- uv run ai-infra run examples/validation_assertion_workflow.yaml --input-file examples/validation_assertion_input.json
- uv run ai-infra validate examples/validation_assertion_failure_workflow.yaml
- uv run ai-infra run examples/validation_assertion_failure_workflow.yaml --input-file examples/validation_assertion_input.json
- uv run python scripts/verify_cli_validation_assertions.py

## Closure Evidence

- Passing tests covering workflow validation assertions.
- Passing CLI validate/run/verify evidence for assertion success and failure examples.
- Independent audit confirms assertion DSL aligns with the active attractor and phase boundaries.
- audit-013-workflow-validation-assertions

## Verification Runs

- ver-1dde5df0cedb
- ver-a98f6439ac72
- ver-85deb8d30de9

## Audits

- audit-013-workflow-validation-assertions
