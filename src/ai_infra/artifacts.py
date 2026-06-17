from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .snapshots import redacted_workflow_snapshot
from .store import NodeEvent, StoredRun, VerificationCheck
from .tools import _render_template


BUNDLE_SCHEMA_VERSION = "1"
BUNDLE_TYPE = "ai_infra.evidence_bundle"
REDACTION_MARKER = "[REDACTED]"
STANDARD_BUNDLE_FILES = ("report.json", "inputs.json", "events.json", "workflow_snapshot.yaml")


@dataclass(frozen=True)
class EvidenceBundle:
    run_id: str
    path: str
    artifacts: list[dict[str, Any]]


@dataclass(frozen=True)
class EvidenceBundleVerification:
    run_id: str
    status: str
    checks: list[VerificationCheck]


def collect_node_artifacts(
    artifact_configs: Any,
    context: dict[str, Any],
    *,
    run_id: str,
    node_id: str,
    state_dir: Path | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(artifact_configs, list):
        return []
    evidence: list[dict[str, Any]] = []
    for config in artifact_configs:
        if not isinstance(config, dict):
            continue
        name = str(config.get("name", ""))
        declared_path = str(config.get("path", ""))
        content_type = str(config.get("content_type", ""))
        rendered_path = _render_template(declared_path, context)
        path = Path(rendered_path)
        item: dict[str, Any] = {
            "name": name,
            "path": path.as_posix(),
            "content_type": content_type,
            "exists": path.exists() and path.is_file(),
        }
        if item["exists"]:
            data = path.read_bytes()
            item["size_bytes"] = len(data)
            item["sha256"] = hashlib.sha256(data).hexdigest()
            if state_dir is not None:
                stored_path = _stored_artifact_path(state_dir, run_id, node_id, name, path)
                stored_path.parent.mkdir(parents=True, exist_ok=True)
                stored_path.write_bytes(data)
                item["stored_path"] = stored_path.as_posix()
        evidence.append(item)
    return evidence


def latest_node_artifacts(run: StoredRun, node_id: str) -> list[dict[str, Any]]:
    for event in reversed(run.events):
        if event.node_id != node_id:
            continue
        return event_artifacts(event)
    return []


def event_artifacts(event: NodeEvent) -> list[dict[str, Any]]:
    artifacts = event.metadata.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    return [dict(item) for item in artifacts if isinstance(item, dict)]


def find_artifact(
    artifacts: list[dict[str, Any]],
    name: str,
) -> dict[str, Any] | None:
    for artifact in artifacts:
        if artifact.get("name") == name:
            return artifact
    return None


def current_file_sha256(path: str) -> str | None:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def export_evidence_bundle(
    run: StoredRun,
    report: dict[str, Any],
    output_dir: str | Path,
) -> EvidenceBundle:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    bundle_path = output_root / f"{run.run_id}-evidence-bundle.zip"
    manifest_artifacts: list[dict[str, Any]] = []
    entries: dict[str, bytes] = {
        "report.json": _json_bytes(report),
        "inputs.json": _json_bytes(run.inputs),
        "events.json": _json_bytes([asdict(event) for event in run.events]),
        "workflow_snapshot.yaml": (
            redacted_workflow_snapshot(run.provenance.workflow_snapshot).encode("utf-8")
            if run.provenance is not None
            else b""
        ),
    }

    for event in run.events:
        for artifact in event_artifacts(event):
            manifest_artifact = dict(artifact)
            manifest_artifact["node_id"] = event.node_id
            archive_path = _artifact_archive_path(event.node_id, artifact)
            manifest_artifact["archive_path"] = archive_path
            artifact_path = Path(str(artifact.get("stored_path") or artifact.get("path", "")))
            if artifact_path.exists() and artifact_path.is_file():
                entries[archive_path] = artifact_path.read_bytes()
            manifest_artifacts.append(manifest_artifact)

    manifest = _bundle_manifest(run, report, manifest_artifacts, entries)
    entries["manifest.json"] = _json_bytes(manifest)

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in _bundle_write_order(entries):
            archive.writestr(name, entries[name])

    return EvidenceBundle(
        run_id=run.run_id,
        path=str(bundle_path),
        artifacts=manifest_artifacts,
    )


def verify_evidence_bundle(bundle_path: str | Path) -> EvidenceBundleVerification:
    checks: list[VerificationCheck] = []
    manifest: dict[str, Any] | None = None
    names: set[str] = set()
    documents: dict[str, Any] = {}

    try:
        with zipfile.ZipFile(bundle_path) as archive:
            all_names = archive.namelist()
            names = set(all_names)
            manifest = _read_manifest(archive, checks)
            _check_required_files(names, checks)
            _check_file_coverage(manifest, all_names, checks)
            _check_manifest_files(archive, manifest, names, checks)
            documents = _parse_bundle_documents(archive, names, checks)
            _check_document_schema(documents, checks)
    except (OSError, zipfile.BadZipFile) as exc:
        checks.append(
            VerificationCheck(
                type="bundle_archive",
                status="failed",
                message=f"bundle archive is unreadable: {exc}",
            )
        )

    _check_run_identity(manifest, documents, checks)
    _check_redaction(manifest, documents, checks)
    status = "passed" if checks and all(check.status == "passed" for check in checks) else "failed"
    run_id = str(manifest.get("run_id", "")) if isinstance(manifest, dict) else ""
    return EvidenceBundleVerification(run_id=run_id, status=status, checks=checks)


def _bundle_manifest(
    run: StoredRun,
    report: dict[str, Any],
    artifacts: list[dict[str, Any]],
    entries: dict[str, bytes],
) -> dict[str, Any]:
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_type": BUNDLE_TYPE,
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "provenance_summary": _provenance_summary(report),
        "redaction_summary": _redaction_summary(report),
        "verification_input_summary": report.get("input_summary", _value_summary(run.inputs)),
        "files": _manifest_files(entries),
        "artifacts": artifacts,
    }


