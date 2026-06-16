# Plan: Run Store Maintenance and Retention

## Metadata

- ID: plan-011-run-store-maintenance-retention
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-010 are closed with local YAML DAG execution, bounded tool nodes, structured reports, hardened schema validation, immutable provenance, explicit failure policy/retry semantics, output contracts, run resumption, local artifact evidence bundles, and execution governance policies. The local SQLite run store and artifact/evidence files now need production-oriented health inspection, run listing, deterministic retention dry-run/apply, and orphan evidence detection so long-running local use remains auditable and operable.
- Owner: engineering
- Created: 2026-06-16T06:18:04.719933+00:00
- Updated: 2026-06-16T06:55:20.663614+00:00

## Goals

- Add local run store maintenance capabilities for health inspection, run listing, and retention planning without changing DAG execution semantics.
- Expose maintenance operations through CLI and SDK so operators can inspect store health, summarize runs, and safely clean old local evidence.
- Detect orphan artifact/evidence files and record deterministic maintenance evidence for cleanup decisions.

## Non-Goals

- No web API or frontend UI.
- No remote scheduler, distributed queue, background worker, or remote object store.
- No MCP runtime, LLM-backed ReAct runtime, PlanExec runtime, or Super-Agent runtime.
- No automatic deletion without explicit apply mode; dry-run must remain the default safety path.

## Exit Criteria

- CLI and SDK can inspect local run store health, including database existence, table presence, run/event/verification/reservation counts, and artifact directory status.
- CLI and SDK can list runs with deterministic summaries and optional status filtering.
- Retention cleanup supports dry-run and explicit apply based on deterministic keep-last and status filters, deleting run rows and declared artifact files only when safe.
- Maintenance detects orphan artifact/evidence files under the local state directory and reports them without deleting by default.
- Tests cover health inspection, run listing, cleanup dry-run/apply, artifact safety, orphan detection, and CLI behavior.

## Commitment Phase State

### Stable State Now

- Closed plan-010 provides governed local DAG execution with persisted run, event, verification, provenance, artifact, resumption, and governance evidence.

### Active Change Pressure

- Production local use needs run store health, retention, and cleanup tooling so SQLite and artifact evidence do not become opaque or unbounded.

### Target Stable State

- Local DAG workflow evidence can be inspected, summarized, and retained or cleaned through deterministic maintenance commands with safe dry-run defaults.

### Conversion Proof

- Failing-first tests, CLI maintenance examples, SQLite-backed cleanup behavior, ABH verification, and independent audit prove the maintenance boundary.

### Residual Pressure

- API/UI, remote stores, scheduled maintenance, MCP runtime, LLM-backed ReAct, PlanExec, and Super-Agent remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run python scripts/verify_cli_maintenance.py

## Closure Evidence

- Passing tests covering run store maintenance and retention behavior.
- Passing CLI maintenance verification evidence.
- Independent audit confirms maintenance operations align with the active attractor and phase boundaries.
- audit-011-run-store-maintenance-retention

## Verification Runs

- ver-f5eb148b7d52
- ver-6cb27cb2c69a
- ver-0db6491bd95a
- ver-6713d633d4d7
- ver-f67461ee13b1
- ver-871ca7118e5a
- ver-d4b132c7497f

## Audits

- audit-011-run-store-maintenance-retention
