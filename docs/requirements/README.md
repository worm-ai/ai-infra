# Requirements

Implementation-ready requirements live here when a slice needs durable product or behavior requirements.

Use this layer for what the system must do. Keep implementation plans in `docs/plans/`.

## MVP Requirement Baseline

The first executable MVP must provide a local Python CLI + SDK orchestration kernel.

Required capabilities:

- Load workflow definitions from YAML.
- Validate workflow structure before execution.
- Execute DAG Workflow locally through a LangGraph-first abstraction.
- Support ReAct as an atomic node type or compatible node boundary.
- Persist workflow run, node event, and verification evidence to local SQLite.
- Expose a CLI for validation, execution, status, logs, and verification.
- Expose an SDK for loading, validating, running, and reading workflow runs.

Deferred capabilities:

- Web API.
- Frontend UI or visual canvas.
- Distributed Super-Agent runtime.
- A2A service mesh.
- Full MCP client/server integration.

## Stable Commitments

- MVP behavior must serve the active attractor.
- DAG Workflow production readiness is more important than breadth of demo features.
- Higher layers can be skeletal if their interfaces preserve the ReAct -> DAG Workflow -> PlanExec -> Super-Agent dependency order.
