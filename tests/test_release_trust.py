import hashlib
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from ai_infra.release_trust import build_release_trust_manifest, verify_release_trust_manifest


def test_build_release_trust_manifest_records_artifacts_metadata_verification_and_sbom_boundary(tmp_path):
    wheel = _write_wheel(tmp_path, name="ai_infra-0.1.0-py3-none-any.whl", version="0.1.0")
    sdist = _write_sdist(tmp_path, name="ai_infra-0.1.0.tar.gz", version="0.1.0")

    manifest = build_release_trust_manifest(
        [wheel, sdist],
        source_commit="abc123",
        tree_state="clean",
        verification_commands=[
            {"command": "uv run pytest -q", "status": "passed"},
            {"command": "uv run python scripts/verify_release_installability.py", "status": "passed"},
        ],
        build_environment={"python": "3.11.9", "platform": "test-platform"},
        sbom={"format": "none", "status": "not_generated", "reason": "deferred to future signed release phase"},
    )

    assert manifest["schema_version"] == "1"
    assert manifest["manifest_type"] == "ai_infra.release_trust"
    assert manifest["package"] == {"name": "ai-infra", "version": "0.1.0"}
    assert manifest["source"] == {"commit": "abc123", "tree_state": "clean"}
    assert manifest["build_environment"] == {"platform": "test-platform", "python": "3.11.9"}
    assert manifest["verification"]["commands"] == [
        {"command": "uv run pytest -q", "status": "passed"},
        {"command": "uv run python scripts/verify_release_installability.py", "status": "passed"},
    ]
    assert manifest["verification"]["status"] == "passed"
    assert manifest["sbom"] == {
        "format": "none",
        "status": "not_generated",
        "reason": "deferred to future signed release phase",
    }

    artifacts = {artifact["kind"]: artifact for artifact in manifest["artifacts"]}
    assert set(artifacts) == {"wheel", "sdist"}
    assert artifacts["wheel"]["filename"] == wheel.name
    assert artifacts["wheel"]["size_bytes"] == wheel.stat().st_size
    assert artifacts["wheel"]["sha256"] == _sha256(wheel)
    assert artifacts["sdist"]["filename"] == sdist.name
    assert artifacts["sdist"]["size_bytes"] == sdist.stat().st_size
    assert artifacts["sdist"]["sha256"] == _sha256(sdist)


def test_build_release_trust_manifest_orders_artifacts_deterministically(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")

    first = build_release_trust_manifest(
        [wheel, sdist],
        source_commit="abc123",
        tree_state="clean",
        verification_commands=[{"command": "uv build", "status": "passed"}],
    )
    second = build_release_trust_manifest(
        [sdist, wheel],
        source_commit="abc123",
        tree_state="clean",
        verification_commands=[{"command": "uv build", "status": "passed"}],
    )

    assert first["artifacts"] == second["artifacts"]
    assert [artifact["kind"] for artifact in first["artifacts"]] == ["sdist", "wheel"]


def test_verify_release_trust_manifest_passes_for_matching_local_artifacts(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest = build_release_trust_manifest(
        [wheel, sdist],
        source_commit="abc123",
        tree_state="clean",
        verification_commands=[{"command": "uv run pytest -q", "status": "passed"}],
        build_environment={"python": "3.11.9"},
        sbom={"format": "none", "status": "not_generated", "reason": "not required for local boundary"},
    )
    manifest_path = tmp_path / "release-trust-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path, expected_source_commit="abc123")

    assert verification.status == "passed"
    assert all(check.status == "passed" for check in verification.checks)
    assert {check.type for check in verification.checks} >= {
        "release_trust_manifest",
        "release_trust_artifact_digest",
        "release_trust_package_metadata",
        "release_trust_source",
        "release_trust_verification_summary",
        "release_trust_sbom_boundary",
    }


def test_verify_release_trust_manifest_fails_for_tampered_artifact_digest(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel, sdist])
    wheel.write_bytes(b"tampered wheel bytes")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_artifact_digest"
        and check.status == "failed"
        and wheel.name in check.message
        and "sha256" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_for_missing_artifact(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel, sdist])
    sdist.unlink()

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_artifact_digest"
        and check.status == "failed"
        and "missing" in check.message
        and sdist.name in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_for_package_metadata_mismatch(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.2.0")
    manifest_path = _write_manifest(tmp_path, [wheel, sdist])

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_package_metadata"
        and check.status == "failed"
        and "0.2.0" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_for_malformed_manifest(tmp_path):
    manifest_path = tmp_path / "release-trust-manifest.json"
    manifest_path.write_text('{"schema_version"', encoding="utf-8")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_manifest"
        and check.status == "failed"
        and "malformed JSON" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_for_malformed_valid_json_field_shapes(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel, sdist])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package"] = {"name": "", "version": "0.1.0"}
    manifest["build_environment"] = []
    manifest["artifacts"][0]["sha256"] = ""
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    failed_manifest_messages = [
        check.message
        for check in verification.checks
        if check.type == "release_trust_manifest" and check.status == "failed"
    ]
    assert any("package.name" in message for message in failed_manifest_messages)
    assert any("build_environment" in message for message in failed_manifest_messages)
    assert any("sha256" in message for message in failed_manifest_messages)


