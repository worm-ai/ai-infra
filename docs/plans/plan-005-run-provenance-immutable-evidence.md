# Plan: Run Provenance and Immutable Evidence

## Metadata

- ID: plan-005-run-provenance-immutable-evidence
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-004 are closed with YAML DAG execution, bounded tool nodes, structured reports, and hardened workflow schema validation. Run records persist workflow_source_path, but they do not yet persist immutable workflow snapshots, content hashes, input hashes, git commit, or execution environment summaries, so audit evidence can drift when source files change after execution.
- Owner: engineering
- Created: 2026-06-15T11:49:45.047256+00:00
- Updated: 2026-06-15T12:40:30.148981+00:00

## Goals

- Persist immutable provenance for each local DAG run, including workflow snapshot, workflow hash, input hash, git commit, and execution environment summary.
- Expose provenance through CLI and SDK reporting so operators can audit exactly what was executed without trusting mutable source files.
- Teach verification to detect workflow source drift while validating against persisted run evidence.

## Non-Goals

- No web API or frontend UI.
- No MCP implementation beyond preserving future interface boundaries.
- No LLM/ReAct runtime, PlanExec runtime, or Super-Agent runtime.
- No distributed artifact store, remote scheduler, or external provenance service.

## Exit Criteria

- New runs persist immutable workflow snapshot/hash, input hash, git commit when available, and execution environment summary in SQLite.
- ai-infra report <run-id> includes provenance fields without requiring the original workflow file to remain unchanged.
- ai-infra verify <run-id> can detect when the current workflow source differs from the persisted run snapshot and records that evidence.
- Tests cover provenance persistence, report output, and workflow source mutation after a run.

## Commitment Phase State

### Stable State Now

- Closed plan-004 provides deterministic workflow schema validation, structured reports, bounded tool execution, and SQLite-backed run evidence.

### Active Change Pressure

- Production auditability requires evidence to remain stable even when workflow source files mutate after a run.

### Target Stable State

- DAG workflow runs carry immutable provenance that supports traceability, drift detection, failure localization, and governance without adding distributed infrastructure.

### Conversion Proof

- Failing-first tests, SQLite-backed provenance fields, report/verify CLI evidence, ABH verification, and independent audit prove the immutable evidence boundary.

### Residual Pressure

- Retry policies, artifact contracts, API/UI, MCP integration, LLM-backed ReAct, PlanExec, and Super-Agent remain future phases. | Non-blocking rationale:

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/tool_workflow.yaml
- uv run ai-infra run examples/tool_workflow.yaml --input-file examples/tool_input.json
- uv run python scripts/verify_cli_provenance.py

## Closure Evidence

- Passing tests covering immutable provenance and source drift detection.
- Passing CLI validate/run/report/verify evidence for example workflows.
- Independent audit confirms provenance hardening aligns with the active attractor and phase boundaries.
- audit-005-run-provenance-immutable-evidence

## Verification Runs

- ver-68487d4ca634
- ver-abf2c8a16331
- ver-ea9120cc918f
- ver-295be40b0b2a
- ver-27b81446d240
- ver-1ec080229fdb
- ver-2581b7555848

## Audits

- audit-005-run-provenance-immutable-evidence
