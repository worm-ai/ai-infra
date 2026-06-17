from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SECRET = "DEMO_INPUT_SECRET"
ENV_SECRET = "DEMO_ENV_SECRET"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-bundle-integrity-") as temp:
        temp_root = Path(temp)
        state_dir = temp_root / "state"
        detached_state_dir = temp_root / "detached-state"
        bundle_dir = temp_root / "bundles"

        bundle = _export_artifact_bundle(state_dir, bundle_dir, temp_root)
        bundle_path = Path(str(bundle["path"]))

        success = _run_cli({}, detached_state_dir, "verify-bundle", str(bundle_path))
        success_payload = _assert_ok(success, "verify-bundle success")
        _assert(success_payload["verification"]["status"] == "passed", "clean bundle should verify")
        _assert(not detached_state_dir.exists(), "offline bundle verification should not create SQLite state")

        tampered = temp_root / "tampered.zip"
        _rewrite_bundle(bundle_path, tampered, {"report.json": b'{"run_id":"tampered"}'})
        tampered_result = _run_cli({}, detached_state_dir, "verify-bundle", str(tampered))
        tampered_payload = _assert_failed(tampered_result, "verify-bundle tampered")
        _assert_has_failed_check(tampered_payload, "bundle_file_digest", "report.json")

        missing = temp_root / "missing-events.zip"
        _rewrite_bundle(bundle_path, missing, {}, omit={"events.json"})
        missing_result = _run_cli({}, detached_state_dir, "verify-bundle", str(missing))
        missing_payload = _assert_failed(missing_result, "verify-bundle missing")
        _assert_has_failed_check(missing_payload, "bundle_required_file", "events.json")

        wrong_shape = temp_root / "wrong-document-shapes.zip"
        _rewrite_bundle(
            bundle_path,
            wrong_shape,
            {
                "report.json": b"[]",
                "inputs.json": b"[]",
                "events.json": b"{}",
                "workflow_snapshot.yaml": b"[]",
            },
            refresh_manifest=True,
        )
        wrong_shape_result = _run_cli({}, detached_state_dir, "verify-bundle", str(wrong_shape))
        wrong_shape_payload = _assert_failed(wrong_shape_result, "verify-bundle wrong document shapes")
        _assert_has_failed_check(wrong_shape_payload, "bundle_document_schema", "report.json")

        status_summary_mismatch = temp_root / "status-summary-mismatch.zip"
        _rewrite_bundle(
            bundle_path,
            status_summary_mismatch,
            {"manifest.json": _tamper_manifest_status},
        )
        status_summary_result = _run_cli({}, detached_state_dir, "verify-bundle", str(status_summary_mismatch))
        status_summary_payload = _assert_failed(
            status_summary_result,
            "verify-bundle status summary mismatch",
        )
        _assert_has_failed_check(status_summary_payload, "bundle_manifest_summary", "status")

        redaction_summary_mismatch = temp_root / "redaction-summary-mismatch.zip"
        _rewrite_bundle(
            bundle_path,
            redaction_summary_mismatch,
            {"manifest.json": _tamper_manifest_redaction_summary},
        )
        redaction_summary_result = _run_cli({}, detached_state_dir, "verify-bundle", str(redaction_summary_mismatch))
        redaction_summary_payload = _assert_failed(
            redaction_summary_result,
            "verify-bundle redaction summary mismatch",
        )
        _assert_has_failed_check(redaction_summary_payload, "bundle_manifest_summary", "redaction_summary")

        input_summary_mismatch = temp_root / "input-summary-mismatch.zip"
        _rewrite_bundle(
            bundle_path,
            input_summary_mismatch,
            {"manifest.json": _tamper_manifest_input_summary},
        )
        input_summary_result = _run_cli({}, detached_state_dir, "verify-bundle", str(input_summary_mismatch))
        input_summary_payload = _assert_failed(
            input_summary_result,
            "verify-bundle input summary mismatch",
        )
        _assert_has_failed_check(input_summary_payload, "bundle_manifest_summary", "verification_input_summary")

        malformed_redaction_summary = temp_root / "malformed-redaction-summary.zip"
        _rewrite_bundle(
            bundle_path,
            malformed_redaction_summary,
            {"report.json": _tamper_report_malformed_redaction_summary},
            refresh_manifest=True,
        )
        malformed_redaction_result = _run_cli({}, detached_state_dir, "verify-bundle", str(malformed_redaction_summary))
        malformed_redaction_payload = _assert_failed(
            malformed_redaction_result,
            "verify-bundle malformed redaction summary",
        )
        _assert_has_failed_check(malformed_redaction_payload, "bundle_manifest_summary", "invalid")

        redaction_bundle = _export_redaction_bundle(state_dir, bundle_dir)
        leaked = temp_root / "redaction-leak.zip"
        _rewrite_bundle(
            Path(str(redaction_bundle["path"])),
            leaked,
            {"inputs.json": _leak_secret_input},
            refresh_manifest=True,
        )
        leak_result = _run_cli({}, detached_state_dir, "verify-bundle", str(leaked))
        leak_payload = _assert_failed(leak_result, "verify-bundle redaction leak")
        _assert_has_failed_check(leak_payload, "bundle_redaction", "inputs.api_key")

        metadata_leak = temp_root / "redaction-metadata-leak.zip"
        _rewrite_bundle(
            Path(str(redaction_bundle["path"])),
            metadata_leak,
            {
                "workflow_snapshot.yaml": _remove_snapshot_sensitive_paths,
                "inputs.json": _leak_secret_input,
            },
            refresh_manifest=True,
        )
        metadata_leak_result = _run_cli({}, detached_state_dir, "verify-bundle", str(metadata_leak))
        metadata_leak_payload = _assert_failed(metadata_leak_result, "verify-bundle redaction metadata leak")
        _assert_has_failed_check(metadata_leak_payload, "bundle_redaction", "inputs.api_key")

        payload = {
            "ok": True,
            "bundle": str(bundle_path),
            "run_id": success_payload["verification"]["run_id"],
            "checks": {
                "success": success_payload["verification"]["status"],
                "tampered": tampered_payload["verification"]["status"],
                "missing": missing_payload["verification"]["status"],
                "wrong_shape": wrong_shape_payload["verification"]["status"],
                "status_summary_mismatch": status_summary_payload["verification"]["status"],
                "redaction_summary_mismatch": redaction_summary_payload["verification"]["status"],
                "input_summary_mismatch": input_summary_payload["verification"]["status"],
                "malformed_redaction_summary": malformed_redaction_payload["verification"]["status"],
                "redaction_leak": leak_payload["verification"]["status"],
                "redaction_metadata_leak": metadata_leak_payload["verification"]["status"],
            },
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0


def _export_artifact_bundle(state_dir: Path, bundle_dir: Path, temp_root: Path) -> dict[str, Any]:
    artifact_path = temp_root / "artifacts" / "note.txt"
    input_path = temp_root / "artifact_input.json"
    input_path.write_text(
        json.dumps({"topic": "ABH", "artifact_path": artifact_path.as_posix()}),
        encoding="utf-8",
    )

    validate = _run_cli({}, state_dir, "validate", "examples/artifact_workflow.yaml")
    _assert_ok(validate, "validate artifact workflow")
    run = _run_cli(
        {},
        state_dir,
        "run",
        "examples/artifact_workflow.yaml",
        "--input-file",
        str(input_path),
    )
    run_payload = _assert_ok(run, "run artifact workflow")
    run_id = str(run_payload["run"]["run_id"])
    export = _run_cli({}, state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))
    return _assert_ok(export, "export artifact bundle")["bundle"]


