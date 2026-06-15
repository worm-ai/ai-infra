from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .config import Workflow, WorkflowNode, validate_workflow
from .store import NodeEvent, RunStore
from .tools import execute_tool


class WorkflowRunState(TypedDict, total=False):
    run_id: str
    inputs: dict[str, Any]
    context: Annotated[dict[str, Any], _merge_dicts]
    outputs: Annotated[dict[str, Any], _merge_dicts]
    events: Annotated[list[NodeEvent], operator.add]
    status: Annotated[str, _merge_status]


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
        inputs = dict(state.get("inputs") or {})
        context = {**inputs, **dict(state.get("context") or {})}

        node_status, output = _execute_node(node, context)
        event_input = {**context, node.id: output}

        event = NodeEvent(
            run_id=str(state.get("run_id") or ""),
            node_id=node.id,
            status=node_status,
            input=event_input,
            output=output,
        )
        if store is not None and event.run_id:
            store.add_event(event)

        return {
            "context": {node.id: output},
            "outputs": {node.id: output},
            "events": [event],
            "status": node_status,
        }

    return execute


def _merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


def _merge_status(left: str | None, right: str | None) -> str:
    if right == "failed" or left == "failed":
        return "failed"
    return right or left or "completed"


def _execute_node(node: WorkflowNode, context: dict[str, Any]) -> tuple[str, Any]:
    if node.type == "template":
        if node.template is None:
            raise RuntimeError(f"template node {node.id!r} requires template")
        return "completed", node.template.format(**context)
    if node.type == "tool":
        tool_config = node.config.get("tool")
        if not isinstance(tool_config, dict):
            raise RuntimeError(f"tool node {node.id!r} requires tool config")
        execution = execute_tool(tool_config, context)
        return execution.status, execution.output
    raise RuntimeError(f"node {node.id!r} has no executable runner for type {node.type!r}")


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
