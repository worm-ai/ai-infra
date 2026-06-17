# Plan: DAG Production Packaging and Demo Contract

## Metadata

- ID: plan-018-dag-production-packaging-demo-contract
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-017 are closed with a production-oriented local YAML DAG stack: LangGraph-backed execution, bounded python/shell/http tool nodes, structured reports, SQLite evidence, hardened schema validation, immutable provenance, retry/failure policies, output contracts, resumption, local artifact evidence bundles, execution governance, run store maintenance, validation assertions, input secret/environment governance, a bounded ReAct atomic node, an OpenAI-compatible ReAct provider boundary, and a minimal deterministic local/fake MCP runtime boundary. The executable kernel is increasingly capable, but the repository still presents as an ABH workspace with a placeholder README and lacks a consolidated production packaging/demo contract that proves a new operator can evaluate the DAG Workflow product boundary end to end.
- Owner: engineering
- Created: 2026-06-17T11:48:44.253072+00:00
- Updated: 2026-06-17T12:30:25.895097+00:00

## Goals

- Turn the current local CLI + SDK DAG kernel into a coherent production-facing delivery surface with README quickstart, demo contract, SDK usage, command matrix, and troubleshooting guidance.
- Create or harden an end-to-end demo verification path that exercises validate/run/status/logs/report/verify/export-bundle across representative DAG, ReAct, OpenAI-compatible fake provider, MCP runtime, failure, governance, and redaction surfaces.
- Document the production boundaries, non-goals, evidence model, and ABH closure model so demos and downstream work stay aligned with the active attractor.
- Keep all packaging/demo artifacts executable and drift-resistant through tests or CLI verification scripts.

## Non-Goals

- No API, frontend UI, hosted service, remote scheduler, distributed execution, A2A, PlanExec runtime, or Super-Agent runtime.
- No live external provider or live remote MCP dependency in mandatory verification; provider and MCP demos must remain local/fake or env-gated outside the required checklist.
- No broad refactor of the runner, store, tool system, ReAct provider, or MCP runtime beyond narrow fixes required to make the documented demo contract true.
- No change to DAG orchestration semantics, evidence schema contracts, or existing examples unless needed for documentation correctness or executable verification.

## Exit Criteria

- README explains what ai-infra is, its active attractor-aligned architecture, install/dev prerequisites, quickstart, CLI command flow, SDK usage, evidence bundle workflow, and current non-goals without presenting the project as a toy demo.
- A production demo script or equivalent verifier runs locally from a clean temp state and proves validate/run/status/logs/report/verify/export-bundle behavior for core DAG success plus representative failure/governance/redaction/ReAct/provider/MCP surfaces.
- Docs identify the current production boundary: DAG Workflow as the mainline, ReAct as an atomic node, MCP as tool/data-source reuse boundary, and PlanExec/Super-Agent/A2A/API/UI as future phases.
- Demo/quickstart commands are copy-pasteable, deterministic, redaction-safe, and do not require external credentials.
- Existing plan-001 through plan-017 examples and verifier scripts remain compatible, or any intentional doc/command changes are covered by tests.
- New documentation and verification artifacts are reviewed by independent audit for attractor alignment and executable truthfulness.

## Commitment Phase State

### Stable State Now

- Closed plan-017 provides an auditable local DAG kernel with ReAct provider and MCP runtime boundaries, but the top-level repository documentation and demo contract do not yet communicate or prove production usability.

### Active Change Pressure

- The project is approaching a production-grade local orchestration kernel; without an executable packaging/demo contract, future work may drift into new features before the current DAG production boundary is demonstrably deliverable.

### Target Stable State

- A new operator can understand, install, run, verify, inspect, and audit the local DAG Workflow product boundary from the README and demo verifier without relying on hidden context or live external services.

### Conversion Proof

- README/doc updates, demo verifier, focused tests, full pytest, CLI demo verification, ABH verification, independent audit, close, commit, and push prove the packaging contract.

### Residual Pressure

- Package publishing, semantic versioning release automation, API/UI, live provider smoke tests, remote MCP transports, PlanExec, Super-Agent, A2A, and distributed governance remain future phases outside plan-018 scope. | Non-blocking rationale:

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run python scripts/verify_cli_production_demo.py
- uv run python scripts/verify_cli_react_openai_provider.py
- uv run python scripts/verify_cli_mcp_runtime.py
- uv run python scripts/verify_cli_redaction_governance.py

## Closure Evidence

- Passing tests covering README/demo contract checks and unchanged CLI/SDK behavior.
- Passing production demo verifier covering quickstart, report, verify, logs, and evidence bundle behavior across representative examples.
- ABH verification confirms plan-018 exit criteria against the active industrial agent orchestration attractor.
- Independent audit confirms packaging/demo materials are executable, redaction-safe, and do not introduce API/UI, PlanExec, Super-Agent, A2A, distributed execution, or live external dependencies.
- audit-018-dag-production-packaging-demo-contract

## Verification Runs

- ver-c76fea1e6165
- ver-1a02f36e0749
- ver-1812c313eefb

## Audits

- audit-018-dag-production-packaging-demo-contract
