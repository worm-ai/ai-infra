# Plan: Run Store Production Reliability Hardening

## Metadata

- ID: plan-023-run-store-production-reliability-hardening
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-022 are closed with a production-oriented local DAG Workflow kernel, bounded ReAct/OpenAI-compatible provider/MCP interfaces, SQLite evidence, offline bundle verification, production demo contract, release installability, and local release trust manifest. The SQLite run store is now the persistence foundation for run records, node events, verification evidence, reports, and maintenance, but reliability evidence for malformed, corrupted, locked, drifted, missing, and backup/restore states is still incomplete.
- Owner: engineering
- Created: 2026-06-17T17:28:40.425154+00:00
- Updated: 2026-06-17T19:20:50.680570+00:00

## Goals

- Strengthen the local SQLite run store reliability boundary without changing DAG runtime semantics.
- Add structured store health evidence for healthy, missing state directory, unreadable/corrupted database, lock/busy state, and schema drift scenarios.
- Add local backup and backup verification/restore preflight behavior that is deterministic and auditable through CLI and SDK boundaries.
- Preserve DAG Workflow as the production mainline while keeping ReAct/provider/MCP/PlanExec/Super-Agent boundaries unchanged.

## Non-Goals

- No remote database, scheduler, worker pool, API, frontend UI, distributed execution, A2A, PlanExec runtime, or Super-Agent runtime.
- No live OpenAI-compatible provider, live remote MCP dependency, network-required verification, external backup service, or cloud storage integration.
- No change to DAG execution semantics, workflow schema semantics, evidence bundle semantics, release trust semantics, or node behavior beyond bounded run-store reliability handling.

## Exit Criteria

- A store health CLI/SDK boundary reports structured evidence for healthy, missing state directory, missing database, locked/busy database, corrupted/unreadable database, and schema drift states.
- Local backup and backup verification/restore preflight can copy and validate a run store without requiring original workflow execution state, credentials, network, or external services.
- Lock/concurrency behavior is deterministic, with bounded timeout/retry behavior and structured failure evidence instead of hanging or opaque tracebacks.
- Existing run/report/verify/export-bundle/verify-bundle/maintenance/release-trust behavior remains compatible.
- Focused verifier demonstrates reliability scenarios, and full pytest plus ABH verification and independent audit confirm the boundary strengthens traceability, failure localization, governance, and auditability.

## Commitment Phase State

### Stable State Now

- Closed plan-022 proves release artifact trust evidence, but the local SQLite run store still lacks explicit production reliability evidence for drift, corruption, lock, missing state, and backup validation scenarios.

### Active Change Pressure

- DAG production auditability depends on the run store being diagnosable and recoverable locally; opaque SQLite failures would weaken traceability, failure localization, and governance.

### Target Stable State

- Operators can inspect, back up, and preflight-restore the run store with structured local evidence before relying on DAG run history, reports, verification results, and evidence bundles.

### Conversion Proof

- Failing-first tests, store health and backup/restore preflight implementation, focused CLI verifier, compatibility verification, ABH verification, independent audit, close, commit, and push prove the stable state.

### Residual Pressure

- Remote databases, automated retention scheduling, WAL shipping, signed backups, cloud storage, API/UI administration, distributed execution, PlanExec, Super-Agent, and A2A remain future phases outside plan-023 scope. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run python scripts/verify_cli_run_store_reliability.py
- uv run python scripts/verify_cli_maintenance.py
- uv run python scripts/verify_cli_production_demo.py
- uv run python scripts/verify_cli_bundle_integrity.py
- uv run python scripts/verify_release_installability.py
- uv run python scripts/verify_release_trust.py
- uv run pytest tests/test_runtime_store.py tests/test_run_report.py tests/test_maintenance.py -q
- uv run pytest tests/test_tool_nodes.py tests/test_react_node.py tests/test_react_openai_provider.py -q
- uv run pytest tests/test_documentation_contract.py tests/test_evidence_bundle_integrity.py tests/test_langgraph_runner.py tests/test_layers.py tests/test_production_demo_contract.py tests/test_release_trust.py tests/test_workflow_config.py tests/test_workflow_schema_contract.py -q
- uv run pytest tests/test_cli.py::test_cli_version_matches_sdk_and_package_metadata tests/test_cli.py::test_cli_validate_run_status_logs_and_verify tests/test_cli.py::test_cli_report_summarizes_failed_tool_run tests/test_cli.py::test_cli_mcp_reserved_tool_boundary_report_and_verify tests/test_cli.py::test_cli_mcp_runtime_report_verify_and_export_bundle tests/test_cli.py::test_cli_verify_reports_workflow_source_drift tests/test_cli.py::test_cli_validate_reports_schema_contract_error tests/test_cli.py::test_cli_retry_policy_report_and_verify tests/test_cli.py::test_cli_retry_exhausted_policy_report_and_verify tests/test_cli.py::test_cli_output_contract_report_and_verify tests/test_cli.py::test_cli_output_contract_failure_report_and_verify tests/test_cli.py::test_cli_resume_report_and_verify -q
- uv run pytest tests/test_cli.py::test_cli_artifact_report_verify_and_export_bundle tests/test_cli.py::test_cli_example_artifact_workflow_uses_input_artifact_path tests/test_cli.py::test_cli_governance_report_and_verify tests/test_cli.py::test_cli_validation_assertions_report_pass_and_failure tests/test_cli.py::test_cli_redaction_governance_report_verify_and_export_bundle tests/test_cli.py::test_cli_missing_required_env_fails_without_leaking_values tests/test_cli.py::test_cli_store_health_runs_and_cleanup_dry_run tests/test_cli.py::test_cli_store_health_does_not_create_missing_database tests/test_cli.py::test_cli_store_health_reports_corrupted_database_without_traceback tests/test_cli.py::test_cli_store_backup_and_restore_preflight tests/test_cli.py::test_cli_store_restore_preflight_reports_corrupted_backup tests/test_cli.py::test_cli_cleanup_apply_removes_old_run -q

## Closure Evidence

- Passing tests covering store health success, missing state/database, corrupted/unreadable database, schema drift, busy/lock evidence, backup creation, backup verification, and restore preflight failure paths.
- Passing focused run-store reliability verifier demonstrates local health and backup scenarios without network, credentials, API/UI, distributed execution, PlanExec, or Super-Agent.
- ABH verification confirms plan-023 exit criteria against the active industrial agent orchestration attractor.
- Independent audit confirms run-store reliability hardening strengthens DAG production traceability and auditability without changing runtime semantics or crossing scoped boundaries.
- Manual full-suite proof before ABH split: uv run pytest -q passed 242 tests in 159.94 seconds; ABH checklist is split only to stay under the local runner per-command timeout.
- Independent audit initially failed on unsafe file-copy backup, weak schema drift detection, busy/locked classification, and focused verifier lock coverage; fixes replaced backup with SQLite backup API, strengthened schema compatibility checks, classified busy as locked, and added CLI lock evidence.
- Second independent re-audit found backup target safety risk when output equals the live run store or an existing backup is replaced before success; fixes added same-file rejection, temporary SQLite backup output, atomic os.replace, and focused CLI evidence that same-file backup is rejected without damaging the store.

## Verification Runs

- ver-2308e6f257cd
- ver-cfc793ca86c6
- ver-14b999db504f
- ver-ddbb029703ce
- ver-3d429ee627ca
- ver-b97bd85560a9
- ver-f59009d176d8
- ver-3d93118ff252
- ver-3805e948b1a2

## Audits

- audit-023-run-store-production-reliability-hardening
