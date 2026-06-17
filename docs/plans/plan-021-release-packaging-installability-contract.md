# Plan: Release Packaging and Installability Contract

## Metadata

- ID: plan-021-release-packaging-installability-contract
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-020 are closed with a production-oriented local YAML DAG stack, bounded tool/ReAct/OpenAI-compatible provider/MCP boundaries, structured reports, SQLite evidence, provenance snapshots, governance/redaction, production demo contract, and offline evidence bundle integrity checks. The kernel is locally demonstrable, but production delivery still depends on a source checkout and uv-run development environment; there is no explicit release packaging, installed-wheel smoke contract, version surface, or preflight verifier proving a new operator can install and validate the CLI/SDK from a built artifact.
- Owner: engineering
- Created: 2026-06-17T14:54:36.382080+00:00
- Updated: 2026-06-17T16:01:17.818755+00:00

## Goals

- Create a release packaging and installability contract for the local DAG Workflow kernel without changing DAG execution semantics.
- Expose version/package metadata through CLI and SDK so installed artifacts are identifiable in reports, demos, and support workflows.
- Add deterministic preflight verification that builds the package, installs it into an isolated environment, and proves CLI/SDK/demo behavior from the installed artifact.
- Keep production-first DAG Workflow as the only mainline runtime while preserving ReAct, provider, MCP, PlanExec, and Super-Agent boundaries.

## Non-Goals

- No API, frontend UI, hosted service, scheduler, distributed execution, A2A, PlanExec runtime, or Super-Agent runtime.
- No PyPI publishing, release automation to external registries, package signing, external trust root, or release-notes automation in this phase.
- No live OpenAI-compatible provider or live remote MCP dependency in mandatory tests or validation.
- No broad refactor of runtime, store, report, ReAct, provider, MCP, or bundle verifier behavior beyond packaging/installability fixes required by this plan.

## Exit Criteria

- uv build produces source and wheel distributions containing the ai_infra package, CLI entrypoint, examples needed by installed smoke tests, and license/readme metadata as appropriate for a local release candidate.
- An installed artifact in a clean temporary virtual environment can run ai-infra --version, validate/run/report/verify/export-bundle/verify-bundle on representative workflows, and import SDK APIs without relying on the repository source tree.
- CLI and SDK expose a stable package version surface and tests cover the version command/import behavior.
- A focused verifier script proves build plus isolated install smoke behavior and is included in the ABH validation checklist.
- Existing source-tree workflows, production demo, bundle verifier, redaction governance verifier, and full pytest remain compatible.
- Packaging docs explain local build/install/smoke verification boundaries and current non-goals without implying hosted service/API/UI or external publishing.

## Commitment Phase State

### Stable State Now

- Closed plan-020 provides an auditable local DAG kernel with production demo, offline evidence bundle verification, and manifest summary consistency hardening, but installation and release-candidate behavior are not yet proven from built artifacts.

### Active Change Pressure

- A production-grade local orchestration kernel needs to be installable and identifiable outside a development checkout; otherwise demos and audits still depend on source-tree assumptions.

### Target Stable State

- A new operator can build, install, identify, smoke-test, and audit the local DAG Workflow kernel from a release artifact while retaining the same DAG-first production boundary.

### Conversion Proof

- Package metadata/version surface, installed-artifact verifier, documentation contract tests, full pytest, ABH verification, independent audit, close, commit, and push prove the release packaging boundary.

### Residual Pressure

- PyPI publishing, signed releases, SBOMs, changelog automation, hosted API/UI, live provider smoke tests, remote MCP transports, PlanExec, Super-Agent, A2A, and distributed governance remain future phases outside plan-021 scope. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv build
- uv run python scripts/verify_release_installability.py
- uv run python scripts/verify_cli_production_demo.py
- uv run python scripts/verify_cli_bundle_integrity.py
- uv run python scripts/verify_cli_redaction_governance.py

## Closure Evidence

- Passing tests covering version metadata, CLI version output, SDK imports, and packaging documentation contract.
- Passing release installability verifier proves built wheel install and installed CLI/SDK smoke behavior from a clean temporary environment.
- ABH verification confirms plan-021 exit criteria against the active industrial agent orchestration attractor.
- Independent audit confirms release packaging strengthens DAG production deliverability without introducing API/UI, PlanExec, Super-Agent, A2A, distributed execution, or live external dependencies.
- audit-021-release-packaging-installability-contract

## Verification Runs

- ver-a75e147e586c
- ver-0d22f07bdf09
- ver-df52a36b4d95
- ver-bb094b298060

## Audits

- audit-021-release-packaging-installability-contract
