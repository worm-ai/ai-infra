from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class WorkflowValidationError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    type: str
    template: str | None = None
    next: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowEdge:
    source: str
    target: str


@dataclass(frozen=True)
class WorkflowValidation:
    type: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Workflow:
    id: str
    name: str
    version: str
    entrypoint: str | None
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    validations: list[WorkflowValidation]
    source_path: Path | None = None

    @property
    def node_map(self) -> dict[str, WorkflowNode]:
        return {node.id: node for node in self.nodes}


def load_workflow(path: str | Path) -> Workflow:
    source_path = Path(path)
    raw = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    nodes = [
        WorkflowNode(
            id=node_id,
            type=str(node_data.get("type", "")),
            template=node_data.get("template"),
            next=node_data.get("next"),
            config={key: value for key, value in node_data.items() if key not in {"type", "template", "next"}},
        )
        for node_id, node_data in (raw.get("nodes") or {}).items()
    ]
    edges = [
        WorkflowEdge(source=str(edge.get("from", "")), target=str(edge.get("to", "")))
        for edge in raw.get("edges", [])
    ]
    validations = [
        WorkflowValidation(
            type=str(item.get("type", "")),
            config={key: value for key, value in item.items() if key != "type"},
        )
        for item in raw.get("validations", [])
    ]
    return Workflow(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", raw.get("id", ""))),
        version=str(raw.get("version", "")),
        entrypoint=raw.get("entrypoint"),
        nodes=nodes,
        edges=edges,
        validations=validations,
        source_path=source_path,
    )


def validate_workflow(workflow: Workflow) -> None:
    if not workflow.id:
        raise WorkflowValidationError("workflow id is required")
    if not workflow.entrypoint:
        raise WorkflowValidationError("workflow entrypoint is required")
    if not workflow.nodes:
        raise WorkflowValidationError("workflow nodes are required")

    node_ids = {node.id for node in workflow.nodes}
    if workflow.entrypoint not in node_ids:
        raise WorkflowValidationError(f"entrypoint {workflow.entrypoint!r} does not reference a node")

    for node in workflow.nodes:
        if node.type not in {"template", "react", "tool", "llm", "validation"}:
            raise WorkflowValidationError(f"node {node.id!r} has unsupported type {node.type!r}")
        if node.type == "template" and not node.template:
            raise WorkflowValidationError(f"template node {node.id!r} requires template")
        if node.type == "tool":
            tool_config = node.config.get("tool")
            if not isinstance(tool_config, dict):
                raise WorkflowValidationError(f"tool node {node.id!r} requires tool config")
            if not tool_config.get("adapter"):
                raise WorkflowValidationError(f"tool node {node.id!r} requires tool adapter")
        if node.next and node.next not in node_ids:
            raise WorkflowValidationError(f"node {node.id!r} next target {node.next!r} is missing")

    for edge in workflow.edges:
        if edge.source not in node_ids:
            raise WorkflowValidationError(f"edge source {edge.source!r} is missing")
        if edge.target not in node_ids:
            raise WorkflowValidationError(f"edge target {edge.target!r} is missing")

    _validate_acyclic(workflow)


def _validate_acyclic(workflow: Workflow) -> None:
    successors: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
    for node in workflow.nodes:
        if node.next:
            successors[node.id].append(node.next)
    for edge in workflow.edges:
        successors.setdefault(edge.source, []).append(edge.target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str, path: list[str]) -> None:
        if node_id in visiting:
            cycle_start = path.index(node_id) if node_id in path else 0
            cycle_path = " -> ".join([*path[cycle_start:], node_id])
            raise WorkflowValidationError(f"workflow cycle detected: {cycle_path}")
        if node_id in visited:
            return
        visiting.add(node_id)
        for target in successors.get(node_id, []):
            visit(target, [*path, target])
        visiting.remove(node_id)
        visited.add(node_id)

    if workflow.entrypoint:
        visit(workflow.entrypoint, [workflow.entrypoint])
    for node in workflow.nodes:
        visit(node.id, [node.id])
