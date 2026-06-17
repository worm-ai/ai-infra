from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Any

from .store import VerificationCheck


RELEASE_TRUST_SCHEMA_VERSION = "1"
RELEASE_TRUST_MANIFEST_TYPE = "ai_infra.release_trust"


@dataclass(frozen=True)
class ReleaseTrustVerification:
    package: dict[str, str]
    status: str
    checks: list[VerificationCheck]


def build_release_trust_manifest(
    artifact_paths: list[str | Path],
    *,
    source_commit: str | None = None,
    tree_state: str | None = None,
    verification_commands: list[dict[str, str]] | None = None,
    build_environment: dict[str, Any] | None = None,
    sbom: dict[str, str] | None = None,
) -> dict[str, Any]:
    artifacts = sorted(
        (_artifact_summary(Path(path)) for path in artifact_paths),
        key=lambda artifact: (artifact["kind"], artifact["filename"]),
    )
    package = _declared_package(artifacts)
    verification_items = _verification_items(verification_commands or [])
    return {
        "schema_version": RELEASE_TRUST_SCHEMA_VERSION,
        "manifest_type": RELEASE_TRUST_MANIFEST_TYPE,
        "package": package,
        "source": {
            "commit": source_commit,
            "tree_state": tree_state,
        },
        "build_environment": _build_environment(build_environment),
        "verification": {
            "status": "passed" if verification_items and all(item.get("status") == "passed" for item in verification_items) else "failed",
            "commands": verification_items,
        },
        "sbom": sbom or _default_sbom_boundary(),
        "artifacts": [
            {
                "kind": artifact["kind"],
                "filename": artifact["filename"],
                "size_bytes": artifact["size_bytes"],
                "sha256": artifact["sha256"],
            }
            for artifact in artifacts
        ],
    }


def verify_release_trust_manifest(
    manifest_path: str | Path,
    *,
    artifact_dir: str | Path | None = None,
    expected_source_commit: str | None = None,
) -> ReleaseTrustVerification:
    manifest_file = Path(manifest_path)
    artifact_root = Path(artifact_dir) if artifact_dir is not None else manifest_file.parent
    checks: list[VerificationCheck] = []
    manifest = _read_manifest(manifest_file, checks)
    if not isinstance(manifest, dict):
        return ReleaseTrustVerification(package={}, status="failed", checks=checks)

    _check_manifest_shape(manifest, checks)
    _check_artifact_set(manifest, artifact_root, checks)
    _check_artifact_digests(manifest, artifact_root, checks)
    _check_package_metadata(manifest, artifact_root, checks)
    _check_source(manifest, expected_source_commit, checks)
    _check_verification_summary(manifest, checks)
    _check_sbom_boundary(manifest, checks)

    status = "passed" if checks and all(check.status == "passed" for check in checks) else "failed"
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    return ReleaseTrustVerification(
        package={str(key): str(value) for key, value in package.items()},
        status=status,
        checks=checks,
    )


def current_source_commit(cwd: str | Path | None = None) -> str | None:
    result = _run_git(["rev-parse", "HEAD"], cwd)
    return result or None


def current_tree_state(cwd: str | Path | None = None) -> str:
    status = _run_git(["status", "--short"], cwd)
    if status is None:
        return "unknown"
    return "clean" if not status.strip() else "dirty"


def default_build_environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }


