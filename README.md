# ai-infra

`ai-infra` is a local-first, industrial Agentic Infra orchestration kernel. It is built around an evidence-first DAG Workflow runtime with YAML workflow declarations, a Python SDK, a CLI, SQLite run state, structured reports, verification records, and exportable evidence bundles.

The project is governed by the active ABH attractor in `docs/architecture/attractors/industrial-agent-orchestration.md`.

## Architecture Boundary

DAG Workflow is the production-first path. The outer orchestration remains explicit, traceable, and auditable so production operators can inspect workflow topology, node events, failures, governance decisions, and evidence bundles.

ReAct is an atomic DAG node. It can perform bounded local reasoning or call a configured OpenAI-compatible provider inside one workflow node, but it does not own long-running business process orchestration.

MCP is a tool and data-source reuse boundary. The current required runtime is deterministic local/fake MCP execution for DAG tool nodes and ReAct-declared tools; live transports and discovery remain future work.

PlanExec and Super-Agent remain future layers. They must build on the verified DAG Workflow boundary instead of replacing it or bypassing run evidence.

## Current Production Surface

- YAML DAG workflow loading and schema validation.
- LangGraph-backed local DAG execution.
- Python, shell, HTTP, ReAct, OpenAI-compatible fake provider, and local/fake MCP tool boundaries.
- SQLite run store with run status, node events, verification results, and provenance snapshots.
- Retry, failure policy, output contracts, resumption, governance budgets, redaction, artifact evidence, and retention helpers.
- CLI commands for validate, run, resume, status, logs, report, verify, export-bundle, verify-bundle, runs, store-health, and cleanup.
- SDK functions for local embedding in Python applications.

## Prerequisites

- Python 3.11 or newer.
- `uv` for reproducible local commands.

Install dependencies:

```powershell
uv sync
```

## Quickstart

Validate a workflow:

```powershell
uv run ai-infra validate examples/hello_workflow.yaml
```

Run it with local input:

```powershell
uv run ai-infra run examples/hello_workflow.yaml --input-file examples/hello_input.json
```

The run command prints a JSON payload containing a `run_id`. Use that id in the inspection commands below:

```powershell
uv run ai-infra status <run-id>
uv run ai-infra logs <run-id>
uv run ai-infra report <run-id>
uv run ai-infra verify <run-id>
uv run ai-infra export-bundle <run-id> --output-dir .ai-infra/bundles
uv run ai-infra verify-bundle .ai-infra/bundles/<run-id>-evidence-bundle.zip
```

Run the full local production demo contract:

```powershell
uv run python scripts/verify_cli_production_demo.py
```

That verifier uses temporary local state and does not require external credentials.

## Representative Workflows

- `examples/hello_workflow.yaml`: minimal DAG success path.
- `examples/tool_workflow.yaml`: Python, shell, and HTTP tool nodes.
- `examples/tool_failure_workflow.yaml`: auditable tool failure.
- `examples/governance_workflow.yaml`: execution governance and skipped-node evidence.
- `examples/redaction_workflow.yaml`: required environment and sensitive input redaction.
- `examples/react_workflow.yaml`: bounded ReAct atomic node with a declared tool.
- `examples/react_openai_compatible_workflow.yaml`: fake OpenAI-compatible provider boundary.
- `examples/mcp_runtime_workflow.yaml`: deterministic local MCP runtime boundary.

## SDK Usage

```python
from pathlib import Path

from ai_infra import (
    build_run_report,
    default_store,
    export_evidence_bundle,
    get_run,
    load_workflow,
    run_workflow,
    validate_stored_run,
    validate_workflow,
    verify_evidence_bundle,
)

workflow = load_workflow(Path("examples/hello_workflow.yaml"))
validate_workflow(workflow)

store = default_store(".ai-infra")
result = run_workflow(workflow, {"topic": "ABH"}, store=store)
verification = validate_stored_run(result.run_id, store=store)
run = get_run(result.run_id, store=store)
report = build_run_report(result.run_id, store=store)
bundle = export_evidence_bundle(run, report, ".ai-infra/bundles")
bundle_verification = verify_evidence_bundle(bundle.path)

assert verification.status == "passed"
assert bundle_verification.status == "passed"
print(result.run_id, bundle.path)
```

## Evidence Model

Each run persists:

- Run inputs and outputs after configured redaction.
- Ordered node events with inputs, outputs, status, metadata, attempts, tool invocation evidence, ReAct evidence, governance evidence, contracts, and artifacts.
- Immutable workflow provenance with source hash and environment summary.
- Verification checks declared by the workflow.
- Optional evidence bundles containing report JSON, inputs, events, redacted workflow snapshot, manifest digests, and collected artifacts.
- Offline bundle verification with per-file SHA-256 checks, run identity checks, JSON/YAML schema checks, and redaction-path checks. This verifies internal bundle consistency; external authenticity and signing remain future work.

The evidence model is designed for traceability, failure localization, cost/governance inspection, and audit review.

## Verification Matrix

Core verification:

```powershell
abh doctor --json
uv run pytest -q
uv run python scripts/verify_cli_production_demo.py
uv run python scripts/verify_cli_bundle_integrity.py
```

Focused verifier scripts:

```powershell
uv run python scripts/verify_cli_react_openai_provider.py
uv run python scripts/verify_cli_mcp_runtime.py
uv run python scripts/verify_cli_redaction_governance.py
uv run python scripts/verify_cli_bundle_integrity.py
uv run python scripts/verify_cli_retry_policy.py
uv run python scripts/verify_cli_resume.py
uv run python scripts/verify_cli_artifacts.py
```

## Current Non-Goals

- No API/UI.
- No PlanExec runtime.
- No Super-Agent runtime.
- No A2A or distributed runtime.
- No hosted scheduler or remote worker.
- No mandatory live OpenAI-compatible provider call.
- No mandatory live remote MCP server, transport discovery, or credential manager.

These are intentionally deferred until the local DAG Workflow production boundary remains demonstrably stable under ABH verification and independent audit.

## ABH Workflow

Every feature stage is bound to an active attractor and an ABH plan. A stage is complete only after implementation, verification, independent audit, `abh close`, commit, and push.

The current plans and audits live in:

- `docs/plans/`
- `docs/audits/`

Use `abh plan list` and `abh attractor active --json` to inspect the current governance state.
