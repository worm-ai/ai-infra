from __future__ import annotations

from typing import Any

from .runtime import default_store
from .store import NodeEvent, RunProvenance, RunStore


def build_run_report(run_id: str, store: RunStore | None = None) -> dict[str, Any]:
    run = (store or default_store()).get_run(run_id)
    timeline = [
        _node_report(index, events)
        for index, events in enumerate(_events_by_node(run.events), start=1)
    ]
    failed_nodes = [node for node in timeline if node["status"] == "failed"]
    retry_events = [
        event
        for event in run.events
        if isinstance(event.output, dict) and int(event.output.get("attempt", 1)) > 1
    ]

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "inputs": run.inputs,
        "provenance": _provenance_report(run.provenance),
        "input_summary": _value_summary(run.inputs),
        "outputs": run.outputs,
        "output_summary": _value_summary(run.outputs),
        "summary": {
            "completed": sum(1 for node in timeline if node["status"] == "completed"),
            "failed": len(failed_nodes),
            "retried": len(retry_events),
            "total_nodes": len(timeline),
            "total_events": len(run.events),
        },
        "failure": _failure_report(failed_nodes[0]) if failed_nodes else None,
        "timeline": timeline,
    }


def _provenance_report(provenance: RunProvenance | None) -> dict[str, Any] | None:
    if provenance is None:
        return None
    return {
        "workflow_source_path": provenance.workflow_source_path,
        "workflow_snapshot": provenance.workflow_snapshot,
        "workflow_sha256": provenance.workflow_sha256,
        "workflow_snapshot_present": bool(provenance.workflow_snapshot),
        "inputs_sha256": provenance.inputs_sha256,
        "git_commit": provenance.git_commit,
        "environment": provenance.environment,
    }


def _events_by_node(events: list[NodeEvent]) -> list[list[NodeEvent]]:
    grouped: list[list[NodeEvent]] = []
    indexes: dict[str, int] = {}
    for event in events:
        if event.node_id not in indexes:
            indexes[event.node_id] = len(grouped)
            grouped.append([])
        grouped[indexes[event.node_id]].append(event)
    return grouped


def _node_report(index: int, events: list[NodeEvent]) -> dict[str, Any]:
    event = events[-1]
    return {
        "sequence": index,
        "node_id": event.node_id,
        "status": event.status,
        "attempts": len(events),
        "policy": _policy_report(event.output),
        "attempt_events": [_attempt_event_report(attempt) for attempt in events],
        "duration_ms": _duration_ms(event.output),
        "input_summary": _value_summary(event.input),
        "output_summary": _value_summary(event.output),
        "output": event.output,
        "tool": _tool_report(event.output),
    }


def _failure_report(node: dict[str, Any]) -> dict[str, str]:
    output = node["output"] if isinstance(node["output"], dict) else {}
    message = str(output.get("error") or f"node {node['node_id']!r} failed")
    failure = {"node_id": node["node_id"], "message": message}
    policy_outcome = output.get("policy_outcome")
    if isinstance(policy_outcome, str):
        failure["policy_outcome"] = policy_outcome
    return failure


def _attempt_event_report(event: NodeEvent) -> dict[str, Any]:
    output = event.output if isinstance(event.output, dict) else {}
    return {
        "status": event.status,
        "attempt": output.get("attempt", 1),
        "policy_outcome": output.get("policy_outcome"),
        "duration_ms": _duration_ms(output),
        "error": output.get("error"),
    }


def _policy_report(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"on_failure": "halt", "max_attempts": 1, "outcome": "completed"}
    return {
        "on_failure": output.get("on_failure", "halt"),
        "max_attempts": output.get("max_attempts", 1),
        "outcome": output.get("policy_outcome", "completed"),
    }


def _duration_ms(output: Any) -> int | None:
    if isinstance(output, dict) and isinstance(output.get("duration_ms"), int):
        return output["duration_ms"]
    return None


def _tool_report(output: Any) -> dict[str, Any] | None:
    if not isinstance(output, dict) or "adapter" not in output:
        return None
    keys = [
        "adapter",
        "name",
        "command",
        "method",
        "url",
        "status_code",
        "exit_code",
        "error",
        "stdout",
        "stderr",
        "duration_ms",
    ]
    return {key: output[key] for key in keys if key in output}


def _value_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in value.keys())}
    if isinstance(value, list):
        return {"type": "array", "items": len(value)}
    return {"type": type(value).__name__}
