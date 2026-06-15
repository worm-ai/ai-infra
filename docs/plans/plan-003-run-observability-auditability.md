# Plan: Run Observability and Auditability

## Metadata

- ID: plan-003-run-observability-auditability
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001 and 002 are closed with YAML DAG execution, CLI/SDK, LangGraph runner, SQLite run store, tool node execution, raw event logs, and verification. The current CLI can show raw logs but lacks a structured run report that summarizes status, timeline, node evidence, failure reasons, and tool execution details for production auditability.
- Owner: engineering
- Created: 2026-06-15T09:17:39.500136+00:00
- Updated: 2026-06-15T09:37:33.976018+00:00

## Goals

- Add structured run reports for local DAG executions without changing the production-first DAG boundary.
- Expose report generation through both CLI and SDK so operators can inspect successful and failed workflow runs from persisted SQLite evidence.
- Improve traceability, failure localization, and auditability for tool-backed DAG workflows while keeping ReAct/PlanExec/Super-Agent as lower-priority skeleton boundaries.

## Non-Goals

- No web API or frontend UI.
- No MCP implementation in this phase.
- No LLM/ReAct runtime, PlanExec runtime, or Super-Agent runtime.
- No database migration unless existing persisted run and event evidence is insufficient.

## Exit Criteria

- A user can run ai-infra report <run-id> and receive a structured JSON report for successful and failed tool workflows.
- Reports include run id, workflow id, run status, inputs and outputs summary, ordered node timeline, node status, duration when available, failure reason, and tool adapter/exit code/error/stdout/stderr summary when available.
- Python SDK exposes report generation without requiring CLI parsing.
- Tests cover successful report generation, failed report generation, CLI report output, and SDK export.

## Commitment Phase State

### Stable State Now

- Closed plan-002 supports bounded, auditable tool execution inside DAG workflow nodes and persists raw node events in SQLite.

### Active Change Pressure

- Production-grade operators need concise run reports rather than only raw event dumps.

### Target Stable State

- DAG workflow runs have a structured report surface that improves traceability, failure localization, and audit review using existing persisted evidence.

### Conversion Proof

- Tests, CLI report output, SDK report API, ABH verification, and independent audit prove the reporting boundary.

### Residual Pressure

- API/UI, MCP integration, richer metrics, LLM-backed ReAct runtime, PlanExec, and Super-Agent remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/tool_workflow.yaml
- uv run ai-infra run examples/tool_workflow.yaml --input-file examples/tool_input.json
- uv run ai-infra validate examples/tool_failure_workflow.yaml
- uv run ai-infra run examples/tool_failure_workflow.yaml --input-file examples/tool_input.json

## Closure Evidence

- Passing tests covering structured run reports for success and failure paths.
- Passing CLI validate/run/report evidence for tool workflows.
- Independent audit confirms run reporting aligns with active attractor and phase boundaries.
- audit-003-run-observability-auditability

## Verification Runs

- ver-6c7e407476a6
- ver-a4d964f02864
- ver-fa965fb07b9a

## Audits

- audit-003-run-observability-auditability