def _provenance_summary(report: dict[str, Any]) -> dict[str, Any]:
    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        return {}
    return {
        "workflow_source_path": provenance.get("workflow_source_path"),
        "workflow_sha256": provenance.get("workflow_sha256"),
        "workflow_snapshot_present": provenance.get("workflow_snapshot_present"),
        "inputs_sha256": provenance.get("inputs_sha256"),
        "git_commit": provenance.get("git_commit"),
        "environment": provenance.get("environment"),
    }


def _redaction_summary(report: dict[str, Any]) -> dict[str, int]:
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return {"redacted_nodes": 0, "redacted_values": 0}
    redaction = summary.get("redaction")
    if not isinstance(redaction, dict):
        return {"redacted_nodes": 0, "redacted_values": 0}
    return {
        "redacted_nodes": int(redaction.get("redacted_nodes", 0)),
        "redacted_values": int(redaction.get("redacted_values", 0)),
    }


def _value_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in value.keys())}
    if isinstance(value, list):
        return {"type": "array", "items": len(value)}
    return {"type": type(value).__name__}


def _manifest_files(entries: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {
            "path": name,
            "size_bytes": len(entries[name]),
            "sha256": hashlib.sha256(entries[name]).hexdigest(),
        }
        for name in sorted(entries)
    ]


def _bundle_write_order(entries: dict[str, bytes]) -> list[str]:
    order = [*STANDARD_BUNDLE_FILES]
    order.extend(name for name in sorted(entries) if name.startswith("artifacts/"))
    order.append("manifest.json")
    return [name for name in order if name in entries]


