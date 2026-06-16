# Plan: Local Artifact Store and Evidence Bundle

## Metadata

- ID: plan-009-local-artifact-store-evidence-bundle
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-008 are closed with local YAML DAG execution, bounded tool nodes, structured reports, hardened schema validation, immutable provenance, explicit failure policy/retry semantics, output contract evidence, and local run resumption. Workflow outputs and tool results can reference files, but large or file-based artifacts do not yet have stable local storage metadata, content hashes, report evidence, verification checks, or an exportable evidence bundle.
- Owner: engineering
- Created: 2026-06-16T04:38:16.652588+00:00
- Updated: 2026-06-16T05:14:26.242708+00:00

## Goals

- Add a local artifact evidence boundary for DAG workflow runs while keeping DAG Workflow as the production-first orchestration layer.
- Capture artifact path, hash, size, content type, and source node evidence in persisted SQLite node event metadata without mutating user output payloads.
- Expose artifact evidence through report, verification, and CLI bundle export so operators can audit run outputs from stable local evidence.

## Non-Goals

- No remote object store, distributed artifact service, scheduler, API, or frontend UI.
- No MCP runtime, LLM-backed ReAct runtime, PlanExec runtime, or Super-Agent runtime.
- No automatic artifact capture from arbitrary filesystem writes beyond explicit workflow-declared artifact outputs.

## Exit Criteria

- Workflow YAML can declare artifact outputs for DAG nodes with deterministic schema validation and actionable errors.
- Runtime records artifact metadata including path, hash, size, content type, and existence status in NodeEvent.metadata artifacts evidence persisted in SQLite.
- ai-infra report <run-id> summarizes artifact evidence per node without requiring consumers to inspect raw logs.
- ai-infra verify <run-id> can validate declared artifact evidence, including existence and hash, from persisted metadata.
- CLI can export a local evidence bundle for one run, including report JSON, workflow snapshot, input summary, event evidence, and declared artifacts.
- Tests and CLI examples cover artifact capture, report, verification, and bundle export.

## Commitment Phase State

### Stable State Now

- Closed plan-008 provides immutable provenance, structured reporting, bounded tool execution, failure policies, output contract evidence, and run resumption for local DAG workflows.

### Active Change Pressure

- Production DAG workflows need stable evidence for file outputs and large artifacts so audit trails do not rely on ad hoc payload inspection or mutable side effects.

### Target Stable State

- DAG workflow runs can declare, persist, report, verify, and export local artifact evidence with deterministic hashes and paths.

### Conversion Proof

- Failing-first tests, CLI artifact examples, SQLite-backed artifact metadata, report/verify/export support, ABH verification, and independent audit prove the artifact evidence boundary.

### Residual Pressure

- Remote stores, API/UI, MCP runtime, LLM-backed ReAct, PlanExec, Super-Agent, and distributed evidence bundles remain future phases. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv run ai-infra validate examples/artifact_workflow.yaml
- uv run ai-infra run examples/artifact_workflow.yaml --input-file examples/artifact_input.json
- uv run python scripts/verify_cli_artifacts.py

## Closure Evidence

- Passing tests covering artifact schema, runtime metadata, reporting, verification, and bundle export.
- Passing CLI validate/run/report/verify/export evidence for artifact workflow examples.
- Independent audit confirms artifact evidence aligns with the active attractor and phase boundaries.
- audit-009-local-artifact-store-evidence-bundle

## Verification Runs

- ver-3ee3f89099ae
- ver-ab9ea7c31d31
- ver-7306b1c12e5a
- ver-4f5ee85ba966

## Audits

- audit-009-local-artifact-store-evidence-bundle
