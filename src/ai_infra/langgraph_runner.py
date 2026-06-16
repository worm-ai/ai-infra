from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .config import Workflow, WorkflowNode, validate_workflow
from .store import NodeEvent, RunStore
from .tools import _render_template, execute_tool


class WorkflowRunState(TypedDict, total=False):
    run_id: str
    inputs: dict[str, Any]
    context: Annotated[dict[str, Any], _merge_dicts]
    outputs: Annotated[dict[str, Any], _merge_dicts]
    events: Annotated[list[NodeEvent], operator.add]
    status: Annotated[str, _merge_status]
    halted: Annotated[bool, _merge_halted]
    resume: dict[str, Any]


def compile_workflow(workflow: Workflow, store: RunStore | None = None) -> Any:
    validate_workflow(workflow)

    graph = StateGraph(WorkflowRunState)
    successors = _successors(workflow)
    predecessors = _predecessors(workflow)

    for node in workflow.nodes:
        graph.add_node(node.id, _node_executor(node, store))

    graph.add_edge(START, workflow.entrypoint)
    for node in workflow.nodes:
        for target in _node_targets(node, successors):
            if len(predecessors.get(target, [])) == 1:
                graph.add_edge(node.id, target)
        if not _node_targets(node, successors):
            graph.add_edge(node.id, END)

    for target, sources in predecessors.items():
        if len(sources) > 1:
            graph.add_edge(sources, target)

    return graph.compile()


def _node_executor(node: WorkflowNode, store: RunStore | None):
    def execute(state: WorkflowRunState) -> WorkflowRunState:
        if state.get("halted"):
            return {"halted": True, "status": "failed"}

        inputs = dict(state.get("inputs") or {})
        context = {**inputs, **dict(state.get("context") or {})}
        run_id = str(state.get("run_id") or "")
        policy = _node_policy(node)
        resume_action = _resume_action(node.id, state)
        if resume_action == "skipped":
            return _skipped_node_state(node, state, context, run_id, store)

        events: list[NodeEvent] = []
        output: Any = None
        node_status = "failed"
        halted = False

        for attempt in range(1, policy["max_attempts"] + 1):
            node_status, output = _execute_node(node, context)
            contract_evidence = _evaluate_output_contract(node, output)
            contract_error: str | None = None
            if contract_evidence is not None:
                contract_failed = contract_evidence["status"] == "failed"
                if contract_failed:
                    node_status = "failed"
                    contract_error = _contract_failure_message(node.id, contract_evidence)
                if contract_failed:
                    if not isinstance(output, dict):
                        output = {"result": output}
                    output = dict(output)
                    output["error"] = contract_error
            records_policy = _has_policy(node) or policy["max_attempts"] > 1
            output = _attempt_output(
                output,
                attempt,
                policy,
                node_status,
                force_mapping=records_policy,
            )
            final_attempt = attempt == policy["max_attempts"] or node_status == "completed"
            event_output = _event_output(output, attempt, policy, node_status)
            event_metadata: dict[str, Any] = {}
            if contract_evidence is not None:
                event_metadata["contract"] = {"output": contract_evidence}
            if resume_action is not None:
                event_metadata["resume"] = {"action": resume_action}
            if contract_error is not None:
                event_output.setdefault("error", contract_error)
            outcome = _policy_outcome(node_status, attempt, policy, final_attempt)
            if records_policy:
                event_output["policy_outcome"] = outcome
            if isinstance(output, dict):
                output = dict(output)
                if records_policy:
                    output["policy_outcome"] = outcome
            event = NodeEvent(
                run_id=run_id,
                node_id=node.id,
                status=node_status,
                input={**context, node.id: event_output},
                output=event_output,
                metadata=event_metadata,
            )
            events.append(event)
            if store is not None and event.run_id:
                store.add_event(event)
            if node_status == "completed":
                break

        if node_status == "failed" and policy["on_failure"] == "halt":
            halted = True
        return {
            "context": {node.id: output},
            "outputs": {node.id: output},
            "events": events,
            "status": "completed" if node_status == "failed" and not halted else node_status,
            "halted": halted,
        }

    return execute


def _skipped_node_state(
    node: WorkflowNode,
    state: WorkflowRunState,
    context: dict[str, Any],
    run_id: str,
    store: RunStore | None,
) -> WorkflowRunState:
    resume = dict(state.get("resume") or {})
    outputs = dict(resume.get("outputs") or {})
    events = dict(resume.get("events") or {})
    output = outputs[node.id]
    source_event = events.get(node.id)
    event_output = source_event.output if isinstance(source_event, NodeEvent) else _event_output(
        output,
        1,
        _node_policy(node),
        "completed",
    )
    event_metadata = dict(source_event.metadata) if isinstance(source_event, NodeEvent) else {}
    event_metadata["resume"] = {
        "action": "skipped",
        "source_event_status": source_event.status if isinstance(source_event, NodeEvent) else "completed",
    }
    event = NodeEvent(
        run_id=run_id,
        node_id=node.id,
        status="skipped",
        input={**context, node.id: event_output},
        output=event_output,
        metadata=event_metadata,
    )
    if store is not None and event.run_id:
        store.add_event(event)
    return {
        "context": {node.id: output},
        "outputs": {node.id: output},
        "events": [event],
        "status": "completed",
        "halted": False,
    }


def _resume_action(node_id: str, state: WorkflowRunState) -> str | None:
    resume = state.get("resume")
    if not isinstance(resume, dict) or not resume.get("enabled"):
        return None
    outputs = resume.get("outputs")
    if isinstance(outputs, dict) and node_id in outputs:
        return "skipped"
    attempted = resume.get("attempted")
    if isinstance(attempted, set) and node_id in attempted:
        return "rerun"
    if isinstance(attempted, list) and node_id in attempted:
        return "rerun"
    return "run"