def _read_manifest(archive: zipfile.ZipFile, checks: list[VerificationCheck]) -> dict[str, Any] | None:
    if "manifest.json" not in archive.namelist():
        checks.append(
            VerificationCheck(
                type="bundle_manifest",
                status="failed",
                message="bundle is missing manifest.json",
            )
        )
        return None
    try:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        checks.append(
            VerificationCheck(
                type="bundle_manifest",
                status="failed",
                message=f"manifest.json is malformed JSON: {exc}",
            )
        )
        return None
    if not isinstance(manifest, dict):
        checks.append(
            VerificationCheck(
                type="bundle_manifest",
                status="failed",
                message="manifest.json root must be an object",
            )
        )
        return None
    schema_version = manifest.get("schema_version")
    bundle_type = manifest.get("bundle_type")
    passed = schema_version == BUNDLE_SCHEMA_VERSION and bundle_type == BUNDLE_TYPE
    checks.append(
        VerificationCheck(
            type="bundle_manifest",
            status="passed" if passed else "failed",
            message=(
                f"manifest schema_version {schema_version!r}, bundle_type {bundle_type!r}"
            ),
        )
    )
    return manifest


def _check_required_files(names: set[str], checks: list[VerificationCheck]) -> None:
    for name in ("manifest.json", *STANDARD_BUNDLE_FILES):
        passed = name in names
        checks.append(
            VerificationCheck(
                type="bundle_required_file",
                status="passed" if passed else "failed",
                message=f"required bundle file {name!r} is present" if passed else f"required bundle file {name!r} is missing",
            )
        )


def _check_manifest_files(
    archive: zipfile.ZipFile,
    manifest: dict[str, Any] | None,
    names: set[str],
    checks: list[VerificationCheck],
) -> None:
    if not isinstance(manifest, dict):
        return
    files = manifest.get("files")
    if not isinstance(files, list):
        checks.append(
            VerificationCheck(
                type="bundle_file_digest",
                status="failed",
                message="manifest files must be a list",
            )
        )
        return
    for item in files:
        if not isinstance(item, dict):
            checks.append(
                VerificationCheck(
                    type="bundle_file_digest",
                    status="failed",
                    message="manifest file entry must be an object",
                )
            )
            continue
        name = str(item.get("path", ""))
        if name not in names:
            checks.append(
                VerificationCheck(
                    type="bundle_file_digest",
                    status="failed",
                    message=f"manifest file {name!r} is missing from bundle",
                )
            )
            continue
        data = archive.read(name)
        actual_size = len(data)
        actual_sha256 = hashlib.sha256(data).hexdigest()
        expected_size = item.get("size_bytes")
        expected_sha256 = item.get("sha256")
        passed = actual_size == expected_size and actual_sha256 == expected_sha256
        checks.append(
            VerificationCheck(
                type="bundle_file_digest",
                status="passed" if passed else "failed",
                message=(
                    f"file {name!r} digest matches manifest sha256 {expected_sha256}"
                    if passed
                    else (
                        f"file {name!r} digest mismatch: size {actual_size}/{expected_size}, "
                        f"sha256 {actual_sha256}/{expected_sha256}"
                    )
                ),
            )
        )


def _check_file_coverage(
    manifest: dict[str, Any] | None,
    all_names: list[str],
    checks: list[VerificationCheck],
) -> None:
    duplicates = sorted(
        name
        for name in set(all_names)
        if all_names.count(name) > 1
    )
    if not isinstance(manifest, dict):
        manifest_paths: set[str] = set()
    else:
        manifest_files = manifest.get("files")
        manifest_paths = {
            str(item.get("path"))
            for item in manifest_files
            if isinstance(item, dict) and item.get("path") is not None
        } if isinstance(manifest_files, list) else set()
    archive_paths = set(all_names)
    extra = sorted(archive_paths - manifest_paths - {"manifest.json"})
    missing = sorted(manifest_paths - archive_paths)
    failures = []
    if duplicates:
        failures.append(f"duplicate zip entries: {duplicates}")
    if extra:
        failures.append(f"files not covered by manifest: {extra}")
    if missing:
        failures.append(f"manifest files missing from archive: {missing}")
    checks.append(
        VerificationCheck(
            type="bundle_file_coverage",
            status="failed" if failures else "passed",
            message="; ".join(failures) if failures else "all bundle files are covered by manifest",
        )
    )


