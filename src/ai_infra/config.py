from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class WorkflowValidationError(ValueError):
    def __init__(self, message: str, *, compatibility: dict[str, Any] | None = None):
        super().__init__(message)
        self.compatibility = compatibility


TOP_LEVEL_FIELDS = {
    "id",
    "name",
    "version",
    "schema_version",
    "features",
    "entrypoint",
    "nodes",
    "edges",
    "validations",
    "governance",
}
NODE_FIELDS = {"type", "template", "next", "tool", "config", "policy", "contract", "artifacts", "governance"}
EDGE_FIELDS = {"from", "to"}
SUPPORTED_SCHEMA_VERSIONS = {"1"}
SUPPORTED_WORKFLOW_FEATURES = {
    "template_nodes",
    "tool_nodes",
    "react_nodes",
    "edge_list",
    "validations",
    "governance",
    "retry_policy",
    "output_contracts",
    "artifacts",
    "redaction",
    "mcp_tools",
    "openai_compatible_react_provider",
}
DEPRECATED_WORKFLOW_FEATURES = {
    "legacy_llm_node": "react_nodes",
}
SUPPORTED_NODE_TYPES = {"template", "react", "tool", "llm", "validation"}
SUPPORTED_TOOL_ADAPTERS = {"python", "shell", "http", "mcp"}
SUPPORTED_REACT_PROVIDERS = {"mock", "openai-compatible"}
SUPPORTED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SUPPORTED_CONTRACT_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
SUPPORTED_CONTRACT_STATUSES = {"passed", "failed"}
SUPPORTED_RESUME_ACTIONS = {"run", "rerun", "skipped"}
SUPPORTED_GOVERNANCE_STATUSES = {"within_limits", "timeout", "budget_exhausted", "aborted"}
SUPPORTED_ASSERTION_SOURCES = {"run", "node_output", "node_metadata", "tool_invocation", "report"}
SUPPORTED_ASSERTION_OPERATORS = {"equals", "contains", "exists", "value_type"}
SUPPORTED_VALIDATION_TYPES = {
    "run_status",
    "node_completed",
    "node_failed",
    "node_attempts",
    "node_policy_outcome",
    "node_contract",
    "node_resume_action",
    "node_artifact",
    "node_governance",
    "assertion",
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
    governance: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None
    source_snapshot: str | None = None
    schema_version: str = "1"
    features: list[str] = field(default_factory=list)

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
    governance = _workflow_governance(raw.get("governance"))
    workflow_id = _optional_string(raw, "id", default="")
    resolved_source_path = Path(source_path) if source_path is not None else None
    return Workflow(
        id=workflow_id,
        name=_optional_string(raw, "name", default=workflow_id),
        version=_optional_string(raw, "version", default=""),
        schema_version=_optional_string(raw, "schema_version", default="1") or "1",
        features=_load_features(raw.get("features")),
        entrypoint=_optional_string(raw, "entrypoint", default=None),
        nodes=nodes,
        edges=edges,
        validations=validations,
        governance=governance,
        source_path=resolved_source_path,
        source_snapshot=source,
    )


def validate_workflow(workflow: Workflow) -> dict[str, Any]:
    compatibility = workflow_compatibility(workflow)
    if compatibility["status"] in {"unsupported", "future"}:
        raise WorkflowValidationError(_compatibility_error_message(compatibility), compatibility=compatibility)

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
        if node.type == "react":
            _validate_react_node(node)
        _validate_node_policy(node)
        _validate_node_contract(node)
        _validate_node_artifacts(node)
        _validate_node_governance(node)
        if node.next and node.next not in node_ids:
            raise WorkflowValidationError(f"node {node.id!r} next target {node.next!r} is missing")

    _validate_workflow_governance(workflow.governance)

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
    return compatibility


def workflow_compatibility(workflow: Workflow) -> dict[str, Any]:
    schema_version = str(workflow.schema_version or "1")
    schema_status = "supported" if schema_version in SUPPORTED_SCHEMA_VERSIONS else "future"
    diagnostics: list[dict[str, str]] = []
    feature_evidence: list[dict[str, str]] = []
    failure_category: str | None = None

    if schema_status == "future":
        diagnostics.append(
            {
                "category": "future_schema",
                "severity": "error",
                "message": (
                    f"workflow schema_version {schema_version!r} is newer than supported schema versions: "
                    f"{_supported_schema_versions_label()}"
                ),
            }
        )
        failure_category = "future_schema"

    for feature in workflow.features:
        if feature in SUPPORTED_WORKFLOW_FEATURES:
            feature_evidence.append({"name": feature, "status": "supported"})
            continue
        if feature in DEPRECATED_WORKFLOW_FEATURES:
            replacement = DEPRECATED_WORKFLOW_FEATURES[feature]
            feature_evidence.append(
                {
                    "name": feature,
                    "status": "deprecated",
                    "replacement": replacement,
                }
            )
            diagnostics.append(
                {
                    "category": "deprecated_feature",
                    "severity": "warning",
                    "message": f"feature {feature!r} is deprecated; use {replacement!r}",
                }
            )
            continue
        feature_evidence.append({"name": feature, "status": "unsupported"})
        diagnostics.append(
            {
                "category": "unsupported_feature",
                "severity": "error",
                "message": f"feature {feature!r} is unsupported by this local DAG runtime",
            }
        )
        failure_category = failure_category or "unsupported_feature"

    if schema_status == "future":
        status = "future"
    elif any(item["status"] == "unsupported" for item in feature_evidence):
        status = "unsupported"
    elif any(item["status"] == "deprecated" for item in feature_evidence):
        status = "deprecated"
    else:
        status = "supported"

    return {
        "schema_version": {
            "declared": schema_version,
            "supported": sorted(SUPPORTED_SCHEMA_VERSIONS),
            "status": schema_status,
        },
        "features": feature_evidence,
        "status": status,
        "failure_category": failure_category,
        "diagnostics": diagnostics,
    }


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
    if "contract" in node_data:
        config["contract"] = node_data["contract"]
    if "artifacts" in node_data:
        config["artifacts"] = node_data["artifacts"]
    if "governance" in node_data:
        config["governance"] = node_data["governance"]
    if "config" in node_data:
        if not isinstance(node_data["config"], dict):
            raise WorkflowValidationError("node config must be a mapping")
        config["config"] = node_data["config"]
    return config


def _workflow_governance(raw_governance: Any) -> dict[str, Any]:
    if raw_governance is None:
        return {}
    if not isinstance(raw_governance, dict):
        return {"__invalid__": raw_governance}
    return dict(raw_governance)


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


def _load_features(raw_features: Any) -> list[str]:
    if raw_features is None:
        return []
    if not isinstance(raw_features, list):
        raise WorkflowValidationError("workflow features must be a list")
    features: list[str] = []
    for index, feature in enumerate(raw_features):
        if not _is_non_empty_string(feature):
            raise WorkflowValidationError(f"workflow features[{index}] must be a non-empty string")
        features.append(str(feature))
    return features


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

    if adapter == "mcp":
        _validate_mcp_tool_config(tool_config, f"mcp tool node {node.id!r}")
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


def _validate_mcp_tool_config(tool_config: dict[str, Any], context: str) -> None:
    _reject_unknown_fields(tool_config, {"adapter", "runtime", "server", "tool", "args", "timeout_seconds"}, context)
    runtime = tool_config.get("runtime")
    if runtime is not None and runtime != "local":
        raise WorkflowValidationError(f"{context} runtime must be 'local'")
    if not _is_non_empty_string(tool_config.get("server")):
        raise WorkflowValidationError(f"{context} requires server")
    if not _is_non_empty_string(tool_config.get("tool")):
        raise WorkflowValidationError(f"{context} requires tool")
    if "args" in tool_config and not isinstance(tool_config["args"], dict):
        raise WorkflowValidationError(f"{context} args must be a mapping")
    _validate_timeout(tool_config, context)


def _validate_react_node(node: WorkflowNode) -> None:
    react_config = node.config.get("config")
    if not isinstance(react_config, dict):
        raise WorkflowValidationError(f"react node {node.id!r} requires config")
    _reject_unknown_fields(
        react_config,
        {
            "provider",
            "model",
            "prompt",
            "max_steps",
            "budget",
            "tools",
            "base_url",
            "api_key_env",
            "timeout_ms",
        },
        f"react node {node.id!r} config",
    )

    provider = react_config.get("provider")
    if not _is_non_empty_string(provider):
        raise WorkflowValidationError(f"react node {node.id!r} requires provider")
    if provider not in SUPPORTED_REACT_PROVIDERS:
        allowed = ", ".join(sorted(SUPPORTED_REACT_PROVIDERS))
        raise WorkflowValidationError(f"react node {node.id!r} provider must be one of {allowed}")

    if not _is_non_empty_string(react_config.get("model")):
        raise WorkflowValidationError(f"react node {node.id!r} requires model")
    if not _is_non_empty_string(react_config.get("prompt")):
        raise WorkflowValidationError(f"react node {node.id!r} requires prompt")
    max_steps = react_config.get("max_steps")
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1 or max_steps > 10:
        raise WorkflowValidationError(f"react node {node.id!r} max_steps must be an integer between 1 and 10")

    if "base_url" in react_config and not _is_non_empty_string(react_config.get("base_url")):
        raise WorkflowValidationError(f"react node {node.id!r} base_url must be a non-empty string")
    if "api_key_env" in react_config and not _is_non_empty_string(react_config.get("api_key_env")):
        raise WorkflowValidationError(f"react node {node.id!r} api_key_env must be a non-empty string")
    if provider == "openai-compatible":
        if not _is_non_empty_string(react_config.get("base_url")):
            raise WorkflowValidationError(f"react node {node.id!r} openai-compatible provider requires base_url")
        if not _is_non_empty_string(react_config.get("api_key_env")):
            raise WorkflowValidationError(f"react node {node.id!r} openai-compatible provider requires api_key_env")
        if not _is_supported_react_base_url(str(react_config["base_url"])):
            raise WorkflowValidationError(
                f"react node {node.id!r} openai-compatible provider has unsupported base_url"
            )
        if "timeout_ms" not in react_config:
            raise WorkflowValidationError(f"react node {node.id!r} openai-compatible provider requires timeout_ms")
    _validate_positive_int(react_config, "timeout_ms", f"react node {node.id!r} timeout_ms")

    budget = react_config.get("budget")
    if provider == "openai-compatible" and budget is None:
        raise WorkflowValidationError(f"react node {node.id!r} openai-compatible provider requires budget")
    if budget is not None:
        if not isinstance(budget, dict):
            raise WorkflowValidationError(f"react node {node.id!r} budget must be a mapping")
        _reject_unknown_fields(
            budget,
            {
                "max_tool_calls",
                "max_total_tokens",
                "max_cost_usd",
                "prompt_cost_per_1k_tokens",
                "completion_cost_per_1k_tokens",
            },
            f"react node {node.id!r} budget",
        )
        if provider == "openai-compatible":
            for required_key in (
                "max_total_tokens",
                "max_cost_usd",
                "prompt_cost_per_1k_tokens",
                "completion_cost_per_1k_tokens",
            ):
                if required_key not in budget:
                    raise WorkflowValidationError(
                        f"react node {node.id!r} openai-compatible provider budget requires {required_key}"
                    )
        max_tool_calls = budget.get("max_tool_calls")
        if max_tool_calls is not None:
            if (
                not isinstance(max_tool_calls, int)
                or isinstance(max_tool_calls, bool)
                or max_tool_calls < 1
                or max_tool_calls > max_steps
            ):
                raise WorkflowValidationError(
                    f"react node {node.id!r} budget max_tool_calls must be a positive integer not greater than max_steps"
                )
        _validate_positive_int(budget, "max_total_tokens", f"react node {node.id!r} budget max_total_tokens")
        _validate_non_negative_number(budget, "max_cost_usd", f"react node {node.id!r} budget max_cost_usd")
        _validate_non_negative_number(
            budget,
            "prompt_cost_per_1k_tokens",
            f"react node {node.id!r} budget prompt_cost_per_1k_tokens",
        )
        _validate_non_negative_number(
            budget,
            "completion_cost_per_1k_tokens",
            f"react node {node.id!r} budget completion_cost_per_1k_tokens",
        )

    tools = react_config.get("tools", [])
    if tools is None:
        return
    if not isinstance(tools, list):
        raise WorkflowValidationError(f"react node {node.id!r} tools must be a list")
    for index, tool_config in enumerate(tools):
        if not isinstance(tool_config, dict):
            raise WorkflowValidationError(f"react node {node.id!r} tool[{index}] must be a mapping")
        _validate_react_tool_config(node, index, tool_config)


def _validate_react_tool_config(node: WorkflowNode, index: int, tool_config: dict[str, Any]) -> None:
    adapter = tool_config.get("adapter")
    context = f"react node {node.id!r} tool[{index}]"
    if not _is_non_empty_string(adapter):
        raise WorkflowValidationError(f"{context} requires tool adapter")
    if adapter not in SUPPORTED_TOOL_ADAPTERS:
        raise WorkflowValidationError(f"{context} has unsupported adapter {adapter!r}")

    if adapter == "python":
        _reject_unknown_fields(tool_config, {"adapter", "name", "args"}, f"python {context}")
        if not _is_non_empty_string(tool_config.get("name")):
            raise WorkflowValidationError(f"python {context} requires name")
        if "args" in tool_config and not isinstance(tool_config["args"], dict):
            raise WorkflowValidationError(f"python {context} args must be a mapping")
        return

    if adapter == "shell":
        _reject_unknown_fields(tool_config, {"adapter", "command", "timeout_seconds"}, f"shell {context}")
        if not _is_non_empty_string(tool_config.get("command")):
            raise WorkflowValidationError(f"shell {context} requires non-empty command")
        _validate_timeout(tool_config, f"shell {context}")
        return

    if adapter == "mcp":
        _validate_mcp_tool_config(tool_config, f"mcp {context}")
        return

    _reject_unknown_fields(tool_config, {"adapter", "method", "url", "json", "timeout_seconds"}, f"http {context}")
    url = tool_config.get("url")
    if not _is_non_empty_string(url):
        raise WorkflowValidationError(f"http {context} requires url")
    if not _is_supported_http_url(url):
        raise WorkflowValidationError(f"http {context} has unsupported url {url!r}")
    method = str(tool_config.get("method", "GET")).upper()
    if method not in SUPPORTED_HTTP_METHODS:
        raise WorkflowValidationError(f"http {context} has unsupported method {method!r}")
    _validate_timeout(tool_config, f"http {context}")


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


def _validate_node_contract(node: WorkflowNode) -> None:
    contract = node.config.get("contract")
    if contract is None:
        return
    if not isinstance(contract, dict):
        raise WorkflowValidationError(f"node {node.id!r} contract must be a mapping")
    _reject_unknown_fields(contract, {"output"}, f"node {node.id!r} contract")
    if "output" not in contract:
        raise WorkflowValidationError(f"node {node.id!r} contract requires output")
    output_contract = contract["output"]
    if not isinstance(output_contract, dict):
        raise WorkflowValidationError(f"node {node.id!r} output contract must be a mapping")
    _reject_unknown_fields(output_contract, {"type", "required_fields"}, f"node {node.id!r} output contract")
    expected_type = output_contract.get("type")
    if not _is_non_empty_string(expected_type):
        raise WorkflowValidationError(f"node {node.id!r} output contract requires type")
    if expected_type not in SUPPORTED_CONTRACT_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_CONTRACT_TYPES))
        raise WorkflowValidationError(f"node {node.id!r} output contract type must be one of {allowed}")

    required_fields = output_contract.get("required_fields", {})
    if required_fields is None:
        required_fields = {}
    if required_fields and expected_type != "object":
        raise WorkflowValidationError(
            f"node {node.id!r} output contract required_fields requires type object"
        )
    if not isinstance(required_fields, dict):
        raise WorkflowValidationError(f"node {node.id!r} output contract required_fields must be a mapping")
    for field_name, field_type in required_fields.items():
        if not _is_non_empty_string(field_name):
            raise WorkflowValidationError(f"node {node.id!r} output contract field name must be a non-empty string")
        if not _is_non_empty_string(field_type):
            raise WorkflowValidationError(
                f"node {node.id!r} output contract field {field_name!r} requires type"
            )
        if field_type not in SUPPORTED_CONTRACT_TYPES:
            raise WorkflowValidationError(
                f"node {node.id!r} output contract field {field_name!r} has unsupported type {field_type!r}"
            )


