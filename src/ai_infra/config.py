from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class WorkflowValidationError(ValueError):
    pass


TOP_LEVEL_FIELDS = {"id", "name", "version", "entrypoint", "nodes", "edges", "validations"}
NODE_FIELDS = {"type", "template", "next", "tool", "config", "policy"}
EDGE_FIELDS = {"from", "to"}
SUPPORTED_NODE_TYPES = {"template", "react", "tool", "llm", "validation"}
SUPPORTED_TOOL_ADAPTERS = {"python", "shell", "http"}
SUPPORTED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SUPPORTED_VALIDATION_TYPES = {
    "run_status",
    "node_completed",
    "node_failed",
    "node_attempts",
    "node_policy_outcome",
}
SUPPORTED_ON_FAILURE = {"halt", "continue"}
SUPPORTED_POLICY_OUTCOMES = {
    "completed",
    "retry_succeeded",
    "retry_exhausted",
    "continued_after_failure",
}
RUN_STATUSES = {"completed", "failed", "running"}


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
    source_snapshot: str | None = None

    @property
    def node_map(self) -> dict[str, WorkflowNode]:
        return {node.id: node for node in self.nodes}


def load_workflow(path: str | Path) -> Workflow:
    source_path = Path(path)
    return load_workflow_from_source(source_path.read_text(encoding="utf-8"), source_path=source_path)


