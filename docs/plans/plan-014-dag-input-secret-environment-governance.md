# Plan: DAG Input Secret and Environment Governance

## Metadata

- ID: plan-014-dag-input-secret-environment-governance
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-013 are closed with local YAML DAG execution, bounded tool nodes, structured reports, hardened schema validation, immutable provenance, retry/failure policies, output contracts, resumption, local artifact evidence, execution governance, run store maintenance, MCP reserved boundary, and workflow validation assertions. The current production DAG stack still lacks explicit governance for required environment variables, sensitive input fields, and redaction of secret-bearing evidence, so local runs can be difficult to audit safely when workflows depend on credentials or sensitive payloads.
- Owner: engineering
- Created: 2026-06-16T09:22:47.748146+00:00
- Updated: 2026-06-16T11:35:56.047333+00:00

## Goals

- Add declarative DAG governance for required environment variables, sensitive input paths, and bounded redaction rules while keeping DAG Workflow as the production-first orchestration layer.
- Enforce environment and sensitive-evidence governance during local DAG execution and persist audit evidence without storing secret values.
- Expose redaction and environment-governance outcomes through CLI, SDK reports, logs, verification, and evidence bundle surfaces so operators can audit secret handling from persisted evidence.

## Non-Goals

- No external secret manager, KMS, Vault, credential rotation, or remote policy service integration.
- No ReAct runtime, PlanExec runtime, Super-Agent runtime, API, frontend UI, real MCP runtime, remote scheduler, or distributed execution.
- No general-purpose policy language, arbitrary expression evaluator, unbounded regex engine, or dynamic data exfiltration scanner in YAML.
- No retroactive migration or rewriting of old stored run evidence from earlier plans.

## Exit Criteria

- Workflow YAML can declare required environment variables and sensitive evidence paths with deterministic schema validation and actionable errors.
- Local DAG execution fails fast with persisted governance evidence when required environment variables are missing, without logging environment variable values.
- Run inputs, node outputs, node metadata, tool invocation evidence, reports, logs, verification records, and exported evidence bundles redact configured sensitive values with a stable marker and include redaction summary evidence.
- ai-infra verify can validate redaction and environment-governance evidence through workflow-declared validations and bounded assertions.
- Python SDK exposes the governance/redaction boundary needed by CLI callers without bypassing workflow validation.
- Existing workflow examples continue to validate, run, report, and verify without requiring governance declarations.

## Commitment Phase State

### Stable State Now

- Closed plan-013 provides a production-oriented local DAG evidence stack with normalized tool invocation evidence, MCP reserved boundary, and bounded validation assertions over persisted run evidence.

### Active Change Pressure

- Production DAG workflows need explicit handling for required environment dependencies and secret-bearing inputs so audit trails remain useful without leaking sensitive values.

### Target Stable State

- Local DAG workflow runs can declare, enforce, persist, report, verify, and export environment and sensitive-evidence governance with deterministic redaction evidence.

### Conversion Proof

- Failing-first tests, YAML examples, CLI verification script, SDK/report/log evidence, ABH verification, and independent audit prove the governance boundary.

### Residual Pressure

- External secret managers, richer policy engines, real MCP runtime, OpenAI-compatible ReAct execution, PlanExec, Super-Agent, API/UI, remote scheduling, and distributed governance remain future phases. | Non-blocking rationale:

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/redaction_workflow.yaml
- uv run ai-infra validate examples/missing_env_workflow.yaml
- uv run python scripts/verify_cli_redaction_governance.py

## Closure Evidence

- Passing tests covering schema validation, missing environment handling, redaction persistence, reports, logs, verification, and evidence bundle export.
- Passing CLI validation and demonstration script evidence for redaction success and missing-env failure workflows.
- Independent audit confirms input/secret/environment governance aligns with the active attractor and phase boundaries.
- audit-014-dag-input-secret-environment-governance

## Verification Runs

- ver-a8e5b5a8cfe9
- ver-874bb5814825
- ver-76e0a42d73ad
- ver-e7176eb8dcb5
- ver-11591d12bdcf
- ver-dfcf9ec7b292
- ver-5ad8595d2440
- ver-3ec366fd9082
- ver-44839119c22b
- ver-e5260ab6cbbc

## Audits

- audit-014-dag-input-secret-environment-governance
