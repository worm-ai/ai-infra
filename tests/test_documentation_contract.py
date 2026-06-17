from pathlib import Path

import tomllib


def test_pyproject_declares_release_metadata_and_wheel_entrypoint():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["readme"] == "README.md"
    assert pyproject["project"]["scripts"]["ai-infra"] == "ai_infra.cli:main"
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/ai_infra"]
    assert "src/ai_infra/examples/*.yaml" in pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]
    assert "src/ai_infra/examples/*.json" in pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]


def test_release_installability_verifier_is_tracked():
    verifier = Path("scripts/verify_release_installability.py")
    verifier_source = verifier.read_text(encoding="utf-8")

    assert verifier.exists()
    assert "def main()" in verifier_source
    assert "ai_infra/examples/release_smoke_workflow.yaml" in verifier_source
    assert "ai_infra/examples/release_smoke_input.json" in verifier_source
    assert "resources.files('ai_infra').joinpath('examples')" in verifier_source


def test_release_trust_verifier_is_tracked():
    verifier = Path("scripts/verify_release_trust.py")
    verifier_source = verifier.read_text(encoding="utf-8")

    assert verifier.exists()
    assert "def main()" in verifier_source
    assert "build_release_trust_manifest" in verifier_source
    assert "verify_release_trust_manifest" in verifier_source
    assert "tampered_artifact" in verifier_source
    assert "missing_artifact" in verifier_source
    assert "package_metadata_mismatch" in verifier_source
    assert "source_commit_mismatch" in verifier_source
    assert "unsupported_sbom_boundary" in verifier_source


def test_readme_documents_production_dag_delivery_contract():
    readme = Path("README.md").read_text(encoding="utf-8")

    required_phrases = [
        "industrial Agentic Infra orchestration kernel",
        "DAG Workflow is the production-first path",
        "ReAct is an atomic DAG node",
        "MCP is a tool and data-source reuse boundary",
        "PlanExec and Super-Agent remain future layers",
        "uv run ai-infra validate examples/hello_workflow.yaml",
        "uv build",
        "uv run python scripts/verify_release_installability.py",
        "uv run python scripts/verify_release_trust.py",
        "uv run ai-infra release-manifest",
        "uv run ai-infra verify-release",
        "ai-infra --version",
        "clean temporary virtual environment",
        "packaged smoke examples",
        "release trust manifest",
        "wheel and source distribution SHA-256",
        "source commit",
        "SBOM boundary",
        "No package signing",
        "No external trust root",
        "No PyPI publishing",
        "uv run ai-infra run examples/hello_workflow.yaml --input-file examples/hello_input.json",
        "uv run ai-infra status",
        "uv run ai-infra logs",
        "uv run ai-infra report",
        "uv run ai-infra verify",
        "uv run ai-infra export-bundle",
        "uv run ai-infra verify-bundle",
        "uv run python scripts/verify_cli_production_demo.py",
        "uv run python scripts/verify_cli_bundle_integrity.py",
        "load_workflow",
        "run_workflow",
        "build_run_report",
        "build_release_trust_manifest",
        "export_evidence_bundle",
        "verify_evidence_bundle",
        "verify_release_trust_manifest",
        "No API/UI",
        "No PlanExec runtime",
        "No Super-Agent runtime",
        "No A2A or distributed runtime",
    ]

    missing = [phrase for phrase in required_phrases if phrase not in readme]

    assert missing == []