def write_release_trust_manifest(
    manifest: dict[str, Any],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _artifact_summary(path: Path) -> dict[str, Any]:
    metadata = _artifact_metadata(path)
    return {
        "kind": _artifact_kind(path),
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "package": metadata,
    }


def _declared_package(artifacts: list[dict[str, Any]]) -> dict[str, str]:
    wheel_metadata = next((artifact["package"] for artifact in artifacts if artifact["kind"] == "wheel"), None)
    metadata = wheel_metadata or (artifacts[0]["package"] if artifacts else {})
    return {
        "name": str(metadata.get("name", "")),
        "version": str(metadata.get("version", "")),
    }


def _artifact_kind(path: Path) -> str:
    if path.suffix == ".whl":
        return "wheel"
    if path.name.endswith(".tar.gz") or path.suffix == ".zip":
        return "sdist"
    return "unknown"


def _artifact_metadata(path: Path) -> dict[str, str]:
    kind = _artifact_kind(path)
    if kind == "wheel":
        return _wheel_metadata(path)
    if kind == "sdist":
        return _sdist_metadata(path)
    return {"name": "", "version": ""}


def _wheel_metadata(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata_name = next((name for name in archive.namelist() if name.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            return {"name": "", "version": ""}
        message = Parser().parsestr(archive.read(metadata_name).decode("utf-8", errors="replace"))
    return {"name": message.get("Name", ""), "version": message.get("Version", "")}


def _sdist_metadata(path: Path) -> dict[str, str]:
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            pyproject_name = next((name for name in archive.getnames() if name.endswith("/pyproject.toml")), None)
            if pyproject_name is None:
                return {"name": "", "version": ""}
            member = archive.extractfile(pyproject_name)
            if member is None:
                return {"name": "", "version": ""}
            data = tomllib.loads(member.read().decode("utf-8"))
            project = data.get("project", {})
            return {"name": str(project.get("name", "")), "version": str(project.get("version", ""))}
    with zipfile.ZipFile(path) as archive:
        pyproject_name = next((name for name in archive.namelist() if name.endswith("/pyproject.toml")), None)
        if pyproject_name is None:
            return {"name": "", "version": ""}
        data = tomllib.loads(archive.read(pyproject_name).decode("utf-8"))
        project = data.get("project", {})
        return {"name": str(project.get("name", "")), "version": str(project.get("version", ""))}


def _verification_items(commands: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "command": str(item.get("command", "")),
            "status": str(item.get("status", "")),
        }
        for item in commands
    ]


def _build_environment(environment: dict[str, Any] | None) -> dict[str, Any]:
    if environment is None:
        return default_build_environment()
    return {str(key): environment[key] for key in sorted(environment)}


def _default_sbom_boundary() -> dict[str, str]:
    return {
        "format": "none",
        "status": "not_generated",
        "reason": "SBOM generation is outside the local release trust boundary for this phase",
    }


def _read_manifest(path: Path, checks: list[VerificationCheck]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checks.append(
            VerificationCheck(
                type="release_trust_manifest",
                status="failed",
                message=f"manifest {path} is missing",
            )
        )
        return None
    except json.JSONDecodeError as exc:
        checks.append(
            VerificationCheck(
                type="release_trust_manifest",
                status="failed",
                message=f"manifest is malformed JSON: {exc}",
            )
        )
        return None
    if not isinstance(value, dict):
        checks.append(
            VerificationCheck(
                type="release_trust_manifest",
                status="failed",
                message="manifest root must be an object",
            )
        )
        return None
    return value


def _check_manifest_shape(manifest: dict[str, Any], checks: list[VerificationCheck]) -> None:
    schema_version = manifest.get("schema_version")
    manifest_type = manifest.get("manifest_type")
    required = ("package", "source", "build_environment", "verification", "sbom", "artifacts")
    missing = [field for field in required if field not in manifest]
    failures: list[str] = []
    if schema_version != RELEASE_TRUST_SCHEMA_VERSION:
        failures.append(f"schema_version {schema_version!r} != {RELEASE_TRUST_SCHEMA_VERSION!r}")
    if manifest_type != RELEASE_TRUST_MANIFEST_TYPE:
        failures.append(f"manifest_type {manifest_type!r} != {RELEASE_TRUST_MANIFEST_TYPE!r}")
    if missing:
        failures.append(f"missing required fields: {missing}")
    package = manifest.get("package")
    if not isinstance(package, dict):
        failures.append("package must be an object")
    else:
        if not isinstance(package.get("name"), str) or not package.get("name"):
            failures.append("package.name must be a non-empty string")
        if not isinstance(package.get("version"), str) or not package.get("version"):
            failures.append("package.version must be a non-empty string")
    if not isinstance(manifest.get("source"), dict):
        failures.append("source must be an object")
    build_environment = manifest.get("build_environment")
    if not isinstance(build_environment, dict):
        failures.append("build_environment must be an object")
    elif not build_environment:
        failures.append("build_environment must not be empty")
    if not isinstance(manifest.get("verification"), dict):
        failures.append("verification must be an object")
    if not isinstance(manifest.get("sbom"), dict):
        failures.append("sbom must be an object")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        failures.append("artifacts must be a list")
    else:
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                failures.append(f"artifacts[{index}] must be an object")
                continue
            if artifact.get("kind") not in {"wheel", "sdist"}:
                failures.append(f"artifacts[{index}].kind {artifact.get('kind')!r} must be 'wheel' or 'sdist'")
            if not isinstance(artifact.get("filename"), str) or not artifact.get("filename"):
                failures.append(f"artifacts[{index}].filename must be a non-empty string")
            if not isinstance(artifact.get("size_bytes"), int) or artifact.get("size_bytes") < 0:
                failures.append(f"artifacts[{index}].size_bytes must be a non-negative integer")
            sha256 = artifact.get("sha256")
            if not isinstance(sha256, str) or len(sha256) != 64:
                failures.append(f"artifacts[{index}].sha256 must be a 64-character hex string")
            elif any(character not in "0123456789abcdef" for character in sha256.lower()):
                failures.append(f"artifacts[{index}].sha256 must be lowercase hex")
    checks.append(
        VerificationCheck(
            type="release_trust_manifest",
            status="failed" if failures else "passed",
            message="; ".join(failures) if failures else "manifest schema and type are supported",
        )
    )


def _check_artifact_set(manifest: dict[str, Any], artifact_root: Path, checks: list[VerificationCheck]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return
    filenames = [
        str(artifact.get("filename"))
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("filename") is not None
    ]
    kinds = [
        str(artifact.get("kind"))
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("kind") is not None
    ]
    failures: list[str] = []
    duplicate_filenames = sorted(filename for filename in set(filenames) if filenames.count(filename) > 1)
    if duplicate_filenames:
        failures.append(f"duplicate filenames: {duplicate_filenames}")
    unknown = sorted(kind for kind in kinds if kind not in {"wheel", "sdist"})
    if unknown:
        failures.append(f"unknown artifact kinds: {unknown}")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        declared_kind = str(artifact.get("kind", ""))
        filename = str(artifact.get("filename", ""))
        path = artifact_root / filename
        if not path.is_file():
            continue
        actual_kind = _artifact_kind(path)
        if declared_kind in {"wheel", "sdist"} and actual_kind != declared_kind:
            failures.append(f"{filename}: declared kind {declared_kind!r} != actual kind {actual_kind!r}")
    for expected_kind in ("sdist", "wheel"):
        count = kinds.count(expected_kind)
        if count == 0:
            failures.append(f"missing required {expected_kind} artifact")
        elif count > 1:
            failures.append(f"duplicate {expected_kind} artifacts: {count}")
    checks.append(
        VerificationCheck(
            type="release_trust_artifact_set",
            status="failed" if failures else "passed",
            message="; ".join(failures) if failures else "release artifact set contains one sdist and one wheel",
        )
    )


def _check_artifact_digests(manifest: dict[str, Any], artifact_root: Path, checks: list[VerificationCheck]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            checks.append(
                VerificationCheck(
                    type="release_trust_artifact_digest",
                    status="failed",
                    message="artifact entry must be an object",
                )
            )
            continue
        filename = str(artifact.get("filename", ""))
        path = artifact_root / filename
        if not path.is_file():
            checks.append(
                VerificationCheck(
                    type="release_trust_artifact_digest",
                    status="failed",
                    message=f"artifact {filename!r} is missing from {artifact_root}",
                )
            )
            continue
        actual_size = path.stat().st_size
        actual_sha256 = _sha256(path)
        expected_size = artifact.get("size_bytes")
        expected_sha256 = artifact.get("sha256")
        passed = actual_size == expected_size and actual_sha256 == expected_sha256
        checks.append(
            VerificationCheck(
                type="release_trust_artifact_digest",
                status="passed" if passed else "failed",
                message=(
                    f"artifact {filename!r} size and sha256 match manifest"
                    if passed
                    else (
                        f"artifact {filename!r} digest mismatch: size {actual_size}/{expected_size}, "
                        f"sha256 {actual_sha256}/{expected_sha256}"
                    )
                ),
            )
        )


def _check_package_metadata(manifest: dict[str, Any], artifact_root: Path, checks: list[VerificationCheck]) -> None:
    declared_package = manifest.get("package")
    artifacts = manifest.get("artifacts")
    if not isinstance(declared_package, dict) or not isinstance(artifacts, list):
        return
    expected = {
        "name": str(declared_package.get("name", "")),
        "version": str(declared_package.get("version", "")),
    }
    failures: list[str] = []
    checked = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = artifact_root / str(artifact.get("filename", ""))
        if not path.is_file():
            continue
        try:
            actual = _artifact_metadata(path)
        except (OSError, tarfile.TarError, zipfile.BadZipFile, tomllib.TOMLDecodeError) as exc:
            failures.append(f"{path.name} metadata is unreadable: {exc}")
            continue
        checked += 1
        if actual != expected:
            failures.append(f"{path.name} package metadata {actual!r} != manifest package {expected!r}")
    if checked == 0 and not failures:
        failures.append("no local artifacts were available for package metadata verification")
    checks.append(
        VerificationCheck(
            type="release_trust_package_metadata",
            status="failed" if failures else "passed",
            message="; ".join(failures) if failures else f"artifact package metadata matches {expected['name']} {expected['version']}",
        )
    )


def _check_source(
    manifest: dict[str, Any],
    expected_source_commit: str | None,
    checks: list[VerificationCheck],
) -> None:
    source = manifest.get("source")
    if not isinstance(source, dict):
        checks.append(
            VerificationCheck(
                type="release_trust_source",
                status="failed",
                message="source must be an object",
            )
        )
        return
    commit = source.get("commit")
    tree_state = source.get("tree_state")
    failures: list[str] = []
    if not commit:
        failures.append("source commit is missing")
    if tree_state not in {"clean", "dirty", "unknown"}:
        failures.append(f"tree_state {tree_state!r} is unsupported")
    if expected_source_commit is not None and commit != expected_source_commit:
        failures.append(f"source commit {commit!r} != expected source commit {expected_source_commit!r}")
    checks.append(
        VerificationCheck(
            type="release_trust_source",
            status="failed" if failures else "passed",
            message="; ".join(failures) if failures else f"source commit {commit!r} is accepted",
        )
    )


def _check_verification_summary(manifest: dict[str, Any], checks: list[VerificationCheck]) -> None:
    verification = manifest.get("verification")
    if not isinstance(verification, dict):
        checks.append(
            VerificationCheck(
                type="release_trust_verification_summary",
                status="failed",
                message="verification must be an object",
            )
        )
        return
    commands = verification.get("commands")
    failures: list[str] = []
    if verification.get("status") != "passed":
        failures.append(f"verification status {verification.get('status')!r} is not passed")
    if not isinstance(commands, list) or not commands:
        failures.append("verification commands must be a non-empty list")
    elif any(not isinstance(item, dict) or item.get("status") != "passed" or not item.get("command") for item in commands):
        failures.append("all verification commands must have command text and passed status")
    checks.append(
        VerificationCheck(
            type="release_trust_verification_summary",
            status="failed" if failures else "passed",
            message="; ".join(failures) if failures else "verification command summary is passed",
        )
    )


def _check_sbom_boundary(manifest: dict[str, Any], checks: list[VerificationCheck]) -> None:
    sbom = manifest.get("sbom")
    if not isinstance(sbom, dict):
        checks.append(
            VerificationCheck(
                type="release_trust_sbom_boundary",
                status="failed",
                message="sbom must be an object",
            )
        )
        return
    sbom_format = sbom.get("format")
    status = sbom.get("status")
    reason = sbom.get("reason")
    failures: list[str] = []
    if sbom_format == "none" and status == "not_generated" and reason:
        pass
    elif sbom_format in {"cyclonedx", "spdx"} and status == "generated" and sbom.get("sha256"):
        pass
    else:
        failures.append(f"unsupported SBOM boundary shape: format={sbom_format!r}, status={status!r}")
    checks.append(
        VerificationCheck(
            type="release_trust_sbom_boundary",
            status="failed" if failures else "passed",
            message="; ".join(failures) if failures else f"SBOM boundary {sbom_format!r}/{status!r} is supported",
        )
    )


def _run_git(args: list[str], cwd: str | Path | None) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
