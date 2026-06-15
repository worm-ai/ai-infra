# Plan: Minimal CLI SDK Workflow MVP

## Metadata

- ID: plan-001-minimal-mvp
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Repository has active industrial Agent orchestration attractor, owner docs, and seed architecture essay; no executable Python package exists yet.
- Owner: engineering
- Created: 2026-06-15T05:59:38.677128+00:00
- Updated: 2026-06-15T07:00:54.139263+00:00

## Goals

- Create a minimal Python CLI and SDK orchestration kernel that can load, validate, execute, inspect, and verify a local YAML DAG workflow.
- Persist workflow runs, node events, and verification results in a local SQLite store.
- Keep DAG Workflow as the production-first path while preserving ReAct, PlanExec, and Super-Agent layer boundaries as minimal SDK abstractions.

## Non-Goals

- No web API or frontend UI.
- No distributed Super-Agent runtime or A2A service mesh.
- No full MCP client/server integration in this MVP.

## Exit Criteria

- A user can run ai-infra validate examples/hello_workflow.yaml and receive a valid result.
- A user can run ai-infra run examples/hello_workflow.yaml --input-file examples/hello_input.json and get a completed run id with persisted node events.
- A user can run ai-infra status <run-id>, ai-infra logs <run-id>, and ai-infra verify <run-id>.
- Python SDK exposes load_workflow, validate_workflow, run_workflow, get_run, and layer skeleton classes for ReAct, DAG Workflow, PlanExec, and SuperAgent.

## Commitment Phase State

### Stable State Now

- 

### Active Change Pressure

- 

### Target Stable State

- 

### Conversion Proof

- 

### Residual Pressure

- 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run pytest tests/test_cli.py -q
- uv run ai-infra validate examples/hello_workflow.yaml
- uv run ai-infra run examples/hello_workflow.yaml --input-file examples/hello_input.json

## Closure Evidence

- Passing pytest output.
- Passing CLI validate and run output.
- ABH doctor passes after implementation.
- Independent audit confirms MVP satisfies active attractor and plan exit criteria.
- audit-001-minimal-mvp

## Verification Runs

- ver-f4985a46389a
- ver-af4fb5b7c058
- ver-a85ff2a96c67
- ver-f36c72951fff
- ver-4ea804db2dc7

## Audits

- audit-001-minimal-mvp