def _export_redaction_bundle(state_dir: Path, bundle_dir: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env["AI_INFRA_TEST_TOKEN"] = ENV_SECRET
    validate = _run_cli(env, state_dir, "validate", "examples/redaction_workflow.yaml")
    _assert_ok(validate, "validate redaction workflow")
    run = _run_cli(
        env,
        state_dir,
        "run",
        "examples/redaction_workflow.yaml",
        "--input-file",
        "examples/redaction_input.json",
    )
    run_payload = _assert_ok(run, "run redaction workflow")
    run_id = str(run_payload["run"]["run_id"])
    export = _run_cli(env, state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))
    return _assert_ok(export, "export redaction bundle")["bundle"]


def _run_cli(env: dict[str, str], state_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command_env = dict(os.environ)
    command_env.update(env)
    command = [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=command_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout.strip():
        return result
    if result.returncode in {-1073740940, -1073741819}:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=command_env,
            text=True,
            capture_output=True,
            check=False,
        )
    return result


def _assert_ok(result: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    payload = _json_payload(result, label)
    if result.returncode != 0 or payload.get("ok") is not True:
        raise AssertionError(
            f"{label} failed: code={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return payload


def _assert_failed(result: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    payload = _json_payload(result, label)
    if result.returncode != 1 or payload.get("ok") is not False:
        raise AssertionError(
            f"{label} should fail verification: code={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return payload


def _json_payload(result: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"{label} did not emit JSON: code={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        ) from exc


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_has_failed_check(payload: dict[str, Any], check_type: str, message_fragment: str) -> None:
    checks = payload["verification"]["checks"]
    if not any(
        check["type"] == check_type
        and check["status"] == "failed"
        and message_fragment in check["message"]
        for check in checks
    ):
        raise AssertionError(f"missing failed {check_type} check containing {message_fragment!r}: {checks!r}")


def _rewrite_bundle(
    source: Path,
    target: Path,
    replacements: dict[str, bytes | Callable[[bytes], bytes]],
    *,
    omit: set[str] | None = None,
    refresh_manifest: bool = False,
) -> None:
    omit = omit or set()
    with zipfile.ZipFile(source) as archive:
        entries = {
            name: archive.read(name)
            for name in archive.namelist()
            if name not in omit
        }
    for name, replacement in replacements.items():
        current = entries[name]
        entries[name] = replacement(current) if callable(replacement) else replacement
    if refresh_manifest:
        manifest = json.loads(entries["manifest.json"])
        for item in manifest["files"]:
            name = item["path"]
            if name not in entries:
                continue
            item["size_bytes"] = len(entries[name])
            item["sha256"] = hashlib.sha256(entries[name]).hexdigest()
        entries["manifest.json"] = _json_bytes(manifest)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])


def _leak_secret_input(data: bytes) -> bytes:
    payload = json.loads(data)
    payload["api_key"] = SECRET
    return _json_bytes(payload)


def _remove_snapshot_sensitive_paths(data: bytes) -> bytes:
    snapshot = data.decode("utf-8")
    return snapshot.replace(
        """governance:
  required_env:
  - AI_INFRA_TEST_TOKEN
  sensitive_paths:
  - inputs.api_key
  - node_output.secret_echo.result
  - tool_invocation.secret_echo.input.args.value
""",
        """governance:
  required_env:
  - AI_INFRA_TEST_TOKEN
""",
    ).encode("utf-8")


def _tamper_manifest_status(data: bytes) -> bytes:
    manifest = json.loads(data)
    manifest["status"] = "failed"
    return _json_bytes(manifest)


def _tamper_manifest_redaction_summary(data: bytes) -> bytes:
    manifest = json.loads(data)
    manifest["redaction_summary"] = {"redacted_nodes": 1, "redacted_values": 1}
    return _json_bytes(manifest)


def _tamper_manifest_input_summary(data: bytes) -> bytes:
    manifest = json.loads(data)
    manifest["verification_input_summary"] = {"type": "object", "keys": ["topic"]}
    return _json_bytes(manifest)


def _tamper_report_malformed_redaction_summary(data: bytes) -> bytes:
    report = json.loads(data)
    report["summary"]["redaction"] = {
        "redacted_nodes": "not-int",
        "redacted_values": 0,
    }
    return _json_bytes(report)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
