from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from .config import Workflow, workflow_compatibility
from .store import RunProvenance


def build_run_provenance(workflow: Workflow, inputs: dict[str, Any]) -> RunProvenance:
    workflow_source_path = str(workflow.source_path) if workflow.source_path else None
    workflow_snapshot = _workflow_snapshot(workflow)
    return RunProvenance(
        workflow_source_path=workflow_source_path,
        workflow_snapshot=workflow_snapshot,
        workflow_sha256=sha256_text(workflow_snapshot),
        inputs_sha256=sha256_text(_canonical_json(inputs)),
        git_commit=_git_commit(workflow.source_path),
        environment=_environment_summary(),
        compatibility=workflow_compatibility(workflow),
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _workflow_snapshot(workflow: Workflow) -> str:
    if workflow.source_snapshot is not None:
        return workflow.source_snapshot
    return _canonical_json(
        {
            "id": workflow.id,
            "name": workflow.name,
            "version": workflow.version,
            "schema_version": workflow.schema_version,
            "features": workflow.features,
            "entrypoint": workflow.entrypoint,
            "nodes": {
                node.id: _node_snapshot(node)
                for node in workflow.nodes
            },
            "edges": [
                {"from": edge.source, "to": edge.target}
                for edge in workflow.edges
            ],
            "governance": workflow.governance,
            "validations": [
                {"type": validation.type, **validation.config}
                for validation in workflow.validations
            ],
        }
    )


def _node_snapshot(node: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"type": node.type}
    if node.template is not None:
        snapshot["template"] = node.template
    if node.next is not None:
        snapshot["next"] = node.next
    snapshot.update(node.config)
    return snapshot


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _git_commit(source_path: Path | None) -> str | None:
    cwd = source_path.parent if source_path is not None else Path.cwd()
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _environment_summary() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "ai_infra_version": _package_version(),
    }


def _package_version() -> str | None:
    try:
        return metadata.version("ai-infra")
    except metadata.PackageNotFoundError:
        return None