def _validate_node_artifacts(node: WorkflowNode) -> None:
    artifacts = node.config.get("artifacts")
    if artifacts is None:
        return
    if not isinstance(artifacts, list):
        raise WorkflowValidationError(f"node {node.id!r} artifacts must be a list")
    seen_names: set[str] = set()
    for index, artifact in enumerate(artifacts):
        context = f"node {node.id!r} artifact[{index}]"
        if not isinstance(artifact, dict):
            raise WorkflowValidationError(f"{context} must be a mapping")
        _reject_unknown_fields(artifact, {"name", "path", "content_type"}, context)
        name = artifact.get("name")
        if not _is_non_empty_string(name):
            raise WorkflowValidationError(f"{context} requires name")
        if name in seen_names:
            raise WorkflowValidationError(f"node {node.id!r} has duplicate artifact name {name!r}")
        seen_names.add(name)
        if not _is_non_empty_string(artifact.get("path")):
            raise WorkflowValidationError(f"{context} requires path")
        if not _is_non_empty_string(artifact.get("content_type")):
            raise WorkflowValidationError(f"{context} requires content_type")


def _validate_workflow_governance(governance: dict[str, Any]) -> None:
    if not governance:
        return
    if "__invalid__" in governance:
        raise WorkflowValidationError("workflow governance must be a mapping")
    _reject_unknown_fields(
        governance,
        {"max_node_executions", "default_node_timeout_ms", "required_env", "sensitive_paths"},
        "workflow governance",
    )
    _validate_positive_int(
        governance,
        "max_node_executions",
        "workflow governance max_node_executions",
    )
    _validate_positive_int(
        governance,
        "default_node_timeout_ms",
        "workflow governance default_node_timeout_ms",
    )
    _validate_string_list(governance, "required_env", "workflow governance required_env")
    _validate_sensitive_paths(governance.get("sensitive_paths"))


