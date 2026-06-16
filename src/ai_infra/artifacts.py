from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .store import NodeEvent, StoredRun
from .tools import _render_template


@dataclass(frozen=True)
class EvidenceBundle:
    run_id: str
    path: str
    artifacts: list[dict[str, Any]]


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

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", _json_bytes(report))
        archive.writestr("inputs.json", _json_bytes(run.inputs))
        archive.writestr("events.json", _json_bytes([asdict(event) for event in run.events]))
        if run.provenance is not None:
            archive.writestr("workflow_snapshot.yaml", run.provenance.workflow_snapshot)
        else:
            archive.writestr("workflow_snapshot.yaml", "")

        for event in run.events:
            for artifact in event_artifacts(event):
                manifest_artifact = dict(artifact)
                manifest_artifact["node_id"] = event.node_id
                archive_path = _artifact_archive_path(event.node_id, artifact)
                manifest_artifact["archive_path"] = archive_path
                artifact_path = Path(str(artifact.get("stored_path") or artifact.get("path", "")))
                if artifact_path.exists() and artifact_path.is_file():
                    archive.write(artifact_path, archive_path)
                manifest_artifacts.append(manifest_artifact)

        manifest = {
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "status": run.status,
            "artifacts": manifest_artifacts,
        }
        archive.writestr("manifest.json", _json_bytes(manifest))

    return EvidenceBundle(
        run_id=run.run_id,
        path=str(bundle_path),
        artifacts=manifest_artifacts,
    )


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