def load_workflow_from_source(source: str, source_path: str | Path | None = None) -> Workflow:
    raw = _load_yaml_mapping(source)
    _reject_unknown_fields(raw, TOP_LEVEL_FIELDS, "top-level")

    nodes = _load_nodes(raw.get("nodes"))
    edges = _load_edges(raw.get("edges"))
    validations = _load_validations(raw.get("validations"))
    workflow_id = _optional_string(raw, "id", default="")
    resolved_source_path = Path(source_path) if source_path is not None else None
    return Workflow(
        id=workflow_id,
        name=_optional_string(raw, "name", default=workflow_id),
        version=_optional_string(raw, "version", default=""),
        entrypoint=_optional_string(raw, "entrypoint", default=None),
        nodes=nodes,
        edges=edges,
        validations=validations,
        source_path=resolved_source_path,
        source_snapshot=source,
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
        if node.type not in SUPPORTED_NODE_TYPES:
            raise WorkflowValidationError(f"node {node.id!r} has unsupported type {node.type!r}")
        if node.type == "template" and not node.template:
            raise WorkflowValidationError(f"template node {node.id!r} requires template")
        if node.type == "tool":
            _validate_tool_node(node)
        _validate_node_policy(node)
        if node.next and node.next not in node_ids:
            raise WorkflowValidationError(f"node {node.id!r} next target {node.next!r} is missing")

    seen_edges: set[tuple[str, str]] = set()
    for edge in workflow.edges:
        if edge.source not in node_ids:
            raise WorkflowValidationError(f"edge source {edge.source!r} is missing")
        if edge.target not in node_ids:
            raise WorkflowValidationError(f"edge target {edge.target!r} is missing")
        edge_key = (edge.source, edge.target)
        if edge_key in seen_edges:
            raise WorkflowValidationError(f"duplicate edge {edge.source!r} -> {edge.target!r}")
        seen_edges.add(edge_key)

    for index, validation in enumerate(workflow.validations):
        _validate_run_validation(index, validation, node_ids)

    _validate_acyclic(workflow)


def _load_yaml_mapping(source: str) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise WorkflowValidationError(f"workflow YAML is invalid: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WorkflowValidationError("workflow YAML root must be a mapping")
    return raw


def _load_nodes(raw_nodes: Any) -> list[WorkflowNode]:
    if raw_nodes is None:
        return []
    if not isinstance(raw_nodes, dict):
        raise WorkflowValidationError("workflow nodes must be a mapping")

    nodes: list[WorkflowNode] = []
    for node_id, node_data in raw_nodes.items():
        if not isinstance(node_id, str) or not node_id.strip():
            raise WorkflowValidationError("node id must be a non-empty string")
        if not isinstance(node_data, dict):
            raise WorkflowValidationError(f"node {node_id!r} must be a mapping")
        _reject_unknown_fields(node_data, NODE_FIELDS, f"node {node_id!r}")
        nodes.append(
            WorkflowNode(
                id=node_id,
                type=_optional_string(node_data, "type", default=""),
                template=_optional_string(node_data, "template", default=None),
                next=_optional_string(node_data, "next", default=None),
                config=_node_config(node_data),
            )
        )
    return nodes


def _node_config(node_data: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if "tool" in node_data:
        config["tool"] = node_data["tool"]
    if "policy" in node_data:
        config["policy"] = node_data["policy"]
    if "config" in node_data:
        if not isinstance(node_data["config"], dict):
            raise WorkflowValidationError("node config must be a mapping")
        config["config"] = node_data["config"]
    return config


def _load_edges(raw_edges: Any) -> list[WorkflowEdge]:
    if raw_edges is None:
        return []
    if not isinstance(raw_edges, list):
        raise WorkflowValidationError("workflow edges must be a list")

    edges: list[WorkflowEdge] = []
    for index, edge in enumerate(raw_edges):
        if not isinstance(edge, dict):
            raise WorkflowValidationError(f"edge[{index}] must be a mapping")
        _reject_unknown_fields(edge, EDGE_FIELDS, f"edge[{index}]")
        edges.append(
            WorkflowEdge(
                source=_required_string(edge, "from", f"edge[{index}] from"),
                target=_required_string(edge, "to", f"edge[{index}] to"),
            )
        )
    return edges


def _load_validations(raw_validations: Any) -> list[WorkflowValidation]:
    if raw_validations is None:
        return []
    if not isinstance(raw_validations, list):
        raise WorkflowValidationError("workflow validations must be a list")

    validations: list[WorkflowValidation] = []
    for index, item in enumerate(raw_validations):
        if not isinstance(item, dict):
            raise WorkflowValidationError(f"validation[{index}] must be a mapping")
        validations.append(
            WorkflowValidation(
                type=_optional_string(item, "type", default=""),
                config={key: value for key, value in item.items() if key != "type"},
            )
        )
    return validations


def _validate_tool_node(node: WorkflowNode) -> None:
    tool_config = node.config.get("tool")
    if not isinstance(tool_config, dict):
        raise WorkflowValidationError(f"tool node {node.id!r} requires tool config")

    adapter = tool_config.get("adapter")
    if not _is_non_empty_string(adapter):
        raise WorkflowValidationError(f"tool node {node.id!r} requires tool adapter")
    if adapter not in SUPPORTED_TOOL_ADAPTERS:
        raise WorkflowValidationError(f"tool node {node.id!r} has unsupported adapter {adapter!r}")

    if adapter == "python":
        _reject_unknown_fields(tool_config, {"adapter", "name", "args"}, f"python tool node {node.id!r}")
        if not _is_non_empty_string(tool_config.get("name")):
            raise WorkflowValidationError(f"python tool node {node.id!r} requires name")
        if "args" in tool_config and not isinstance(tool_config["args"], dict):
            raise WorkflowValidationError(f"python tool node {node.id!r} args must be a mapping")
        return

    if adapter == "shell":
        _reject_unknown_fields(tool_config, {"adapter", "command", "timeout_seconds"}, f"shell tool node {node.id!r}")
        if not _is_non_empty_string(tool_config.get("command")):
            raise WorkflowValidationError(f"shell tool node {node.id!r} requires non-empty command")
        _validate_timeout(tool_config, f"shell tool node {node.id!r}")
        return

    _reject_unknown_fields(tool_config, {"adapter", "method", "url", "json", "timeout_seconds"}, f"http tool node {node.id!r}")
    url = tool_config.get("url")
    if not _is_non_empty_string(url):
        raise WorkflowValidationError(f"http tool node {node.id!r} requires url")
    if not _is_supported_http_url(url):
        raise WorkflowValidationError(f"http tool node {node.id!r} has unsupported url {url!r}")
    method = str(tool_config.get("method", "GET")).upper()
    if method not in SUPPORTED_HTTP_METHODS:
        raise WorkflowValidationError(f"http tool node {node.id!r} has unsupported method {method!r}")
    _validate_timeout(tool_config, f"http tool node {node.id!r}")


def _validate_node_policy(node: WorkflowNode) -> None:
    policy = node.config.get("policy")
    if policy is None:
        return
    if not isinstance(policy, dict):
        raise WorkflowValidationError(f"node {node.id!r} policy must be a mapping")
    _reject_unknown_fields(policy, {"on_failure", "max_attempts"}, f"node {node.id!r} policy")
    on_failure = policy.get("on_failure", "halt")
    if on_failure not in SUPPORTED_ON_FAILURE:
        allowed = ", ".join(sorted(SUPPORTED_ON_FAILURE))
        raise WorkflowValidationError(f"node {node.id!r} policy on_failure must be one of {allowed}")
    max_attempts = policy.get("max_attempts", 1)
    if not isinstance(max_attempts, int) or max_attempts < 1 or max_attempts > 10:
        raise WorkflowValidationError(
            f"node {node.id!r} policy max_attempts must be an integer between 1 and 10"
        )


def _validate_timeout(config: dict[str, Any], context: str) -> None:
    if "timeout_seconds" not in config:
        return
    timeout = config["timeout_seconds"]
    if not isinstance(timeout, int) or timeout <= 0:
        raise WorkflowValidationError(f"{context} timeout_seconds must be a positive integer")


def _validate_run_validation(index: int, validation: WorkflowValidation, node_ids: set[str]) -> None:
    context = f"validation[{index}]"
    if validation.type not in SUPPORTED_VALIDATION_TYPES:
        raise WorkflowValidationError(f"{context} has unsupported type {validation.type!r}")

    if validation.type == "run_status":
        _reject_unknown_fields(validation.config, {"equals"}, context)
        expected = validation.config.get("equals")
        if not _is_non_empty_string(expected):
            raise WorkflowValidationError(f"{context} run_status requires equals")
        if expected not in RUN_STATUSES:
            raise WorkflowValidationError(f"{context} run_status has unsupported equals {expected!r}")
        return

    if validation.type == "node_attempts":
        _reject_unknown_fields(validation.config, {"node", "equals"}, context)
        _validate_validation_node_reference(context, validation, node_ids)
        expected = validation.config.get("equals")
        if not isinstance(expected, int) or expected < 1:
            raise WorkflowValidationError(f"{context} node_attempts requires equals")
        return

    if validation.type == "node_policy_outcome":
        _reject_unknown_fields(validation.config, {"node", "equals"}, context)
        _validate_validation_node_reference(context, validation, node_ids)
        expected = validation.config.get("equals")
        if not _is_non_empty_string(expected):
            raise WorkflowValidationError(f"{context} node_policy_outcome requires equals")
        if expected not in SUPPORTED_POLICY_OUTCOMES:
            raise WorkflowValidationError(
                f"{context} node_policy_outcome has unsupported equals {expected!r}"
            )
        return

    _reject_unknown_fields(validation.config, {"node"}, context)
    _validate_validation_node_reference(context, validation, node_ids)


def _validate_validation_node_reference(
    context: str,
    validation: WorkflowValidation,
    node_ids: set[str],
) -> None:
    node_id = validation.config.get("node")
    if not _is_non_empty_string(node_id):
        raise WorkflowValidationError(f"{context} {validation.type} requires node")
    if node_id not in node_ids:
        raise WorkflowValidationError(f"{context} references missing node {node_id!r}")


def _reject_unknown_fields(raw: dict[str, Any], allowed: set[str], context: str) -> None:
    for key in raw:
        if key not in allowed:
            if context == "top-level":
                raise WorkflowValidationError(f"unsupported top-level field {key!r}")
            raise WorkflowValidationError(f"{context} has unsupported field {key!r}")


def _required_string(raw: dict[str, Any], key: str, context: str) -> str:
    if key not in raw:
        raise WorkflowValidationError(f"{context} is required")
    value = raw[key]
    if not _is_non_empty_string(value):
        raise WorkflowValidationError(f"{context} must be a non-empty string")
    return value


def _optional_string(raw: dict[str, Any], key: str, default: str | None) -> str | None:
    if key not in raw or raw[key] is None:
        return default
    value = raw[key]
    if not isinstance(value, str):
        raise WorkflowValidationError(f"{key} must be a string")
    return value


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_supported_http_url(url: str) -> bool:
    return url == "memory://echo" or url.startswith(("http://", "https://"))


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
