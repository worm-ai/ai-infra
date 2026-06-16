from __future__ import annotations

from typing import Any

from .artifacts import event_artifacts
from .runtime import default_store
from .store import NodeEvent, RunProvenance, RunStore


def build_run_report(run_id: str, store: RunStore | None = None) -> dict[str, Any]:
    run = (store or default_store()).get_run(run_id)
    timeline = [
        _node_report(index, events)
        for index, events in enumerate(_events_by_node(run.events), start=1)
    ]
    failed_nodes = [
        node
        for node in timeline
        if node["status"] == "failed"
        or _governance_status(node.get("governance")) in ("timeout", "budget_exhausted", "aborted")
    ]
    retry_events = [
        event
        for event in run.events
        if isinstance(event.output, dict) and int(event.output.get("attempt", 1)) > 1
    ]

    summary: dict[str, Any] = {
        "completed": sum(1 for node in timeline if node["status"] in ("completed", "skipped")),
        "failed": len(failed_nodes),
        "retried": len(retry_events),
        "total_nodes": len(timeline),
        "total_events": len(run.events),
    }
    contract_summary = _contract_summary(timeline)
    if contract_summary is not None:
        summary["contracts"] = contract_summary
    resume_summary = _resume_summary(timeline)
    if resume_summary is not None:
        summary["resume"] = resume_summary
    artifact_summary = _artifact_summary(timeline)
    if artifact_summary is not None:
        summary["artifacts"] = artifact_summary
    governance_summary = _governance_summary(timeline)
    if governance_summary is not None:
        summary["governance"] = governance_summary

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "inputs": run.inputs,
        "provenance": _provenance_report(run.provenance),
        "input_summary": _value_summary(run.inputs),
        "outputs": run.outputs,
        "output_summary": _value_summary(run.outputs),
        "summary": summary,
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
        "attempts": sum(1 for attempt in events if attempt.status != "skipped"),
        "policy": _policy_report(event.output),
        "attempt_events": [_attempt_event_report(attempt) for attempt in events],
        "duration_ms": _duration_ms(event.output),
        "input_summary": _value_summary(event.input),
        "output_summary": _value_summary(event.output),
        "output": event.output,
        "tool": _tool_report(event.output),
        "contract": _contract_report(event),
        "resume": _resume_report(event),
        "artifacts": _artifact_report(event),
        "governance": _governance_report(event),
    }


def _failure_report(node: dict[str, Any]) -> dict[str, str]:
    output = node["output"] if isinstance(node["output"], dict) else {}
    message = str(output.get("error") or f"node {node['node_id']!r} failed")
    failure = {"node_id": node["node_id"], "message": message}
    policy_outcome = output.get("policy_outcome")
    if isinstance(policy_outcome, str):
        failure["policy_outcome"] = policy_outcome
    contract_status = _contract_status(node.get("contract"))
    if contract_status == "failed":
        failure["contract_status"] = contract_status
    governance_status = _governance_status(node.get("governance"))
    if governance_status in ("timeout", "budget_exhausted", "aborted"):
        failure["governance_status"] = governance_status
    return failure


def _attempt_event_report(event: NodeEvent) -> dict[str, Any]:
    output = event.output if isinstance(event.output, dict) else {}
    return {
        "status": event.status,
        "attempt": output.get("attempt", 1),
        "policy_outcome": output.get("policy_outcome"),
        "contract_status": _contract_status(event.metadata.get("contract")),
        "resume_action": _resume_action(event.metadata.get("resume")),
        "governance_status": _governance_status(event.metadata.get("governance")),
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
    invocation = output.get("tool_invocation")
    if isinstance(invocation, dict):
        report = dict(invocation)
        for key in [
            "name",
            "command",
            "method",
            "url",
            "status_code",
            "exit_code",
            "stdout",
            "stderr",
        ]:
            if key in output and key not in report:
                report[key] = output[key]
        return report
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


def _contract_report(event: NodeEvent) -> dict[str, Any] | None:
    contract = event.metadata.get("contract")
    if not isinstance(contract, dict):
        return None
    return contract


def _resume_report(event: NodeEvent) -> dict[str, Any] | None:
    resume = event.metadata.get("resume")
    if not isinstance(resume, dict):
        return None
    return resume


def _artifact_report(event: NodeEvent) -> list[dict[str, Any]]:
    return event_artifacts(event)


def _governance_report(event: NodeEvent) -> dict[str, Any] | None:
    governance = event.metadata.get("governance")
    if not isinstance(governance, dict):
        return None
    return governance


def _governance_summary(timeline: list[dict[str, Any]]) -> dict[str, int] | None:
    counts = {"within_limits": 0, "timeout": 0, "budget_exhausted": 0, "aborted": 0, "skipped": 0}
    saw_governance = False
    for node in timeline:
        governance_status = _governance_status(node.get("governance"))
        if governance_status in ("within_limits", "timeout", "budget_exhausted", "aborted"):
            counts[governance_status] += 1
            saw_governance = True
        if governance_status in ("budget_exhausted", "aborted") or node.get("status") == "skipped":
            counts["skipped"] += 1
    return counts if saw_governance else None


def _governance_status(governance: Any) -> str | None:
    if not isinstance(governance, dict):
        return None
    status = governance.get("status")
    return status if isinstance(status, str) else None


def _artifact_summary(timeline: list[dict[str, Any]]) -> dict[str, int] | None:
    counts = {"declared": 0, "present": 0, "missing": 0}
    for node in timeline:
        artifacts = node.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            counts["declared"] += 1
            if artifact.get("exists") is True:
                counts["present"] += 1
            else:
                counts["missing"] += 1
    return counts if counts["declared"] else None


def _resume_summary(timeline: list[dict[str, Any]]) -> dict[str, int] | None:
    counts = {"skipped": 0, "rerun": 0, "run": 0}
    saw_resume = False
    for node in timeline:
        action = _resume_action(node.get("resume"))
        if action in counts:
            counts[action] += 1
            saw_resume = True
    return counts if saw_resume else None


def _resume_action(resume: Any) -> str | None:
    if not isinstance(resume, dict):
        return None
    action = resume.get("action")
    return action if isinstance(action, str) else None


def _contract_summary(timeline: list[dict[str, Any]]) -> dict[str, int] | None:
    counts = {"passed": 0, "failed": 0, "unchecked": 0}
    saw_contract = False
    for node in timeline:
        contract = node.get("contract")
        if contract is None:
            counts["unchecked"] += 1
            continue
        status = _contract_status(contract)
        if status in ("passed", "failed"):
            counts[status] += 1
            saw_contract = True
        else:
            counts["unchecked"] += 1
    if not saw_contract:
        return None
    return counts


def _contract_status(contract: Any) -> str | None:
    if not isinstance(contract, dict):
        return None
    output_contract = contract.get("output")
    if not isinstance(output_contract, dict):
        return None
    status = output_contract.get("status")
    return status if isinstance(status, str) else None


def _value_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in value.keys())}
    if isinstance(value, list):
        return {"type": "array", "items": len(value)}
    return {"type": type(value).__name__}
