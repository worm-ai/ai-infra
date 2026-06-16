# Plan: MCP Tool Boundary Preparation

## Metadata

- ID: plan-012-mcp-tool-boundary-preparation
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-011 are closed with local YAML DAG execution, bounded python/shell/http tool nodes, structured reports, hardened schema validation, immutable provenance, retry/failure policy, output contracts, run resumption, local artifact evidence bundles, execution governance policies, and run store maintenance. The current tool system executes adapters directly but lacks a stable SDK-level invocation contract and an explicit MCP reserved boundary, so future MCP integration pressure could blur adapter responsibilities or weaken audit evidence.
- Owner: engineering
- Created: 2026-06-16T07:13:37.602755+00:00
- Updated: 2026-06-16T07:42:34.335511+00:00

## Goals

- Add a stable SDK-level tool invocation and adapter boundary for DAG tool nodes without changing DAG orchestration semantics.
- Normalize python, shell, and http tool execution evidence into a consistent invocation evidence surface while preserving existing behavior.
- Add an MCP reserved adapter/config boundary that validates declaratively and fails audibly/auditably when executed, without implementing an MCP runtime.

## Non-Goals

- No real MCP client, server, transport, discovery, or runtime execution.
- No LLM-backed ReAct runtime, PlanExec runtime, Super-Agent runtime, API, frontend UI, distributed scheduler, or remote execution.
- No change to DAG outer orchestration semantics or existing python/shell/http adapter behavior beyond normalized evidence.

## Exit Criteria

- YAML tool config for python, shell, http, and reserved mcp adapters can be normalized into a common invocation contract/evidence surface.
- Existing python/shell/http workflows continue to validate, run, report, verify, and expose compatible adapter-specific evidence.
- MCP adapter config validates at the schema boundary and execution produces deterministic reserved/not-implemented evidence instead of silent failure.
- CLI logs/report expose consistent tool invocation identity, adapter, input, output, duration, status, and error evidence.
- Python SDK exports stable boundary types/helpers for tool invocation contracts and execution evidence.
- Tests and a CLI verification script cover old behavior compatibility and MCP reserved behavior.

## Commitment Phase State

### Stable State Now

- Closed plan-011 provides operable local DAG evidence with bounded python/shell/http tools, reports, provenance, policies, artifacts, resumption, governance, and maintenance tooling.

### Active Change Pressure

- Future MCP tool/data-source reuse needs a clear adapter boundary before runtime integration is introduced.

### Target Stable State

- DAG tool nodes execute through a stable invocation contract, with existing adapters normalized and MCP explicitly reserved as a non-runtime boundary.

### Conversion Proof

- Failing-first tests, normalized invocation evidence, MCP reserved examples, CLI verification, ABH verification, and independent audit prove the boundary.

### Residual Pressure

- Real MCP runtime, richer tool discovery, OpenAI-compatible LLM/ReAct execution, PlanExec, Super-Agent, API/UI, and distributed execution remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/tool_workflow.yaml
- uv run ai-infra run examples/tool_workflow.yaml --input-file examples/tool_input.json
- uv run ai-infra validate examples/mcp_reserved_workflow.yaml
- uv run ai-infra run examples/mcp_reserved_workflow.yaml --input-file examples/mcp_reserved_input.json
- uv run python scripts/verify_cli_tool_boundary.py

## Closure Evidence

- Passing tests covering unified tool invocation evidence and MCP reserved behavior.
- Passing CLI validate/run/report/verify evidence for python/shell/http and MCP reserved workflows.
- Independent audit confirms MCP boundary preparation aligns with the active attractor and phase boundaries.
- audit-012-mcp-tool-boundary-preparation

## Verification Runs

- ver-f17a973d9c07
- ver-f9df49ccf93f

## Audits

- audit-012-mcp-tool-boundary-preparation