def _parse_bundle_documents(
    archive: zipfile.ZipFile,
    names: set[str],
    checks: list[VerificationCheck],
) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    for name in ("report.json", "inputs.json", "events.json"):
        if name not in names:
            continue
        try:
            documents[name] = json.loads(archive.read(name).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            checks.append(
                VerificationCheck(
                    type="bundle_json",
                    status="failed",
                    message=f"{name} is malformed JSON: {exc}",
                )
            )
            continue
        checks.append(
            VerificationCheck(
                type="bundle_json",
                status="passed",
                message=f"{name} parsed as JSON",
            )
        )
    if "workflow_snapshot.yaml" in names:
        try:
            snapshot = yaml.safe_load(
                archive.read("workflow_snapshot.yaml").decode("utf-8")
            )
            documents["workflow_snapshot.yaml"] = {} if snapshot is None else snapshot
        except (yaml.YAMLError, UnicodeDecodeError) as exc:
            checks.append(
                VerificationCheck(
                    type="bundle_yaml",
                    status="failed",
                    message=f"workflow_snapshot.yaml is malformed YAML: {exc}",
                )
            )
        else:
            checks.append(
                VerificationCheck(
                    type="bundle_yaml",
                    status="passed",
                    message="workflow_snapshot.yaml parsed as YAML",
                )
            )
    return documents


def _check_document_schema(documents: dict[str, Any], checks: list[VerificationCheck]) -> None:
    expected = {
        "report.json": dict,
        "inputs.json": dict,
        "events.json": list,
        "workflow_snapshot.yaml": dict,
    }
    for name, expected_type in expected.items():
        if name not in documents:
            continue
        value = documents[name]
        passed = isinstance(value, expected_type)
        expected_label = "object" if expected_type is dict else "array"
        checks.append(
            VerificationCheck(
                type="bundle_document_schema",
                status="passed" if passed else "failed",
                message=(
                    f"{name} has expected {expected_label} schema"
                    if passed
                    else f"{name} must be a {expected_label}"
                ),
            )
        )
        if not passed:
            continue
        if name == "report.json":
            checks.extend(_report_schema_checks(value))
        if name == "events.json":
            checks.extend(_events_schema_checks(value))


def _report_schema_checks(report: dict[str, Any]) -> list[VerificationCheck]:
    required_fields = ("run_id", "workflow_id", "status", "summary", "timeline")
    missing = [field for field in required_fields if field not in report]
    if missing:
        return [
            VerificationCheck(
                type="bundle_document_schema",
                status="failed",
                message=f"report.json missing required fields: {missing}",
            )
        ]
    if not isinstance(report.get("summary"), dict):
        return [
            VerificationCheck(
                type="bundle_document_schema",
                status="failed",
                message="report.json summary must be an object",
            )
        ]
    if not isinstance(report.get("timeline"), list):
        return [
            VerificationCheck(
                type="bundle_document_schema",
                status="failed",
                message="report.json timeline must be an array",
            )
        ]
    return [
        VerificationCheck(
            type="bundle_document_schema",
            status="passed",
            message="report.json contains required run evidence fields",
        )
    ]


def _events_schema_checks(events: list[Any]) -> list[VerificationCheck]:
    malformed = [
        index
        for index, event in enumerate(events)
        if not isinstance(event, dict)
        or not {"run_id", "node_id", "status", "input", "output", "metadata"}.issubset(event)
    ]
    if malformed:
        return [
            VerificationCheck(
                type="bundle_document_schema",
                status="failed",
                message=f"events.json has malformed event entries at indexes {malformed}",
            )
        ]
    return [
        VerificationCheck(
            type="bundle_document_schema",
            status="passed",
            message="events.json contains structured node event evidence",
        )
    ]


def _check_run_identity(
    manifest: dict[str, Any] | None,
    documents: dict[str, Any],
    checks: list[VerificationCheck],
) -> None:
    if not isinstance(manifest, dict):
        return
    expected_run_id = manifest.get("run_id")
    expected_workflow_id = manifest.get("workflow_id")
    failures: list[str] = []

    report = documents.get("report.json")
    if isinstance(report, dict):
        if report.get("run_id") != expected_run_id:
            failures.append(f"report run_id {report.get('run_id')!r} != manifest run_id {expected_run_id!r}")
        if report.get("workflow_id") != expected_workflow_id:
            failures.append(
                f"report workflow_id {report.get('workflow_id')!r} != manifest workflow_id {expected_workflow_id!r}"
            )

    events = documents.get("events.json")
    if isinstance(events, list):
        mismatched = [
            event.get("run_id")
            for event in events
            if isinstance(event, dict) and event.get("run_id") != expected_run_id
        ]
        if mismatched:
            failures.append(f"event run_id values {mismatched!r} != manifest run_id {expected_run_id!r}")

    workflow_snapshot = documents.get("workflow_snapshot.yaml")
    if isinstance(workflow_snapshot, dict) and workflow_snapshot.get("id") not in (None, expected_workflow_id):
        failures.append(
            f"workflow snapshot id {workflow_snapshot.get('id')!r} != manifest workflow_id {expected_workflow_id!r}"
        )

    checks.append(
        VerificationCheck(
            type="bundle_run_identity",
            status="failed" if failures else "passed",
            message="; ".join(failures) if failures else f"bundle run_id {expected_run_id!r} is consistent",
        )
    )


def _check_redaction(
    manifest: dict[str, Any] | None,
    documents: dict[str, Any],
    checks: list[VerificationCheck],
) -> None:
    workflow_snapshot = documents.get("workflow_snapshot.yaml")
    sensitive_paths = _sensitive_paths_from_snapshot(workflow_snapshot)
    sensitive_paths.extend(_sensitive_paths_from_redaction_metadata(documents))
    sensitive_paths = sorted(set(sensitive_paths))
    redaction_summary = manifest.get("redaction_summary") if isinstance(manifest, dict) else None
    redacted_nodes = redaction_summary.get("redacted_nodes") if isinstance(redaction_summary, dict) else 0
    redacted_values = redaction_summary.get("redacted_values") if isinstance(redaction_summary, dict) else 0
    if not sensitive_paths:
        if redacted_nodes or redacted_values:
            checks.append(
                VerificationCheck(
                    type="bundle_redaction",
                    status="failed",
                    message="redaction summary is present but no sensitive path source is available",
                )
            )
            return
        checks.append(
            VerificationCheck(
                type="bundle_redaction",
                status="passed",
                message="bundle declares no sensitive paths",
            )
        )
        return

    leaks: list[str] = []
    for sensitive_path in sensitive_paths:
        for location, value in _sensitive_values_for_path(sensitive_path, documents):
            if value != REDACTION_MARKER:
                leaks.append(f"{sensitive_path} leaked at {location}")

    checks.append(
        VerificationCheck(
            type="bundle_redaction",
            status="failed" if leaks else "passed",
            message="; ".join(leaks) if leaks else f"sensitive paths are redacted: {', '.join(sensitive_paths)}",
        )
    )


def _sensitive_paths_from_snapshot(snapshot: Any) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    governance = snapshot.get("governance")
    if not isinstance(governance, dict):
        return []
    raw_paths = governance.get("sensitive_paths")
    if not isinstance(raw_paths, list):
        return []
    return [path for path in raw_paths if isinstance(path, str) and "." in path]


def _sensitive_paths_from_redaction_metadata(documents: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    events = documents.get("events.json")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            metadata = event.get("metadata")
            if isinstance(metadata, dict):
                paths.extend(_paths_from_redaction_object(metadata.get("redaction")))
    report = documents.get("report.json")
    if isinstance(report, dict):
        for node in report.get("timeline", []):
            if isinstance(node, dict):
                paths.extend(_paths_from_redaction_object(node.get("redaction")))
    return paths


def _paths_from_redaction_object(redaction: Any) -> list[str]:
    if not isinstance(redaction, dict):
        return []
    raw_paths = redaction.get("paths")
    if not isinstance(raw_paths, list):
        return []
    return [path for path in raw_paths if isinstance(path, str) and "." in path]


def _sensitive_values_for_path(sensitive_path: str, documents: dict[str, Any]) -> list[tuple[str, Any]]:
    parts = sensitive_path.split(".")
    root = parts[0]
    rest = parts[1:]
    found: list[tuple[str, Any]] = []
    report = documents.get("report.json")
    events = documents.get("events.json")
    inputs = documents.get("inputs.json")

    if root == "inputs":
        _append_found(found, "inputs.json", inputs, rest)
        if isinstance(report, dict):
            _append_found(found, "report.json.inputs", report.get("inputs"), rest)
        return found
    if root == "outputs":
        if isinstance(report, dict):
            _append_found(found, "report.json.outputs", report.get("outputs"), rest)
        return found
    if root in {"node_output", "node_metadata", "tool_invocation"} and len(rest) >= 2:
        node_id = rest[0]
        path = rest[1:]
        if root == "node_output":
            if isinstance(report, dict):
                _append_found(found, f"report.json.outputs.{node_id}", report.get("outputs", {}).get(node_id), path)
                for node in _report_timeline_nodes(report, node_id):
                    _append_found(found, f"report.json.timeline.{node_id}.output", node.get("output"), path)
            for event in _events_for_node(events, node_id):
                _append_found(found, f"events.json.{node_id}.output", event.get("output"), path)
        if root == "node_metadata":
            for event in _events_for_node(events, node_id):
                _append_found(found, f"events.json.{node_id}.metadata", event.get("metadata"), path)
        if root == "tool_invocation":
            if isinstance(report, dict):
                for node in _report_timeline_nodes(report, node_id):
                    _append_found(found, f"report.json.timeline.{node_id}.tool", node.get("tool"), path)
            for event in _events_for_node(events, node_id):
                output = event.get("output")
                if isinstance(output, dict):
                    _append_found(found, f"events.json.{node_id}.output.tool_invocation", output.get("tool_invocation"), path)
        return found
    return found


def _append_found(found: list[tuple[str, Any]], location: str, value: Any, parts: list[str]) -> None:
    path_value, exists = _lookup_path(value, parts)
    if exists:
        found.append((location, path_value))


def _events_for_node(events: Any, node_id: str) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    return [
        event
        for event in events
        if isinstance(event, dict) and event.get("node_id") == node_id
    ]


def _report_timeline_nodes(report: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    timeline = report.get("timeline")
    if not isinstance(timeline, list):
        return []
    return [
        node
        for node in timeline
        if isinstance(node, dict) and node.get("node_id") == node_id
    ]


def _lookup_path(value: Any, parts: list[str]) -> tuple[Any, bool]:
    current = value
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
            continue
        return None, False
    return current, True


def _artifact_archive_path(node_id: str, artifact: dict[str, Any]) -> str:
    artifact_name = _safe_path_part(str(artifact.get("name", "artifact")))
    source_path = Path(str(artifact.get("path", "artifact")))
    filename = _safe_path_part(source_path.name or artifact_name)
    return str(PurePosixPath("artifacts") / _safe_path_part(node_id) / artifact_name / filename)


def _stored_artifact_path(state_dir: Path, run_id: str, node_id: str, name: str, source_path: Path) -> Path:
    filename = _safe_path_part(source_path.name or name)
    return (
        state_dir
        / "artifacts"
        / _safe_path_part(run_id)
        / _safe_path_part(node_id)
        / _safe_path_part(name)
        / filename
    )


def _safe_path_part(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in ("-", "_", ".") else "_" for character in value)
    safe = safe.strip("._")
    return safe or "artifact"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