def test_verify_release_trust_manifest_fails_when_wheel_artifact_is_omitted(tmp_path):
    _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [sdist])

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_artifact_set"
        and check.status == "failed"
        and "wheel" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_when_sdist_artifact_is_omitted(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel])

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_artifact_set"
        and check.status == "failed"
        and "sdist" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_for_duplicate_artifact_kind(tmp_path):
    first_wheel = _write_wheel(tmp_path, name="ai_infra-0.1.0-py3-none-any.whl", version="0.1.0")
    second_wheel = _write_wheel(tmp_path, name="ai_infra-0.1.0-duplicate-py3-none-any.whl", version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [first_wheel, second_wheel, sdist])

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_artifact_set"
        and check.status == "failed"
        and "duplicate" in check.message
        and "wheel" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_for_unknown_artifact_kind(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel, sdist])
    unknown = tmp_path / "ai_infra-0.1.0.zip"
    unknown.write_bytes(b"not a supported release artifact")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "kind": "unknown",
            "filename": unknown.name,
            "size_bytes": unknown.stat().st_size,
            "sha256": _sha256(unknown),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_artifact_set"
        and check.status == "failed"
        and "unknown" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_when_same_file_is_declared_as_wheel_and_sdist(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "kind": "sdist",
            "filename": wheel.name,
            "size_bytes": wheel.stat().st_size,
            "sha256": _sha256(wheel),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_artifact_set"
        and check.status == "failed"
        and "duplicate filenames" in check.message
        for check in verification.checks
    )
    assert any(
        check.type == "release_trust_artifact_set"
        and check.status == "failed"
        and "declared kind 'sdist' != actual kind 'wheel'" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_when_sdist_kind_points_to_wheel_file(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel, sdist])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact["filename"] == wheel.name:
            artifact["kind"] = "sdist"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_artifact_set"
        and check.status == "failed"
        and "declared kind 'sdist' != actual kind 'wheel'" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_for_source_commit_mismatch(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel, sdist], source_commit="abc123")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path, expected_source_commit="def456")

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_source"
        and check.status == "failed"
        and "def456" in check.message
        for check in verification.checks
    )


def test_verify_release_trust_manifest_fails_for_unsupported_sbom_boundary_shape(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest = build_release_trust_manifest(
        [wheel, sdist],
        source_commit="abc123",
        tree_state="clean",
        verification_commands=[{"command": "uv run pytest -q", "status": "passed"}],
        build_environment={"python": "3.11.9"},
        sbom={"format": "cyclonedx", "status": "not_generated", "reason": "invalid mixed state"},
    )
    manifest_path = tmp_path / "release-trust-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tmp_path)

    assert verification.status == "failed"
    assert any(
        check.type == "release_trust_sbom_boundary"
        and check.status == "failed"
        and "unsupported" in check.message
        for check in verification.checks
    )


def test_cli_release_manifest_and_verify_release_round_trip(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = tmp_path / "release-trust-manifest.json"

    manifest_result = _run_cli(
        "release-manifest",
        "--artifact",
        str(wheel),
        "--artifact",
        str(sdist),
        "--output",
        str(manifest_path),
        "--source-commit",
        "abc123",
        "--tree-state",
        "clean",
        "--verification",
        "uv run pytest -q=passed",
    )

    assert manifest_result.returncode == 0
    manifest_payload = json.loads(manifest_result.stdout)
    assert manifest_payload["ok"] is True
    assert manifest_payload["manifest"]["path"] == str(manifest_path)
    assert manifest_path.exists()

    verify_result = _run_cli(
        "verify-release",
        str(manifest_path),
        "--artifact-dir",
        str(tmp_path),
        "--expected-source-commit",
        "abc123",
    )

    assert verify_result.returncode == 0
    verify_payload = json.loads(verify_result.stdout)
    assert verify_payload["ok"] is True
    assert verify_payload["verification"]["status"] == "passed"


def test_cli_verify_release_reports_failure_for_tampered_artifact(tmp_path):
    wheel = _write_wheel(tmp_path, version="0.1.0")
    sdist = _write_sdist(tmp_path, version="0.1.0")
    manifest_path = _write_manifest(tmp_path, [wheel, sdist])
    wheel.write_bytes(b"tampered")

    verify_result = _run_cli("verify-release", str(manifest_path), "--artifact-dir", str(tmp_path))

    assert verify_result.returncode == 1
    payload = json.loads(verify_result.stdout)
    assert payload["ok"] is False
    assert any(
        check["type"] == "release_trust_artifact_digest"
        and check["status"] == "failed"
        for check in payload["verification"]["checks"]
    )


def _write_manifest(
    tmp_path: Path,
    artifacts: list[Path],
    *,
    source_commit: str = "abc123",
) -> Path:
    manifest = build_release_trust_manifest(
        artifacts,
        source_commit=source_commit,
        tree_state="clean",
        verification_commands=[{"command": "uv run pytest -q", "status": "passed"}],
        build_environment={"python": "3.11.9"},
        sbom={"format": "none", "status": "not_generated", "reason": "not required for local boundary"},
    )
    manifest_path = tmp_path / "release-trust-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _write_wheel(
    directory: Path,
    *,
    name: str = "ai_infra-0.1.0-py3-none-any.whl",
    version: str,
) -> Path:
    path = directory / name
    dist_info = "ai_infra-0.1.0.dist-info"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ai_infra/__init__.py", "")
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: ai-infra\nVersion: {version}\n",
        )
        archive.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\n")
    return path


def _write_sdist(
    directory: Path,
    *,
    name: str = "ai_infra-0.1.0.tar.gz",
    version: str,
) -> Path:
    path = directory / name
    pyproject = (
        "[project]\n"
        "name = \"ai-infra\"\n"
        f"version = \"{version}\"\n"
    ).encode("utf-8")
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("ai_infra-0.1.0/pyproject.toml")
        info.size = len(pyproject)
        archive.addfile(info, _BytesReader(pyproject))
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _BytesReader:
    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._data) - self._offset
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk
