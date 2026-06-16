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
        events: list[NodeEvent] = []
        output: Any = None
        node_status = "failed"
        halted = False

        for attempt in range(1, policy["max_attempts"] + 1):
            node_status, output = _execute_node(node, context)
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
