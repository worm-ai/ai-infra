from __future__ import annotations

from typing import Any

from .runtime import default_store
from .store import NodeEvent, RunStore


def build_run_report(run_id: str, store: RunStore | None = None) -> dict[str, Any]:
    run = (store or default_store()).get_run(run_id)
    timeline = [_node_report(index, event) for index, event in enumerate(run.events, start=1)]
    failed_events = [event for event in run.events if event.status == "failed"]

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "inputs": run.inputs,
        "input_summary": _value_summary(run.inputs),
        "outputs": run.outputs,
        "output_summary": _value_summary(run.outputs),
        "summary": {
            "completed": sum(1 for event in run.events if event.status == "completed"),
            "failed": len(failed_events),
            "total_nodes": len(run.events),
        },
        "failure": _failure_report(failed_events[0]) if failed_events else None,
        "timeline": timeline,
    }


def _node_report(index: int, event: NodeEvent) -> dict[str, Any]:
    return {
        "sequence": index,
        "node_id": event.node_id,
        "status": event.status,
        "duration_ms": _duration_ms(event.output),
        "input_summary": _value_summary(event.input),
        "output_summary": _value_summary(event.output),
        "output": event.output,
        "tool": _tool_report(event.output),
    }


def _failure_report(event: NodeEvent) -> dict[str, str]:
    output = event.output if isinstance(event.output, dict) else {}
    message = str(output.get("error") or f"node {event.node_id!r} failed")
    return {"node_id": event.node_id, "message": message}


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