def _merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


def _merge_status(left: str | None, right: str | None) -> str:
    if right == "failed" or left == "failed":
        return "failed"
    return right or left or "completed"


def _merge_halted(left: bool | None, right: bool | None) -> bool:
    return bool(left) or bool(right)


def _execute_node(node: WorkflowNode, context: dict[str, Any]) -> tuple[str, Any]:
    if node.type == "template":
        if node.template is None:
            raise RuntimeError(f"template node {node.id!r} requires template")
        return "completed", _render_template(node.template, context)
    if node.type == "tool":
        tool_config = node.config.get("tool")
        if not isinstance(tool_config, dict):
            raise RuntimeError(f"tool node {node.id!r} requires tool config")
        execution = execute_tool(tool_config, context)
        return execution.status, execution.output
    raise RuntimeError(f"node {node.id!r} has no executable runner for type {node.type!r}")


def _node_policy(node: WorkflowNode) -> dict[str, int | str]:
    raw_policy = node.config.get("policy")
    if not isinstance(raw_policy, dict):
        return {"on_failure": "halt", "max_attempts": 1}
    return {
        "on_failure": str(raw_policy.get("on_failure", "halt")),
        "max_attempts": int(raw_policy.get("max_attempts", 1)),
    }


def _has_policy(node: WorkflowNode) -> bool:
    return isinstance(node.config.get("policy"), dict)


def _attempt_output(
    output: Any,
    attempt: int,
    policy: dict[str, int | str],
    status: str,
    *,
    force_mapping: bool,
) -> Any:
    if not force_mapping and not isinstance(output, dict):
        return output
    if not isinstance(output, dict):
        output = {"result": output}
    enriched = dict(output)
    enriched["attempt"] = attempt
    enriched["attempts"] = attempt
    enriched["max_attempts"] = policy["max_attempts"]
    enriched["on_failure"] = policy["on_failure"]
    enriched["node_status"] = status
    return enriched


def _event_output(
    output: Any,
    attempt: int,
    policy: dict[str, int | str],
    status: str,
) -> dict[str, Any]:
    if isinstance(output, dict):
        return dict(output)
    return {
        "result": output,
        "attempt": attempt,
        "attempts": attempt,
        "max_attempts": policy["max_attempts"],
        "on_failure": policy["on_failure"],
        "node_status": status,
    }


def _policy_outcome(
    node_status: str,
    attempt: int,
    policy: dict[str, int | str],
    final_attempt: bool,
) -> str:
    max_attempts = int(policy["max_attempts"])
    if node_status == "completed":
        return "retry_succeeded" if attempt > 1 else "completed"
    if not final_attempt and attempt < max_attempts:
        return "retrying"
    if policy["on_failure"] == "continue":
        return "continued_after_failure"
    return "retry_exhausted"


def _evaluate_output_contract(node: WorkflowNode, output: Any) -> dict[str, Any] | None:
    contract = node.config.get("contract")
    if not isinstance(contract, dict):
        return None
    output_contract = contract.get("output")
    if not isinstance(output_contract, dict):
        return None

    expected_type = str(output_contract.get("type", ""))
    required_fields = output_contract.get("required_fields", {})
    if not isinstance(required_fields, dict):
        required_fields = {}

    missing_fields: list[str] = []
    type_errors: list[dict[str, str]] = []
    if not _matches_contract_type(output, expected_type):
        type_errors.append(
            {
                "field": "$",
                "expected": expected_type,
                "actual": _contract_type_name(output),
            }
        )
    elif expected_type == "object":
        for field_name, field_type in required_fields.items():
            field_key = str(field_name)
            if not isinstance(output, dict) or field_key not in output:
                missing_fields.append(field_key)
                continue
            actual_value = output[field_key]
            expected_field_type = str(field_type)
            if not _matches_contract_type(actual_value, expected_field_type):
                type_errors.append(
                    {
                        "field": field_key,
                        "expected": expected_field_type,
                        "actual": _contract_type_name(actual_value),
                    }
                )

    status = "failed" if missing_fields or type_errors else "passed"
    return {
        "status": status,
        "type": expected_type,
        "required_fields": dict(required_fields),
        "missing_fields": missing_fields,
        "type_errors": type_errors,
    }


def _contract_failure_message(node_id: str, evidence: dict[str, Any]) -> str:
    missing_fields = evidence.get("missing_fields")
    if isinstance(missing_fields, list) and missing_fields:
        missing = ", ".join(f"missing field {field!r}" for field in missing_fields)
        return f"output contract failed for node {node_id!r}: {missing}"
    type_errors = evidence.get("type_errors")
    if isinstance(type_errors, list) and type_errors:
        first = type_errors[0]
        if isinstance(first, dict):
            return (
                f"output contract failed for node {node_id!r}: field {first.get('field')!r} "
                f"expected {first.get('expected')!r}, got {first.get('actual')!r}"
            )
    return f"output contract failed for node {node_id!r}"


def _matches_contract_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int | float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return False


def _contract_type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return type(value).__name__


def _successors(workflow: Workflow) -> dict[str, list[str]]:
    successors: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
    for edge in workflow.edges:
        successors.setdefault(edge.source, []).append(edge.target)
    return successors


def _predecessors(workflow: Workflow) -> dict[str, list[str]]:
    predecessors: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
    for node in workflow.nodes:
        if node.next:
            predecessors.setdefault(node.next, []).append(node.id)
    for edge in workflow.edges:
        predecessors.setdefault(edge.target, []).append(edge.source)
    return predecessors


def _node_targets(node: WorkflowNode, successors: dict[str, list[str]]) -> list[str]:
    if node.next:
        return [node.next]
    return successors.get(node.id, [])
