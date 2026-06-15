# Plan: Tool System Productionization

## Metadata

- ID: plan-002-tool-system-productionization
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: MVP plan-001 is closed with YAML DAG execution, CLI/SDK, LangGraph runner, SQLite run store, verification, and layer skeletons; runner currently executes template nodes only while workflow config already reserves tool/react/llm/validation node types.
- Owner: engineering
- Created: 2026-06-15T08:42:13.955585+00:00
- Updated: 2026-06-15T09:04:03.331077+00:00

## Goals

- Add production-oriented tool node execution to DAG Workflow while keeping DAG as the outer orchestrator and tools as auditable atomic node capabilities.
- Support minimal Python callable, shell, and HTTP tool adapters behind a bounded tool registry/interface.
- Persist tool invocation evidence, including inputs, outputs, status, duration, exit details, and errors, through the existing SQLite event/log path.

## Non-Goals

- No full MCP client/server integration in this phase.
- No API, frontend UI, distributed A2A, PlanExec runtime, or Super-Agent runtime.
- No unrestricted shell execution beyond explicitly declared workflow tool nodes and test fixtures.

## Exit Criteria

- A user can validate and run a YAML workflow containing tool nodes for Python callable, shell, and HTTP adapters.
- A user can inspect ai-infra logs for tool node invocation evidence, including success and failure details.
- A user can run ai-infra verify <run-id> and validate tool node completion or expected failure through persisted run evidence.
- Python SDK exposes the tool registry/execution boundary needed to run DAG tool nodes without bypassing workflow validation.

## Commitment Phase State

### Stable State Now

- Closed MVP supports YAML DAG template execution, persisted runs/events/verifications, CLI/SDK inspection, and layer skeletons.

### Active Change Pressure

- Production-grade DAG workflows need real tool execution rather than template-only demonstration nodes.

### Target Stable State

- DAG Workflow can execute bounded, auditable tool nodes through explicit adapters while preserving traceability and failure localization.

### Conversion Proof

- Tool workflow examples, SQLite-backed logs, verification checks, tests, and independent audit prove the new tool boundary.

### Residual Pressure

- MCP, stronger schema contracts, richer observability, API/UI, PlanExec, and Super-Agent remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/tool_workflow.yaml
- uv run ai-infra run examples/tool_workflow.yaml --input-file examples/tool_input.json
- uv run ai-infra validate examples/tool_failure_workflow.yaml
- uv run ai-infra run examples/tool_failure_workflow.yaml --input-file examples/tool_input.json

## Closure Evidence

- Passing tests covering tool node success and failure paths.
- Passing CLI validate/run/status/logs/verify evidence for tool workflows.
- Independent audit confirms tool execution remains aligned with active attractor and phase boundaries.
- audit-002-tool-system-productionization

## Verification Runs

- ver-f4e586838a59
- ver-42095a944c05
- ver-2177afc4778c

## Audits

- audit-002-tool-system-productionization
