# Plan: DAG Workflow Schema and Runtime Compatibility Contract

## Metadata

- ID: plan-024-dag-workflow-compatibility-contract
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-023 are closed with a local-first production DAG Workflow kernel, bounded ReAct atomic node support, OpenAI-compatible and MCP-reserved tool/provider boundaries, SQLite evidence, reports, offline evidence bundles, release installability/trust, and run store reliability. The remaining production-delivery gap is that workflow declarations and runtime behavior do not yet expose an explicit compatibility contract for schema versioning, feature support, migration diagnostics, and compatibility evidence across validate/run/report/verify/bundle/release flows.
- Owner: engineering
- Created: 2026-06-17T19:29:50.533133+00:00
- Updated: 2026-06-17T20:36:10.517395+00:00

## Goals

- Define a local DAG Workflow compatibility contract that makes workflow schema version, supported feature set, and runtime compatibility decisions explicit and auditable.
- Add structured validation evidence for supported, deprecated, unsupported, and future workflow schema or feature declarations without changing existing DAG execution semantics.
- Propagate compatibility evidence through CLI/SDK validate, run, report, verification, evidence bundle, and release installability surfaces so operators can reason about workflow upgrade safety.
- Keep ReAct, provider, MCP, PlanExec, and Super-Agent boundaries unchanged; this phase strengthens the DAG production mainline only.

## Non-Goals

- No API, frontend UI, remote registry, hosted compatibility service, scheduler, worker pool, distributed execution, A2A, PlanExec runtime, or Super-Agent runtime.
- No live OpenAI-compatible provider call, live remote MCP transport/discovery, credential manager, or external network dependency.
- No semantic rewrite of DAG runtime behavior, node execution ordering, retry/governance semantics, evidence bundle trust model, release publishing, or package signing.

## Exit Criteria

- Workflow validation reports structured compatibility evidence including schema version, supported feature declarations, unsupported/future/deprecated fields or features, and deterministic operator-facing failure categories.
- Existing packaged examples remain compatible, while focused incompatible/future/deprecated workflow fixtures prove validation and runtime boundaries fail or warn with auditable evidence instead of opaque schema errors.
- Run records, run reports, verification checks, and evidence bundles include enough compatibility evidence to trace which workflow schema/features were accepted for a run.
- CLI and SDK compatibility behavior is locally demonstrable without credentials, network, API/UI, PlanExec, Super-Agent, or distributed runtime.
- Focused verifier, pytest coverage, release installability smoke, ABH verification, and independent audit confirm the contract improves traceability, failure localization, governance, and maintainability.

## Commitment Phase State

### Stable State Now

- Closed plan-023 proves the local run store can be inspected, backed up, and preflight-restored, but workflow declaration compatibility is still implicit and scattered across schema validation and runtime behavior.

### Active Change Pressure

- A production DAG Workflow kernel needs explicit compatibility evidence so operators can safely upgrade workflow declarations, diagnose unsupported features, and trust stored run evidence across versions.

### Target Stable State

- Operators can validate, run, inspect, verify, bundle, and package workflows with explicit local evidence about the schema/features accepted for each DAG run.

### Conversion Proof

- Create failing compatibility tests and fixtures, implement minimal compatibility contract surfaces, propagate evidence through report/verify/bundle/installability paths, run ABH verification, complete independent audit, close, commit, and push.

### Residual Pressure

- Remote compatibility registries, migration generators, hosted API/UI diagnostics, live MCP discovery, live provider negotiation, scheduler/worker compatibility, PlanExec runtime, Super-Agent runtime, distributed execution, and A2A remain future phases outside plan-024 scope. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run python scripts/verify_cli_workflow_compatibility.py
- uv run python scripts/verify_cli_production_demo.py
- uv run python scripts/verify_cli_bundle_integrity.py
- uv run python scripts/verify_release_installability.py
- uv run pytest tests/test_workflow_schema_contract.py tests/test_workflow_config.py tests/test_runtime_store.py tests/test_run_report.py tests/test_evidence_bundle_integrity.py -q
- uv run pytest tests/test_cli.py tests/test_documentation_contract.py tests/test_langgraph_runner.py tests/test_layers.py tests/test_react_node.py tests/test_react_openai_provider.py tests/test_tool_nodes.py -q

## Closure Evidence

- Passing focused compatibility verifier demonstrates supported, deprecated, unsupported, and future workflow declarations with structured local evidence.
- Reports, verification records, and evidence bundles contain compatibility evidence for accepted DAG runs.
- Full targeted pytest and release/demo verifiers confirm existing production DAG behavior remains compatible.
- Independent audit confirms the plan strengthens the active attractor without crossing PlanExec, Super-Agent, API/UI, live provider, or distributed boundaries.
- audit-024-dag-workflow-compatibility-contract

## Verification Runs

- ver-e24d84681f07
- ver-7734bf6b4a77
- ver-2258f40ac813

## Audits

- audit-024-dag-workflow-compatibility-contract
