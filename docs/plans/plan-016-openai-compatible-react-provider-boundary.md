# Plan: OpenAI-Compatible ReAct Provider Boundary

## Metadata

- ID: plan-016-openai-compatible-react-provider-boundary
- Status: ready
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-015 are closed with a production-oriented local YAML DAG stack: LangGraph-backed execution, bounded python/shell/http tool nodes, structured reports, SQLite evidence, hardened schema validation, immutable provenance, retry/failure policies, output contracts, resumption, local artifact evidence bundles, execution governance, run store maintenance, MCP reserved boundary, validation assertions, input secret/environment governance, and a bounded ReAct atomic node. Plan-015 added deterministic mock/offline ReAct execution and reserved OpenAI-compatible configuration, but the real provider boundary remains intentionally non-production: provider credentials, timeout, token/cost budget, request/response summaries, failure evidence, redaction, and report/verify/bundle surfaces are not yet hardened end to end.
- Owner: engineering
- Created: 2026-06-17T09:05:28.961410+00:00
- Updated: 2026-06-17T09:05:28.963119+00:00

## Goals

- Promote the ReAct atomic node from mock/offline-only behavior to an optional OpenAI-compatible provider boundary while keeping DAG Workflow as the production outer orchestrator.
- Add provider configuration, environment-key governance, timeout handling, token/cost budget enforcement, request/response summaries, and structured provider failure evidence for DAG react nodes.
- Carry provider evidence through SQLite events, logs, reports, verification, and evidence bundles with redaction-safe summaries and no secret leakage.

## Non-Goals

- No PlanExec runtime, Super-Agent runtime, API, frontend UI, distributed execution, A2A service, remote scheduler, or outer autonomous planner.
- No mandatory live OpenAI-compatible network call in tests, verification, or ABH closure; tests must use an injectable fake provider/client.
- No real MCP runtime, model marketplace, streaming UI, or provider-specific feature expansion beyond the OpenAI-compatible chat/completion boundary needed by the ReAct node.
- No hidden chain-of-thought persistence, unbounded ReAct loop, or ReAct node ownership of multi-step business workflow orchestration.

## Exit Criteria

- Workflow YAML validates openai-compatible react provider config deterministically, including base_url, api_key_env, model, timeout, token budget, cost budget, and redaction-sensitive fields.
- Missing provider API key fails fast with governance evidence and redaction-safe messages, without logging key values or prompting for credentials interactively.
- A fake OpenAI-compatible provider workflow completes locally and persists request summary, response summary, model identity, token usage, estimated cost, timeout/budget metadata, and terminal ReAct result evidence.
- Timeout, provider error, token-budget exhaustion, and cost-budget exhaustion produce actionable failure evidence in node events, logs, reports, verification records, and bundles.
- Report, logs, verify, and evidence bundle surfaces expose provider evidence and redaction summaries without leaking prompts, secrets, or configured sensitive values.
- Existing mock ReAct workflows and non-ReAct DAG workflows continue to validate, run, report, verify, and preserve plan-014 redaction behavior.

## Commitment Phase State

### Stable State Now

- Closed plan-015 provides a bounded ReAct atomic node inside DAG Workflow with deterministic mock/offline execution, tool-call evidence, step limits, reports, verification, bundles, and redaction interaction.

### Active Change Pressure

- The active attractor requires ReAct to be a real atomic execution unit under DAG Workflow, but production use needs an optional OpenAI-compatible provider boundary with governed credentials, budget controls, timeout behavior, and auditable evidence.

### Target Stable State

- DAG react nodes can optionally call an OpenAI-compatible provider through a bounded, redaction-safe, budgeted, timeout-aware boundary while preserving DAG governance and auditability.

### Conversion Proof

- Fake-provider workflows, missing-key failures, budget-exhaustion tests, redaction bundle checks, full pytest, ABH verification, and independent audit prove the provider boundary without live network dependency.

### Residual Pressure

- Live provider smoke tests, richer model adapters, streaming, MCP runtime tools, PlanExec, Super-Agent, API/UI, remote scheduling, and distributed governance remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/react_openai_compatible_workflow.yaml
- uv run ai-infra run examples/react_openai_compatible_workflow.yaml --input-file examples/react_openai_compatible_input.json
- uv run python scripts/verify_cli_react_openai_provider.py

## Closure Evidence

- Passing tests covering provider schema, fake provider execution, missing key governance, timeout/provider error handling, token/cost budget exhaustion, redaction, report, verify, and evidence bundle behavior.
- Passing CLI validation and demonstration script evidence for fake OpenAI-compatible ReAct provider workflows and failure cases.
- ABH verification confirms plan-016 exit criteria against the active attractor.
- Independent audit confirms the provider boundary remains a DAG react-node atomic capability and does not escalate to PlanExec, Super-Agent, API/UI, or distributed execution.
- audit-016-openai-compatible-react-provider-boundary

## Verification Runs

- 

## Audits

- 
