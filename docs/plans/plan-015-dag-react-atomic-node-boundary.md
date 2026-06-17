# Plan: DAG ReAct Atomic Node Boundary

## Metadata

- ID: plan-015-dag-react-atomic-node-boundary
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-014 are closed with a production-oriented local YAML DAG stack: LangGraph-backed execution, bounded python/shell/http tool nodes, structured reports, SQLite evidence, hardened schema validation, immutable provenance, retry/failure policies, output contracts, resumption, local artifact evidence bundles, execution governance, run store maintenance, MCP reserved boundary, workflow validation assertions, and input secret/environment governance. The ReAct layer still exists only as a minimal SDK skeleton; DAG workflows cannot yet declare and execute a bounded ReAct atomic node with OpenAI-compatible LLM configuration, tool-call evidence, step limits, cost/governance metadata, and redaction-safe persisted traces.
- Owner: engineering
- Created: 2026-06-17T01:16:28.097729+00:00
- Updated: 2026-06-17T03:26:02.729736+00:00

## Goals

- Add a minimal executable ReAct atomic node type inside DAG Workflow while keeping DAG as the production-first outer orchestrator.
- Support an OpenAI-compatible LLM client boundary with deterministic mock/offline execution for tests and demos, plus reserved real-provider configuration that does not require network credentials for validation.
- Persist ReAct reasoning/action/observation evidence, tool calls, model configuration summaries, budget/step outcomes, and redaction-safe traces through existing SQLite, report, logs, verification, and evidence bundle surfaces.

## Non-Goals

- No PlanExec runtime, Super-Agent runtime, API, frontend UI, distributed execution, A2A service, or remote scheduler.
- No unbounded autonomous loop, no ReAct node owning multi-step business workflow orchestration, and no bypass of DAG failure/governance/output/secret controls.
- No real MCP runtime and no mandatory live OpenAI/API call in tests or ABH verification; live providers remain optional future integration.
- No general-purpose prompt policy language, hidden chain-of-thought persistence, or unrestricted tool execution beyond explicitly declared DAG node tool boundaries.

## Exit Criteria

- Workflow YAML can declare a react node with deterministic schema validation for provider/model/prompt/tool/step/budget/redaction-safe configuration.
- Local DAG execution can run a bounded ReAct node using a deterministic mock OpenAI-compatible client and existing tool adapters, with persisted step-level action/observation evidence.
- ReAct node execution enforces max steps and governance boundaries, produces actionable failure evidence on limit/tool/model errors, and remains an atomic DAG node rather than an outer orchestrator.
- Reports, logs, verification records, and evidence bundles expose ReAct traces, tool-call summaries, model configuration summaries, redaction summaries, and terminal answer/status without leaking configured sensitive values.
- Python SDK exposes the ReAct node/client boundary needed by CLI callers without bypassing workflow validation or existing DAG controls.
- Existing workflow examples continue to validate, run, report, verify, and preserve plan14 secret redaction behavior without requiring ReAct declarations.

## Commitment Phase State

### Stable State Now

- Closed plan-014 provides a production-oriented DAG evidence stack with secret/environment governance, redaction, validation assertions, MCP reserved boundary, and bounded local execution controls.

### Active Change Pressure

- The active attractor requires ReAct to exist as the smallest intelligent execution unit under DAG Workflow, but the current project only has layer skeletons and cannot demonstrate a controlled ReAct atomic node.

### Target Stable State

- Local DAG workflows can declare, execute, persist, report, verify, and export bounded ReAct atomic-node evidence through deterministic OpenAI-compatible client boundaries while retaining DAG governance.

### Conversion Proof

- Failing-first tests, YAML examples, CLI verification script, SDK/report/log evidence, ABH verification, and independent audit prove the ReAct atomic-node boundary without escalating to PlanExec or Super-Agent.

### Residual Pressure

- Real OpenAI provider calls, richer model adapters, MCP runtime tools, PlanExec long-task orchestration, Super-Agent coordination, API/UI, remote scheduling, and distributed governance remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/react_workflow.yaml
- uv run ai-infra run examples/react_workflow.yaml --input-file examples/react_input.json
- uv run python scripts/verify_cli_react_node.py

## Closure Evidence

- Passing tests covering ReAct schema validation, bounded execution, tool-call evidence, max-step failure, report/log/verify/evidence-bundle surfaces, and redaction interaction.
- Passing CLI validation and demonstration script evidence for deterministic mock ReAct workflows.
- Independent audit confirms ReAct remains an atomic DAG node and aligns with the active attractor and phase boundaries.
- audit-015-dag-react-atomic-node-boundary

## Verification Runs

- ver-5bc145f3e825

## Audits

- audit-015-dag-react-atomic-node-boundary
