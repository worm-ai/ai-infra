# Plan: MCP Tool Runtime Boundary Minimal

## Metadata

- ID: plan-017-mcp-tool-runtime-boundary-minimal
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-016 are closed with a production-oriented local YAML DAG stack: LangGraph-backed execution, bounded python/shell/http tool nodes, structured reports, SQLite evidence, hardened schema validation, immutable provenance, retry/failure policies, output contracts, resumption, local artifact evidence bundles, execution governance, run store maintenance, validation assertions, input secret/environment governance, a bounded ReAct atomic node, and an OpenAI-compatible ReAct provider boundary. Plan-012 added an MCP reserved adapter/config boundary that validates and fails audibly when executed, but MCP tool/data-source reuse is still non-runnable, so the next pressure is a minimal deterministic MCP runtime boundary that stays inside DAG tool and ReAct tool execution.
- Owner: engineering
- Created: 2026-06-17T11:01:48.748851+00:00
- Updated: 2026-06-17T11:41:51.083070+00:00

## Goals

- Promote the MCP adapter from reserved non-runtime behavior to a minimal deterministic local/fake runtime boundary for DAG tool nodes and ReAct-declared tools.
- Add YAML configuration for MCP server/tool invocation with timeout, request summary, response summary, tool error evidence, and redaction-safe reporting.
- Carry MCP invocation evidence through SQLite events, CLI run output, reports, verification, and evidence bundles without leaking configured sensitive values.
- Preserve existing python/shell/http tool behavior and keep MCP integration bounded to tool/data-source reuse under DAG Workflow.

## Non-Goals

- No A2A, distributed agent communication, Super-Agent runtime, PlanExec runtime, API, frontend UI, remote scheduler, or general MCP service discovery.
- No dependency on live external MCP services in tests, ABH verification, or closure; tests must use deterministic local/fake MCP runtime behavior.
- No change to DAG outer orchestration semantics and no expansion of ReAct beyond an atomic DAG node that may call declared tools.
- No credential prompts, secret persistence, streaming transport, marketplace, or broad provider abstraction beyond the minimal MCP tool invocation boundary.

## Exit Criteria

- Workflow YAML validates minimal MCP runtime config deterministically, including server identity, tool name, args mapping, timeout, and optional redaction-sensitive fields.
- A fake/local MCP workflow completes locally and persists adapter identity, server/tool identity, request summary, response summary, duration/status, timeout metadata, and result evidence.
- Missing MCP config, timeout, runtime/tool error, and malformed response cases fail with actionable evidence in node events, CLI output, reports, verification, and bundles.
- MCP evidence is redaction-safe across report, verify, and export-bundle surfaces, including configured sensitive values embedded in args or error strings.
- Existing reserved MCP compatibility is either preserved through explicit reserved mode or intentionally migrated with tests and documented behavior.
- Existing python/shell/http and ReAct mock/openai-compatible workflows continue to validate, run, report, verify, and pass tests.

## Commitment Phase State

### Stable State Now

- Closed plan-016 provides a production-oriented DAG evidence stack and bounded ReAct provider boundary; MCP exists as a validated but non-runnable reserved tool boundary from plan-012.

### Active Change Pressure

- The active attractor assigns MCP the role of tool/data-source reuse, and the reserved boundary now needs a minimal executable proof without promoting the architecture to PlanExec, Super-Agent, API/UI, or distributed runtime.

### Target Stable State

- DAG tool nodes and ReAct-declared tools can invoke deterministic local/fake MCP tools through a bounded, timeout-aware, redaction-safe, auditable invocation boundary while DAG Workflow remains the production orchestrator.

### Conversion Proof

- Fake MCP workflow validate/run/report/verify/export-bundle, missing-config failure, timeout/tool-error failure, redaction bundle check, full pytest, ABH verification, independent read-only audit, close, commit, and push prove the boundary.

### Residual Pressure

- Live MCP transports, tool discovery/listing, remote MCP servers, MCP credential managers, A2A, PlanExec, Super-Agent, API/UI, and distributed governance remain future phases outside plan-017 scope. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/mcp_runtime_workflow.yaml
- uv run ai-infra run examples/mcp_runtime_workflow.yaml --input-file examples/mcp_runtime_input.json
- uv run python scripts/verify_cli_mcp_runtime.py
- uv run python scripts/verify_cli_react_node.py

## Closure Evidence

- Passing tests covering MCP runtime schema, deterministic fake/local execution, timeout/tool-error handling, missing config, malformed response, redaction, report, verify, and evidence bundle behavior.
- Passing CLI validation and demonstration script evidence for fake/local MCP runtime workflows and failure cases.
- ABH verification confirms plan-017 exit criteria against the active industrial agent orchestration attractor.
- Independent audit confirms MCP remains a DAG/ReAct tool boundary and does not introduce A2A, PlanExec, Super-Agent, API/UI, or distributed execution.
- audit-017-mcp-tool-runtime-boundary-minimal

## Verification Runs

- ver-5e08b69e37f4
- ver-23a5a4b239b4
- ver-71441ab2af48

## Audits

- audit-017-mcp-tool-runtime-boundary-minimal
