from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ai_infra.release_trust import (
    build_release_trust_manifest,
    current_source_commit,
    current_tree_state,
    default_build_environment,
    verify_release_trust_manifest,
    write_release_trust_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-release-trust-") as temp:
        temp_root = Path(temp)
        dist_dir = temp_root / "dist"
        manifest_path = temp_root / "release-trust-manifest.json"

        _run([_uv(), "build", "--out-dir", str(dist_dir)], cwd=ROOT)
        wheel = _single_artifact(dist_dir, "*.whl")
        sdist = _single_artifact(dist_dir, "*.tar.gz")

        source_commit = current_source_commit(ROOT) or "unknown"
        manifest = build_release_trust_manifest(
            [wheel, sdist],
            source_commit=source_commit,
            tree_state=current_tree_state(ROOT),
            build_environment=default_build_environment(),
            verification_commands=[
                {"command": "uv build", "status": "passed"},
                {"command": "uv run python scripts/verify_release_installability.py", "status": "passed"},
                {"command": "uv run pytest -q", "status": "passed"},
            ],
            sbom={
                "format": "none",
                "status": "not_generated",
                "reason": "SBOM generation is reserved as a future release-hardening phase; this phase records the boundary explicitly.",
            },
        )
        write_release_trust_manifest(manifest, manifest_path)

        clean = verify_release_trust_manifest(
            manifest_path,
            artifact_dir=dist_dir,
            expected_source_commit=source_commit,
        )
        _assert(clean.status == "passed", f"clean release trust manifest should pass: {asdict(clean)}")

        checks = {
            "clean": clean.status,
            "tampered_artifact": _verify_tampered_artifact(temp_root, manifest_path, wheel, sdist),
            "missing_artifact": _verify_missing_artifact(temp_root, manifest_path, wheel, sdist),
            "package_metadata_mismatch": _verify_package_metadata_mismatch(temp_root, manifest_path, wheel, sdist),
            "source_commit_mismatch": _verify_source_commit_mismatch(manifest_path, dist_dir),
            "unsupported_sbom_boundary": _verify_unsupported_sbom_boundary(temp_root, manifest_path, dist_dir),
        }
        payload = {
            "ok": True,
            "manifest": str(manifest_path),
            "artifacts": {
                "wheel": wheel.name,
                "sdist": sdist.name,
            },
            "source_commit": source_commit,
            "checks": checks,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0


def _verify_tampered_artifact(temp_root: Path, manifest_path: Path, wheel: Path, sdist: Path) -> str:
    tampered_dir = temp_root / "tampered-artifact"
    tampered_dir.mkdir()
    tampered_wheel = tampered_dir / wheel.name
    tampered_sdist = tampered_dir / sdist.name
    tampered_wheel.write_bytes(wheel.read_bytes() + b"\ntampered_artifact")
    shutil.copy2(sdist, tampered_sdist)
    verification = verify_release_trust_manifest(manifest_path, artifact_dir=tampered_dir)
    _assert_failed_check(verification, "release_trust_artifact_digest", wheel.name)
    return verification.status


def _verify_missing_artifact(temp_root: Path, manifest_path: Path, wheel: Path, sdist: Path) -> str:
    missing_dir = temp_root / "missing-artifact"
    missing_dir.mkdir()
    shutil.copy2(wheel, missing_dir / wheel.name)
    verification = verify_release_trust_manifest(manifest_path, artifact_dir=missing_dir)
    _assert_failed_check(verification, "release_trust_artifact_digest", sdist.name)
    return verification.status


def _verify_package_metadata_mismatch(temp_root: Path, manifest_path: Path, wheel: Path, sdist: Path) -> str:
    mismatch_dir = temp_root / "package-mismatch"
    mismatch_dir.mkdir()
    shutil.copy2(wheel, mismatch_dir / wheel.name)
    shutil.copy2(sdist, mismatch_dir / sdist.name)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package"]["version"] = "999.999.999"
    mismatch_manifest = temp_root / "package-mismatch-manifest.json"
    mismatch_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    verification = verify_release_trust_manifest(mismatch_manifest, artifact_dir=mismatch_dir)
    _assert_failed_check(verification, "release_trust_package_metadata", "999.999.999")
    return verification.status


def _verify_source_commit_mismatch(manifest_path: Path, dist_dir: Path) -> str:
    verification = verify_release_trust_manifest(
        manifest_path,
        artifact_dir=dist_dir,
        expected_source_commit="not-the-release-commit",
    )
    _assert_failed_check(verification, "release_trust_source", "not-the-release-commit")
    return verification.status


def _verify_unsupported_sbom_boundary(temp_root: Path, manifest_path: Path, dist_dir: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sbom"] = {
        "format": "cyclonedx",
        "status": "not_generated",
        "reason": "unsupported_sbom_boundary",
    }
    sbom_manifest = temp_root / "unsupported-sbom-manifest.json"
    sbom_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    verification = verify_release_trust_manifest(sbom_manifest, artifact_dir=dist_dir)
    _assert_failed_check(verification, "release_trust_sbom_boundary", "unsupported")
    return verification.status


def _assert_failed_check(verification: Any, check_type: str, message_fragment: str) -> None:
    _assert(verification.status == "failed", f"{check_type} scenario should fail: {asdict(verification)}")
    if not any(
        check.type == check_type
        and check.status == "failed"
        and message_fragment in check.message
        for check in verification.checks
    ):
        raise AssertionError(f"missing failed {check_type} check containing {message_fragment!r}: {asdict(verification)}")


def _single_artifact(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    _assert(len(matches) == 1, f"expected exactly one {pattern} artifact in {dist_dir}, found {matches}")
    return matches[0]


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(command)}\n"
            f"cwd={cwd}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    return result


def _uv() -> str:
    executable = os.environ.get("UV")
    if executable:
        return executable
    return "uv"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
