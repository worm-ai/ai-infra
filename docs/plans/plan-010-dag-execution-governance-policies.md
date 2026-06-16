# Plan: DAG Execution Governance Policies

## Metadata

- ID: plan-010-dag-execution-governance-policies
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-009 are closed with local YAML DAG execution, bounded tool nodes, structured reports, hardened schema validation, immutable provenance, explicit failure policy/retry semantics, output contract evidence, run resumption, and local artifact evidence bundles. The DAG runner still lacks explicit execution governance policies for timeout, budget, and abort evidence, which limits production cost control and operational auditability.
- Owner: engineering
- Created: 2026-06-16T05:23:11.798735+00:00
- Updated: 2026-06-16T06:04:17.547846+00:00

## Goals

- Add explicit local DAG governance policy declarations for workflow and node execution while keeping DAG Workflow as the production-first orchestration layer.
- Enforce deterministic timeout and budget limits during local execution and persist governance evidence in SQLite node event metadata.
- Expose governance outcomes through report and verification checks so operators can audit timeout, budget, and abort behavior from persisted evidence.

## Non-Goals

- No remote scheduler, distributed queue, background worker, API, or frontend UI.
- No MCP runtime, LLM-backed ReAct runtime, PlanExec runtime, or Super-Agent runtime.
- No external cancellation service or wall-clock distributed coordination; first version stays local and deterministic.

## Exit Criteria

- Workflow YAML can declare workflow-level and node-level governance policies with deterministic schema validation and actionable errors.
- Runtime records timeout, budget, skipped, and abort evidence in NodeEvent.metadata governance evidence persisted in SQLite.
- ai-infra report <run-id> summarizes governance outcomes per run and node without requiring raw log inspection.
- ai-infra verify <run-id> can validate declared governance evidence through workflow validations.
- Tests and CLI examples cover governance schema, runtime timeout/budget behavior, reporting, verification, and examples.

## Commitment Phase State

### Stable State Now

- Closed plan-009 provides immutable provenance, structured reporting, bounded tool execution, failure policies, output contracts, run resumption, and local artifact evidence bundles for local DAG workflows.

### Active Change Pressure

- Production DAG workflows need explicit timeout, budget, and abort controls so execution cost and failure boundaries are governed rather than implicit.

### Target Stable State

- DAG workflow runs can declare, enforce, persist, report, and verify local execution governance policies with deterministic evidence.

### Conversion Proof

- Failing-first tests, CLI governance examples, SQLite-backed governance metadata, report/verify support, ABH verification, and independent audit prove the governance boundary.

### Residual Pressure

- Remote scheduling, API/UI, MCP runtime, LLM-backed ReAct, PlanExec, Super-Agent, and distributed cancellation remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/governance_workflow.yaml
- uv run ai-infra run examples/governance_workflow.yaml --input-file examples/governance_input.json
- uv run python scripts/verify_cli_governance.py

## Closure Evidence

- Passing tests covering DAG execution governance policies.
- Passing CLI validate/run/report/verify evidence for governance workflow examples.
- Independent audit confirms governance policies align with the active attractor and phase boundaries.
- audit-010-dag-execution-governance-policies

## Verification Runs

- ver-89216be91fa7
- ver-c9cd93c5bba7
- ver-1bdf8fcc79b6

## Audits

- audit-010-dag-execution-governance-policies
