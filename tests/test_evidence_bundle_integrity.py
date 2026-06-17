import hashlib
import json
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path
from typing import Callable

from ai_infra import (
    build_run_report,
    export_evidence_bundle,
    get_run,
    load_workflow,
    run_workflow,
    verify_evidence_bundle,
)
from ai_infra.store import RunStore


def run_cli(*args, state_dir):
    return subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_exported_bundle_manifest_contains_file_digests_and_sdk_verifies_offline(tmp_path):
    bundle_path, run_id = _export_artifact_bundle(tmp_path)

    with zipfile.ZipFile(bundle_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        files = {item["path"]: item for item in manifest["files"]}
        names = set(archive.namelist())

        assert manifest["schema_version"] == "1"
        assert manifest["bundle_type"] == "ai_infra.evidence_bundle"
        assert manifest["run_id"] == run_id
        assert manifest["workflow_id"] == "artifact-workflow"
        assert manifest["provenance_summary"]["workflow_sha256"]
        assert manifest["compatibility_summary"]["status"] == "supported"
        assert manifest["compatibility_summary"]["schema_version"]["declared"] == "1"
        assert "workflow_snapshot" not in manifest["provenance_summary"]
        assert manifest["redaction_summary"] == {"redacted_nodes": 0, "redacted_values": 0}
        assert manifest["verification_input_summary"] == {
            "type": "object",
            "keys": ["artifact_path", "topic"],
        }
        assert {
            "report.json",
            "inputs.json",
            "events.json",
            "workflow_snapshot.yaml",
            "artifacts/write_note/note/note.txt",
        }.issubset(files)
        assert set(files).issubset(names)
        for name, item in files.items():
            data = archive.read(name)
            assert item["size_bytes"] == len(data)
            assert item["sha256"] == hashlib.sha256(data).hexdigest()

    verification = verify_evidence_bundle(bundle_path)

    assert verification.run_id == run_id
    assert verification.status == "passed"
    assert all(check.status == "passed" for check in verification.checks)
    assert {check.type for check in verification.checks} >= {
        "bundle_manifest",
        "bundle_required_file",
        "bundle_file_coverage",
        "bundle_file_digest",
        "bundle_json",
        "bundle_yaml",
        "bundle_document_schema",
        "bundle_run_identity",
        "bundle_manifest_summary",
        "bundle_redaction",
    }


def test_verify_evidence_bundle_detects_tampered_file_content(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    tampered = tmp_path / "tampered.zip"
    _rewrite_bundle(bundle_path, tampered, {"report.json": b'{"run_id":"tampered"}'})

    verification = verify_evidence_bundle(tampered)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_file_digest"
        and check.status == "failed"
        and "report.json" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_unmanifested_extra_file(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    extra = tmp_path / "extra-file.zip"
    _rewrite_bundle(bundle_path, extra, {"unmanifested.txt": b"not covered by manifest"})

    verification = verify_evidence_bundle(extra)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_file_coverage"
        and check.status == "failed"
        and "unmanifested.txt" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_duplicate_zip_entry(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    duplicate = tmp_path / "duplicate-entry.zip"
    _rewrite_bundle(bundle_path, duplicate, {"report.json": b'{"run_id":"duplicate"}'}, append=True)

    verification = verify_evidence_bundle(duplicate)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_file_coverage"
        and check.status == "failed"
        and "duplicate" in check.message
        and "report.json" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_missing_required_file(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    missing = tmp_path / "missing-events.zip"
    _rewrite_bundle(bundle_path, missing, {}, omit={"events.json"})

    verification = verify_evidence_bundle(missing)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_required_file"
        and check.status == "failed"
        and "events.json" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_malformed_json_after_manifest_refresh(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    malformed = tmp_path / "malformed-json.zip"
    _rewrite_bundle(bundle_path, malformed, {"events.json": b'{"not valid"'}, refresh_manifest=True)

    verification = verify_evidence_bundle(malformed)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_json"
        and check.status == "failed"
        and "events.json" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_wrong_document_shapes_after_manifest_refresh(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    malformed = tmp_path / "wrong-document-shapes.zip"
    _rewrite_bundle(
        bundle_path,
        malformed,
        {
            "report.json": b"[]",
            "inputs.json": b"[]",
            "events.json": b"{}",
            "workflow_snapshot.yaml": b"[]",
        },
        refresh_manifest=True,
    )

    verification = verify_evidence_bundle(malformed)

    assert verification.status == "failed"
    failed_messages = [
        check.message
        for check in verification.checks
        if check.type == "bundle_document_schema" and check.status == "failed"
    ]
    assert any("report.json" in message and "object" in message for message in failed_messages)
    assert any("inputs.json" in message and "object" in message for message in failed_messages)
    assert any("events.json" in message and "array" in message for message in failed_messages)
    assert any("workflow_snapshot.yaml" in message and "object" in message for message in failed_messages)


def test_verify_evidence_bundle_detects_malformed_yaml_after_manifest_refresh(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    malformed = tmp_path / "malformed-yaml.zip"
    _rewrite_bundle(
        bundle_path,
        malformed,
        {"workflow_snapshot.yaml": b"id: [unterminated"},
        refresh_manifest=True,
    )

    verification = verify_evidence_bundle(malformed)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_yaml"
        and check.status == "failed"
        and "workflow_snapshot.yaml" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_uses_redaction_metadata_when_snapshot_paths_are_removed(
    tmp_path,
    monkeypatch,
):
    bundle_path, _run_id = _export_redaction_bundle(tmp_path, monkeypatch)
    leaked = tmp_path / "redaction-leak-without-snapshot-paths.zip"

    def remove_snapshot_paths(data: bytes) -> bytes:
        snapshot = data.decode("utf-8")
        return snapshot.replace(
            """governance:
  required_env:
  - AI_INFRA_TEST_TOKEN
  sensitive_paths:
  - inputs.api_key
  - node_output.secret_echo.result
  - tool_invocation.secret_echo.input.args.value
""".encode("utf-8").decode("utf-8"),
            """governance:
  required_env:
  - AI_INFRA_TEST_TOKEN
""",
        ).encode("utf-8")

    def leak_input(data: bytes) -> bytes:
        payload = json.loads(data)
        payload["api_key"] = "DEMO_INPUT_SECRET"
        return _json_bytes(payload)

    _rewrite_bundle(
        bundle_path,
        leaked,
        {
            "workflow_snapshot.yaml": remove_snapshot_paths,
            "inputs.json": leak_input,
        },
        refresh_manifest=True,
    )

    verification = verify_evidence_bundle(leaked)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_redaction"
        and check.status == "failed"
        and "inputs.api_key" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_fails_when_redaction_summary_has_no_path_source(
    tmp_path,
    monkeypatch,
):
    bundle_path, _run_id = _export_redaction_bundle(tmp_path, monkeypatch)
    ambiguous = tmp_path / "redaction-without-path-source.zip"

    def remove_snapshot_paths(data: bytes) -> bytes:
        snapshot = data.decode("utf-8")
        return snapshot.replace(
            """governance:
  required_env:
  - AI_INFRA_TEST_TOKEN
  sensitive_paths:
  - inputs.api_key
  - node_output.secret_echo.result
  - tool_invocation.secret_echo.input.args.value
""".encode("utf-8").decode("utf-8"),
            """governance:
  required_env:
  - AI_INFRA_TEST_TOKEN
""",
        ).encode("utf-8")

    def remove_event_paths(data: bytes) -> bytes:
        events = json.loads(data)
        for event in events:
            redaction = event.get("metadata", {}).get("redaction")
            if isinstance(redaction, dict):
                redaction["paths"] = []
        return _json_bytes(events)

    def remove_report_paths(data: bytes) -> bytes:
        report = json.loads(data)
        for node in report.get("timeline", []):
            redaction = node.get("redaction")
            if isinstance(redaction, dict):
                redaction["paths"] = []
        return _json_bytes(report)

    _rewrite_bundle(
        bundle_path,
        ambiguous,
        {
            "workflow_snapshot.yaml": remove_snapshot_paths,
            "events.json": remove_event_paths,
            "report.json": remove_report_paths,
        },
        refresh_manifest=True,
    )

    verification = verify_evidence_bundle(ambiguous)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_redaction"
        and check.status == "failed"
        and "no sensitive path source" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_manifest_run_mismatch(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    mismatched = tmp_path / "run-mismatch.zip"

    def change_manifest(data: bytes) -> bytes:
        manifest = json.loads(data)
        manifest["run_id"] = "run-mismatched"
        return _json_bytes(manifest)

    _rewrite_bundle(mismatched_source := bundle_path, mismatched, {"manifest.json": change_manifest})

    verification = verify_evidence_bundle(mismatched)

    assert mismatched_source.exists()
    assert verification.status == "failed"
    assert any(
        check.type == "bundle_run_identity"
        and check.status == "failed"
        and "run-mismatched" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_manifest_status_summary_mismatch(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    mismatched = tmp_path / "status-summary-mismatch.zip"

    def change_manifest(data: bytes) -> bytes:
        manifest = json.loads(data)
        manifest["status"] = "failed"
        return _json_bytes(manifest)

    _rewrite_bundle(bundle_path, mismatched, {"manifest.json": change_manifest})

    verification = verify_evidence_bundle(mismatched)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_manifest_summary"
        and check.status == "failed"
        and "status" in check.message
        and "report.json" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_manifest_redaction_summary_mismatch(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    mismatched = tmp_path / "redaction-summary-mismatch.zip"

    def change_manifest(data: bytes) -> bytes:
        manifest = json.loads(data)
        manifest["redaction_summary"] = {"redacted_nodes": 1, "redacted_values": 1}
        return _json_bytes(manifest)

    _rewrite_bundle(bundle_path, mismatched, {"manifest.json": change_manifest})

    verification = verify_evidence_bundle(mismatched)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_manifest_summary"
        and check.status == "failed"
        and "redaction_summary" in check.message
        and "report.json" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_reports_malformed_report_redaction_summary(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    malformed = tmp_path / "malformed-redaction-summary.zip"

    def change_report(data: bytes) -> bytes:
        report = json.loads(data)
        report["summary"]["redaction"] = {
            "redacted_nodes": "not-int",
            "redacted_values": 0,
        }
        return _json_bytes(report)

    _rewrite_bundle(bundle_path, malformed, {"report.json": change_report}, refresh_manifest=True)

    verification = verify_evidence_bundle(malformed)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_manifest_summary"
        and check.status == "failed"
        and "redaction_summary" in check.message
        and "invalid" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_manifest_input_summary_mismatch(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    mismatched = tmp_path / "input-summary-mismatch.zip"

    def change_manifest(data: bytes) -> bytes:
        manifest = json.loads(data)
        manifest["verification_input_summary"] = {"type": "object", "keys": ["topic"]}
        return _json_bytes(manifest)

    _rewrite_bundle(bundle_path, mismatched, {"manifest.json": change_manifest})

    verification = verify_evidence_bundle(mismatched)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_manifest_summary"
        and check.status == "failed"
        and "verification_input_summary" in check.message
        and "inputs.json" in check.message
        for check in verification.checks
    )


def test_verify_evidence_bundle_detects_redaction_sensitive_path_leak_after_manifest_refresh(tmp_path, monkeypatch):
    bundle_path, _run_id = _export_redaction_bundle(tmp_path, monkeypatch)
    leaked = tmp_path / "redaction-leak.zip"

    def leak_input(data: bytes) -> bytes:
        payload = json.loads(data)
        payload["api_key"] = "DEMO_INPUT_SECRET"
        return _json_bytes(payload)

    _rewrite_bundle(bundle_path, leaked, {"inputs.json": leak_input}, refresh_manifest=True)

    verification = verify_evidence_bundle(leaked)

    assert verification.status == "failed"
    assert any(
        check.type == "bundle_redaction"
        and check.status == "failed"
        and "inputs.api_key" in check.message
        for check in verification.checks
    )


def test_cli_verify_bundle_reports_success_and_failure_without_state_store(tmp_path):
    bundle_path, run_id = _export_artifact_bundle(tmp_path)
    detached_state_dir = tmp_path / "detached-state"

    verify = run_cli("verify-bundle", str(bundle_path), state_dir=detached_state_dir)

    assert verify.returncode == 0
    assert detached_state_dir.exists() is False
    payload = json.loads(verify.stdout)
    assert payload["ok"] is True
    assert payload["verification"]["run_id"] == run_id
    assert payload["verification"]["status"] == "passed"

    tampered = tmp_path / "tampered-cli.zip"
    _rewrite_bundle(bundle_path, tampered, {"report.json": b'{"run_id":"tampered"}'})
    failed = run_cli("verify-bundle", str(tampered), state_dir=detached_state_dir)

    assert failed.returncode == 1
    assert detached_state_dir.exists() is False
    failed_payload = json.loads(failed.stdout)
    assert failed_payload["ok"] is False
    assert failed_payload["verification"]["status"] == "failed"


def test_cli_verify_bundle_reports_manifest_summary_mismatch_without_state_store(tmp_path):
    bundle_path, _run_id = _export_artifact_bundle(tmp_path)
    detached_state_dir = tmp_path / "detached-state"
    mismatched = tmp_path / "cli-status-summary-mismatch.zip"

    def change_manifest(data: bytes) -> bytes:
        manifest = json.loads(data)
        manifest["status"] = "failed"
        return _json_bytes(manifest)

    _rewrite_bundle(bundle_path, mismatched, {"manifest.json": change_manifest})

    failed = run_cli("verify-bundle", str(mismatched), state_dir=detached_state_dir)

    assert failed.returncode == 1
    assert detached_state_dir.exists() is False
    payload = json.loads(failed.stdout)
    assert payload["ok"] is False
    assert any(
        check["type"] == "bundle_manifest_summary"
        and check["status"] == "failed"
        and "status" in check["message"]
        for check in payload["verification"]["checks"]
    )


def _export_artifact_bundle(tmp_path: Path) -> tuple[Path, str]:
    store = RunStore(tmp_path / "state" / "runs.sqlite")
    artifact_path = tmp_path / "artifacts" / "note.txt"
    workflow = load_workflow(Path("examples/artifact_workflow.yaml"))
    result = run_workflow(
        workflow,
        {"topic": "ABH", "artifact_path": artifact_path.as_posix()},
        store=store,
    )
    report = build_run_report(result.run_id, store=store)
    run = get_run(result.run_id, store=store)
    bundle = export_evidence_bundle(run, report, tmp_path / "bundles")
    return Path(bundle.path), result.run_id


def _export_redaction_bundle(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    monkeypatch.setenv("AI_INFRA_TEST_TOKEN", "DEMO_ENV_SECRET")
    store = RunStore(tmp_path / "state" / "runs.sqlite")
    workflow = load_workflow(Path("examples/redaction_workflow.yaml"))
    result = run_workflow(workflow, {"api_key": "DEMO_INPUT_SECRET"}, store=store)
    report = build_run_report(result.run_id, store=store)
    run = get_run(result.run_id, store=store)
    bundle = export_evidence_bundle(run, report, tmp_path / "bundles")
    return Path(bundle.path), result.run_id


def _rewrite_bundle(
    source: Path,
    target: Path,
    replacements: dict[str, bytes | Callable[[bytes], bytes]],
    *,
    omit: set[str] | None = None,
    refresh_manifest: bool = False,
    append: bool = False,
) -> None:
    omit = omit or set()
    with zipfile.ZipFile(source) as archive:
        entries = {
            name: archive.read(name)
            for name in archive.namelist()
            if name not in omit
    }
    for name, replacement in replacements.items():
        current = entries.get(name, b"")
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
    mode = "a" if append else "w"
    if append:
        target.write_bytes(source.read_bytes())
    with zipfile.ZipFile(target, mode, compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            if append and name not in replacements:
                continue
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Duplicate name:*", category=UserWarning)
                archive.writestr(name, entries[name])


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
