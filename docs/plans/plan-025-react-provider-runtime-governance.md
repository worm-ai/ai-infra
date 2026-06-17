# Plan: ReAct Provider Runtime Governance Boundary

## Metadata

- ID: plan-025-react-provider-runtime-governance
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-024 are closed with a local-first production DAG Workflow kernel, bounded ReAct atomic nodes, an OpenAI-compatible provider boundary, MCP-reserved/runtime tool boundaries, SQLite evidence, reports, verification, evidence bundles, release trust, run-store reliability, and workflow compatibility evidence. Plan-016 made optional OpenAI-compatible calls possible inside DAG react nodes, but runtime policy for live HTTP provider usage is still implicit: operators cannot deterministically require fake/offline-only provider execution, explicitly allow live HTTP calls, or capture provider-mode governance evidence across run/report/verify/bundle surfaces.
- Owner: engineering
- Created: 2026-06-17T20:47:10.901113+00:00
- Updated: 2026-06-17T21:40:39.628109+00:00

## Goals

- Add explicit runtime governance for OpenAI-compatible ReAct provider modes while keeping ReAct as an atomic DAG node.
- Require live HTTP provider calls to pass an explicit allow policy, with deterministic disabled/fake/dry-run evidence when live calls are not allowed.
- Propagate provider runtime mode, allow/deny reason, and dry-run request summary through SQLite events, reports, verification, and evidence bundles without leaking prompts or API keys.
- Preserve DAG Workflow as the production mainline and keep PlanExec, Super-Agent, API/UI, distributed execution, and live-network-required verification out of scope.

## Non-Goals

- No PlanExec runtime, Super-Agent runtime, API, frontend UI, scheduler, distributed execution, A2A, or autonomous outer planner.
- No mandatory live OpenAI-compatible network call in tests, verification, ABH closure, or release smoke; local fake and dry-run modes remain sufficient.
- No new provider marketplace, streaming protocol, MCP remote transport expansion, credential manager, or provider-specific advanced model features.
- No unbounded ReAct loop, hidden chain-of-thought persistence, or ReAct ownership of multi-step business workflow orchestration.

## Exit Criteria

- Workflow config can declare provider runtime governance for openai-compatible ReAct nodes with deterministic validation for supported modes and allow-live behavior.
- HTTP provider calls fail fast with structured provider governance evidence when live calls are disabled, without attempting network access or leaking API key values.
- A local dry-run provider workflow records request summary, model identity, budget metadata, runtime mode, and terminal result evidence without network access.
- Fake provider, disabled live provider, dry-run provider, missing key, budget exhaustion, redaction bundle, report, verify, and logs remain auditable end to end.
- Focused verifier, pytest coverage, ABH verification, and independent audit confirm this strengthens traceability, failure localization, cost control, governance, and auditability without crossing the active attractor boundaries.

## Commitment Phase State

### Stable State Now

- Closed plan-024 makes workflow compatibility explicit, and closed plan-016 already provides fake/local OpenAI-compatible ReAct provider execution plus timeout, key, budget, error, report, verify, and bundle evidence.

### Active Change Pressure

- Production operators need a deterministic local policy boundary that prevents accidental live HTTP provider calls unless explicitly allowed and records why a provider call ran, dry-ran, or was denied.

### Target Stable State

- DAG react nodes expose provider runtime governance evidence so live, fake, and dry-run provider modes are auditable and controlled while ReAct remains an atomic execution unit.

### Conversion Proof

- Create failing tests for disabled live HTTP and dry-run provider modes, implement minimal config/runtime/report/verify/bundle evidence propagation, run focused verifier, full relevant pytest, ABH verification, independent audit, close, commit, and push.

### Residual Pressure

- Live provider smoke tests, richer adapters, streaming, credential vaults, remote MCP discovery, API/UI diagnostics, scheduler/worker policy, PlanExec, Super-Agent, A2A, and distributed governance remain future phases outside plan-025 scope. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run python scripts/verify_cli_react_provider_governance.py
- uv run python scripts/verify_cli_react_openai_provider.py
- uv run python scripts/verify_cli_production_demo.py
- uv run python scripts/verify_cli_bundle_integrity.py
- uv run pytest tests/test_react_openai_provider.py tests/test_workflow_schema_contract.py tests/test_run_report.py tests/test_evidence_bundle_integrity.py -q
- uv run pytest tests/test_documentation_contract.py tests/test_langgraph_runner.py tests/test_react_node.py tests/test_tool_nodes.py -q
- uv run pytest tests/test_cli.py::test_cli_version_matches_sdk_and_package_metadata tests/test_cli.py::test_cli_validate_run_status_logs_and_verify tests/test_cli.py::test_cli_report_summarizes_failed_tool_run tests/test_cli.py::test_cli_mcp_reserved_tool_boundary_report_and_verify tests/test_cli.py::test_cli_mcp_runtime_report_verify_and_export_bundle tests/test_cli.py::test_cli_verify_reports_workflow_source_drift tests/test_cli.py::test_cli_validate_reports_schema_contract_error tests/test_cli.py::test_cli_retry_policy_report_and_verify tests/test_cli.py::test_cli_retry_exhausted_policy_report_and_verify tests/test_cli.py::test_cli_output_contract_report_and_verify tests/test_cli.py::test_cli_output_contract_failure_report_and_verify tests/test_cli.py::test_cli_resume_report_and_verify -q
- uv run pytest tests/test_cli.py::test_cli_artifact_report_verify_and_export_bundle tests/test_cli.py::test_cli_example_artifact_workflow_uses_input_artifact_path tests/test_cli.py::test_cli_governance_report_and_verify tests/test_cli.py::test_cli_validation_assertions_report_pass_and_failure tests/test_cli.py::test_cli_redaction_governance_report_verify_and_export_bundle tests/test_cli.py::test_cli_missing_required_env_fails_without_leaking_values tests/test_cli.py::test_cli_store_health_runs_and_cleanup_dry_run tests/test_cli.py::test_cli_store_health_does_not_create_missing_database tests/test_cli.py::test_cli_store_health_reports_corrupted_database_without_traceback tests/test_cli.py::test_cli_store_backup_and_restore_preflight tests/test_cli.py::test_cli_store_restore_preflight_reports_corrupted_backup tests/test_cli.py::test_cli_cleanup_apply_removes_old_run -q

## Closure Evidence

- Passing focused provider governance verifier demonstrates fake, dry-run, disabled-live, missing-key, budget, redaction, report, verify, and bundle evidence without mandatory network calls.
- Reports, verification records, logs, and evidence bundles include provider runtime governance evidence for accepted DAG ReAct runs.
- Independent audit confirms the plan strengthens the active attractor without crossing PlanExec, Super-Agent, API/UI, live-network-required, or distributed boundaries.
- audit-025-react-provider-runtime-governance

## Verification Runs

- ver-64da47890117
- ver-2f75b78de1a9
- ver-e87f5e2dd58a
- ver-ebd50ab2d08a
- ver-a027f64a12f1

## Audits

- audit-025-react-provider-runtime-governance
