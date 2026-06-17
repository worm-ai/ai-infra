# Plan: Release Trust Manifest and SBOM Boundary

## Metadata

- ID: plan-022-release-trust-manifest-sbom-boundary
- Status: closed
- Attractor: attractor-industrial-agent-orchestration
- Baseline: Plans 001-021 are closed with a production-oriented local DAG Workflow kernel, bounded ReAct/OpenAI-compatible provider/MCP interfaces, SQLite evidence, offline evidence bundle verification, production demo contract, and release installability from built artifacts. Release candidates can now be built and smoke-tested, but artifact trust evidence is still implicit: there is no deterministic local release manifest tying wheel/sdist digests, source commit, package metadata, build environment, verification summary, and an explicit SBOM boundary into a verifiable audit artifact.
- Owner: engineering
- Created: 2026-06-17T16:17:44.018640+00:00
- Updated: 2026-06-17T17:13:46.329959+00:00

## Goals

- Create a deterministic local release trust manifest for built wheel and sdist artifacts without changing DAG runtime semantics.
- Add an offline verifier that checks artifact digests, package metadata, source commit/build environment fields, verification summary, and SBOM boundary evidence.
- Document the local release trust boundary so operators can audit release candidates without assuming PyPI publishing, signing, or remote trust roots.
- Keep DAG Workflow as the production mainline while preserving ReAct/provider/MCP/PlanExec/Super-Agent boundaries unchanged.

## Non-Goals

- No PyPI publishing, external signing service, remote trust root, hosted release service, or release automation to external registries.
- No API, frontend UI, scheduler, distributed execution, A2A, PlanExec runtime, or Super-Agent runtime.
- No live OpenAI-compatible provider, live remote MCP dependency, or network-required verification in mandatory tests.
- No change to DAG execution semantics, evidence bundle semantics, workflow validation semantics, ReAct/provider/MCP runtime behavior, or SQLite run-store behavior beyond release trust artifact generation and verification.

## Exit Criteria

- uv build artifacts can be summarized into a deterministic release trust manifest containing package name/version, artifact filenames/sizes/sha256, source commit and tree status, build environment summary, verification command summary, and SBOM boundary metadata.
- A focused offline verifier validates the manifest against local wheel/sdist artifacts and fails with actionable evidence for tampered artifact digest, missing artifact, package metadata mismatch, malformed manifest, source commit mismatch when requested, and unsupported SBOM boundary shape.
- The manifest and verifier do not require network access, credentials, PyPI, signing keys, the SQLite run store, or original workflow execution state.
- Existing release installability smoke, production demo, bundle integrity verifier, redaction governance verifier, uv build, and full pytest remain compatible.
- README/docs explain how to build, generate, verify, and interpret the local release trust manifest and explicitly list non-goals including signing, PyPI, remote trust roots, API/UI, PlanExec, and Super-Agent.
- ABH verification and independent audit confirm the release trust boundary strengthens production deliverability and auditability while staying within the active attractor.

## Commitment Phase State

### Stable State Now

- Closed plan-021 proves built wheel/sdist installability and installed CLI/SDK smoke behavior, but release trust evidence remains implicit and not independently verifiable as a local artifact.

### Active Change Pressure

- Production-grade release candidates need deterministic artifact trust evidence so operators can verify what was built, from which source, with which local verification summary, before any future publishing/signing decisions.

### Target Stable State

- A local release candidate has a deterministic trust manifest and offline verifier that make wheel/sdist integrity and release evidence auditable without external trust infrastructure.

### Conversion Proof

- Failing-first tests, release trust manifest generation, offline verifier, focused CLI script, documentation updates, full pytest, ABH verification, independent audit, close, commit, and push prove the stable state.

### Residual Pressure

- Cryptographic signing, external SBOM standards integration, PyPI publishing, release automation, changelog automation, hosted API/UI, live provider smoke tests, remote MCP transports, PlanExec, Super-Agent, A2A, and distributed governance remain future phases outside plan-022 scope. | Non-blocking rationale: 

## Validation Checklist

- abh doctor --json
- uv run pytest -q
- uv build
- uv run python scripts/verify_release_installability.py
- uv run python scripts/verify_release_trust.py
- uv run python scripts/verify_cli_production_demo.py
- uv run python scripts/verify_cli_bundle_integrity.py
- uv run python scripts/verify_cli_redaction_governance.py

## Closure Evidence

- Passing tests covering release trust manifest generation, offline verification success, tamper/missing/malformed/package-mismatch/source-commit/SBOM-boundary failures, and documentation contract.
- Passing release trust verifier proves build, manifest generation, offline verification, and representative failure detection without live external services.
- ABH verification confirms plan-022 exit criteria against the active industrial agent orchestration attractor.
- Independent audit confirms release trust work strengthens local DAG production deliverability without introducing API/UI, PlanExec, Super-Agent, A2A, distributed execution, signing, PyPI publishing, or live dependencies.
- audit-022-release-trust-manifest-sbom-boundary

## Verification Runs

- ver-e8c419df008e
- ver-bc6e6d743e6e
- ver-8df7cb00d87f

## Audits

- audit-022-release-trust-manifest-sbom-boundary
