# Plan: Workflow Schema Contract and Validation Hardening

## Metadata

- ID: plan-004-workflow-schema-contract-validation
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-003 are closed with YAML DAG execution, CLI/SDK, LangGraph runner, SQLite run store, tool node execution, structured run reports, and ABH verification/audit records. Workflow config validation exists, but the YAML contract is still loose around top-level shape, unknown fields, node/edge data types, adapter-specific tool config, validation config, and actionable error messages.
- Owner: engineering
- Created: 2026-06-15T11:16:50.437569+00:00
- Updated: 2026-06-15T11:32:14.562309+00:00

## Goals

- Harden YAML Workflow schema validation into an explicit production-grade DAG configuration contract.
- Improve CLI/SDK validation error clarity for invalid workflows without changing runtime execution semantics.
- Add focused invalid-workflow coverage so schema regressions are caught before runner execution.

## Non-Goals

- No web API or frontend UI.
- No MCP implementation beyond preserving future interface boundaries.
- No LLM/ReAct runtime, PlanExec runtime, or Super-Agent runtime.
- No retry/failure policy runtime implementation in this phase.
- No output/artifact contract implementation beyond validating workflow input schema.

## Exit Criteria

- Existing valid examples continue to validate and run.
- Invalid YAML workflow cases fail deterministically with actionable WorkflowValidationError messages.
- Tool adapter configs validate adapter-specific required fields for python, shell, and http nodes.
- Edge and validation config shapes are validated before execution.
- Tests cover valid and invalid schema cases, including CLI validation failure output.

## Commitment Phase State

### Stable State Now

- Closed plan-003 provides auditable DAG workflow runs, structured reports, bounded tool nodes, and persisted run evidence.

### Active Change Pressure

- Production-grade workflow execution needs stricter declarative config contracts so bad YAML fails before runner execution.

### Target Stable State

- DAG workflow YAML has a deterministic validation boundary with actionable errors for operators and SDK callers.

### Conversion Proof

- Failing-first tests, updated validation logic, CLI evidence, ABH verification, and independent audit prove the schema contract.

### Residual Pressure

- MCP, API/UI, LLM-backed ReAct, PlanExec, Super-Agent, retry policies, and artifact contracts remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/hello_workflow.yaml
- uv run ai-infra validate examples/tool_workflow.yaml
- uv run ai-infra validate examples/tool_failure_workflow.yaml

## Closure Evidence

- Passing tests covering schema contract success and failure paths.
- Passing CLI validation evidence for existing valid workflows.
- Independent audit confirms schema hardening aligns with the active attractor and plan boundaries.
- audit-004-workflow-schema-contract-validation

## Verification Runs

- ver-d99e78b05ac2

## Audits

- audit-004-workflow-schema-contract-validation