def _validate_node_governance(node: WorkflowNode) -> None:
    governance = node.config.get("governance")
    if governance is None:
        return
    if not isinstance(governance, dict):
        raise WorkflowValidationError(f"node {node.id!r} governance must be a mapping")
    _reject_unknown_fields(governance, {"timeout_ms"}, f"node {node.id!r} governance")
    _validate_positive_int(governance, "timeout_ms", f"node {node.id!r} governance timeout_ms")


def _validate_timeout(config: dict[str, Any], context: str) -> None:
    if "timeout_seconds" not in config:
        return
    timeout = config["timeout_seconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise WorkflowValidationError(f"{context} timeout_seconds must be a positive integer")


def _validate_positive_int(config: dict[str, Any], key: str, context: str) -> None:
    if key not in config:
        return
    value = config[key]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise WorkflowValidationError(f"{context} must be a positive integer")


def _validate_non_negative_number(config: dict[str, Any], key: str, context: str) -> None:
    if key not in config:
        return
    value = config[key]
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise WorkflowValidationError(f"{context} must be a non-negative number")


def _validate_string_list(config: dict[str, Any], key: str, context: str) -> None:
    if key not in config:
        return
    value = config[key]
    if not isinstance(value, list):
        raise WorkflowValidationError(f"{context} must be a list")
    for index, item in enumerate(value):
        if not _is_non_empty_string(item):
            raise WorkflowValidationError(f"{context}[{index}] must be a non-empty string")


def _validate_sensitive_paths(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise WorkflowValidationError("workflow governance sensitive_paths must be a list")
    allowed_roots = {"inputs", "outputs", "node_output", "node_metadata", "tool_invocation"}
    for index, item in enumerate(value):
        context = f"workflow governance sensitive_paths[{index}]"
        if not _is_non_empty_string(item):
            raise WorkflowValidationError(f"{context} must be a non-empty string")
        parts = str(item).split(".")
        if len(parts) < 2 or any(not part.strip() for part in parts):
            raise WorkflowValidationError(f"{context} must include a root and path")
        if parts[0] not in allowed_roots:
            raise WorkflowValidationError(f"{context} has unsupported root {parts[0]!r}")
        if parts[0] in {"node_output", "node_metadata", "tool_invocation"} and len(parts) < 3:
            raise WorkflowValidationError(f"{context} must include root, node, and path")


def _validate_run_validation(index: int, validation: WorkflowValidation, node_ids: set[str]) -> None:
    context = f"validation[{index}]"
    if validation.type not in SUPPORTED_VALIDATION_TYPES:
        raise WorkflowValidationError(f"{context} has unsupported type {validation.type!r}")

    if validation.type == "assertion":
        _validate_assertion_validation(context, validation, node_ids)
        return

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

    if validation.type == "node_contract":
        _reject_unknown_fields(validation.config, {"node", "equals"}, context)
        _validate_validation_node_reference(context, validation, node_ids)
        expected = validation.config.get("equals")
        if not _is_non_empty_string(expected):
            raise WorkflowValidationError(f"{context} node_contract requires equals")
        if expected not in SUPPORTED_CONTRACT_STATUSES:
            raise WorkflowValidationError(f"{context} node_contract has unsupported equals {expected!r}")
        return

    if validation.type == "node_resume_action":
        _reject_unknown_fields(validation.config, {"node", "equals"}, context)
        _validate_validation_node_reference(context, validation, node_ids)
        expected = validation.config.get("equals")
        if not _is_non_empty_string(expected):
            raise WorkflowValidationError(f"{context} node_resume_action requires equals")
        if expected not in SUPPORTED_RESUME_ACTIONS:
            raise WorkflowValidationError(f"{context} node_resume_action has unsupported equals {expected!r}")
        return

    if validation.type == "node_artifact":
        _reject_unknown_fields(validation.config, {"node", "name", "exists"}, context)
        _validate_validation_node_reference(context, validation, node_ids)
        if not _is_non_empty_string(validation.config.get("name")):
            raise WorkflowValidationError(f"{context} node_artifact requires name")
        exists = validation.config.get("exists")
        if exists is not None and not isinstance(exists, bool):
            raise WorkflowValidationError(f"{context} node_artifact exists must be a boolean")
        return

    if validation.type == "node_governance":
        _reject_unknown_fields(validation.config, {"node", "equals"}, context)
        _validate_validation_node_reference(context, validation, node_ids)
        expected = validation.config.get("equals")
        if not _is_non_empty_string(expected):
            raise WorkflowValidationError(f"{context} node_governance requires equals")
        if expected not in SUPPORTED_GOVERNANCE_STATUSES:
            raise WorkflowValidationError(
                f"{context} node_governance has unsupported equals {expected!r}"
            )
        return

    _reject_unknown_fields(validation.config, {"node"}, context)
    _validate_validation_node_reference(context, validation, node_ids)


def _validate_assertion_validation(
    context: str,
    validation: WorkflowValidation,
    node_ids: set[str],
) -> None:
    _reject_unknown_fields(
        validation.config,
        {"source", "node", "path", *SUPPORTED_ASSERTION_OPERATORS},
        context,
    )

    source = validation.config.get("source")
    if not _is_non_empty_string(source):
        raise WorkflowValidationError(f"{context} assertion requires source")
    if source not in SUPPORTED_ASSERTION_SOURCES:
        raise WorkflowValidationError(f"{context} assertion has unsupported source {source!r}")

    path = validation.config.get("path")
    if not _is_non_empty_string(path):
        raise WorkflowValidationError(f"{context} assertion requires path")
    _validate_assertion_path(context, str(path))

    operators = [operator for operator in SUPPORTED_ASSERTION_OPERATORS if operator in validation.config]
    if not operators:
        raise WorkflowValidationError(f"{context} assertion requires one assertion operator")
    if len(operators) > 1:
        raise WorkflowValidationError(f"{context} assertion must use exactly one assertion operator")

    if source in {"node_output", "node_metadata", "tool_invocation"}:
        node_id = validation.config.get("node")
        if not _is_non_empty_string(node_id):
            raise WorkflowValidationError(f"{context} assertion source {source!r} requires node")
        if node_id not in node_ids:
            raise WorkflowValidationError(f"{context} references missing node {node_id!r}")
    elif "node" in validation.config:
        raise WorkflowValidationError(f"{context} assertion source {source!r} does not accept node")

    if "exists" in validation.config and not isinstance(validation.config["exists"], bool):
        raise WorkflowValidationError(f"{context} assertion exists must be a boolean")
    if "value_type" in validation.config:
        expected_type = validation.config["value_type"]
        if not _is_non_empty_string(expected_type):
            raise WorkflowValidationError(f"{context} assertion value_type requires a type")
        if expected_type not in SUPPORTED_CONTRACT_TYPES:
            raise WorkflowValidationError(
                f"{context} assertion value_type has unsupported type {expected_type!r}"
            )


def _validate_assertion_path(context: str, path: str) -> None:
    parts = path.split(".")
    if any(not part.strip() for part in parts):
        raise WorkflowValidationError(f"{context} assertion path must be dot-separated non-empty segments")


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


def _is_supported_react_base_url(url: str) -> bool:
    return url in {"memory://fake-openai", "memory://timeout", "memory://provider-error"} or url.startswith(
        ("http://", "https://")
    )


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


def _compatibility_error_message(compatibility: dict[str, Any]) -> str:
    diagnostics = compatibility.get("diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, dict):
                continue
            if diagnostic.get("severity") == "error" and isinstance(diagnostic.get("message"), str):
                return diagnostic["message"]
    return "workflow compatibility check failed"


def _supported_schema_versions_label() -> str:
    return ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
