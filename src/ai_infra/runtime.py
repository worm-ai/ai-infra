from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import current_file_sha256, find_artifact, latest_node_artifacts
from .config import Workflow, load_workflow_from_source, validate_workflow
from .langgraph_runner import compile_workflow
from .provenance import build_run_provenance, sha256_text
from .store import NodeEvent, RunStore, StoredRun, VerificationCheck


@dataclass(frozen=True)
class RunResult:
    run_id: str
    workflow_id: str
    status: str
    outputs: dict[str, Any]
    events: list[NodeEvent]


@dataclass(frozen=True)
class VerificationResult:
    run_id: str
    status: str
    checks: list[VerificationCheck]


def default_store(state_dir: str | Path = ".ai-infra") -> RunStore:
    return RunStore(Path(state_dir) / "runs.sqlite")


def run_workflow(workflow: Workflow, inputs: dict[str, Any], store: RunStore | None = None) -> RunResult:
    validate_workflow(workflow)
    run_store = store or default_store()
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    workflow_source_path = str(workflow.source_path) if workflow.source_path else None
    provenance = build_run_provenance(workflow, inputs)

    run_store.save_run(
        StoredRun(
            run_id=run_id,
            workflow_id=workflow.id,
            status="running",
            inputs=inputs,
            outputs={},
            workflow_source_path=workflow_source_path,
            provenance=provenance,
        )
    )

    graph = compile_workflow(workflow, store=run_store)
    state = graph.invoke(
        {
            "run_id": run_id,
            "inputs": inputs,
            "context": dict(inputs),
            "outputs": {},
            "events": [],
            "status": "running",
        }
    )
    outputs = dict(state.get("outputs") or {})
    events = list(state.get("events") or [])
    status = str(state.get("status") or "completed")

    run_store.save_run(
        StoredRun(
            run_id=run_id,
            workflow_id=workflow.id,
            status=status,
            inputs=inputs,
            outputs=outputs,
            workflow_source_path=workflow_source_path,
            provenance=provenance,
        )
    )
    return RunResult(run_id=run_id, workflow_id=workflow.id, status=status, outputs=outputs, events=events)


def resume_workflow(run_id: str, workflow: Workflow, store: RunStore | None = None) -> RunResult:
    validate_workflow(workflow)
    run_store = store or default_store()
    stored = run_store.get_run(run_id)
    _validate_resume_compatibility(stored, workflow)

    workflow_source_path = str(workflow.source_path) if workflow.source_path else None
    provenance = stored.provenance
    resume_state = _resume_state(stored, workflow)

    run_store.save_run(
        StoredRun(
            run_id=run_id,
            workflow_id=stored.workflow_id,
            status="running",
            inputs=stored.inputs,
            outputs=stored.outputs,
            workflow_source_path=workflow_source_path,
            provenance=provenance,
        )
    )

    graph = compile_workflow(workflow, store=run_store)
    state = graph.invoke(
        {
            "run_id": run_id,
            "inputs": stored.inputs,
            "context": dict(stored.inputs),
            "outputs": {},
            "events": [],
            "status": "running",
            "resume": resume_state,
        }
    )
    outputs = dict(state.get("outputs") or {})
    events = list(state.get("events") or [])
    status = str(state.get("status") or "completed")

    run_store.save_run(
        StoredRun(
            run_id=run_id,
            workflow_id=stored.workflow_id,
            status=status,
            inputs=stored.inputs,
            outputs=outputs,
            workflow_source_path=workflow_source_path,
            provenance=provenance,
        )
    )
    return RunResult(run_id=run_id, workflow_id=workflow.id, status=status, outputs=outputs, events=events)


def get_run(run_id: str, store: RunStore | None = None) -> StoredRun:
    return (store or default_store()).get_run(run_id)


def validate_run(run_id: str, workflow: Workflow, store: RunStore | None = None) -> VerificationResult:
    validate_workflow(workflow)
    run_store = store or default_store()
    stored = run_store.get_run(run_id)
    checks = _evaluate_workflow_validations(workflow, stored)
    return _record_verification(run_store, run_id, checks)


def validate_stored_run(run_id: str, store: RunStore | None = None) -> VerificationResult:
    run_store = store or default_store()
    stored = run_store.get_run(run_id)
    if stored.provenance is None:
        raise RuntimeError(f"run {run_id!r} does not include immutable workflow provenance")
    workflow = load_workflow_from_source(
        stored.provenance.workflow_snapshot,
        source_path=stored.provenance.workflow_source_path,
    )
    if workflow.id != stored.workflow_id:
        raise RuntimeError(
            f"stored run references workflow {stored.workflow_id!r}, "
            f"but snapshot contains workflow {workflow.id!r}"
        )
    checks = [_evaluate_workflow_source_integrity(stored)]
    checks.extend(_evaluate_workflow_validations(workflow, stored))
    return _record_verification(run_store, run_id, checks)


def _evaluate_workflow_validations(workflow: Workflow, stored: StoredRun) -> list[VerificationCheck]:
    return [
        _evaluate_validation(validation.type, validation.config, stored)
        for validation in workflow.validations
    ]


def _record_verification(
    run_store: RunStore,
    run_id: str,
    checks: list[VerificationCheck],
) -> VerificationResult:
    status = "passed" if all(check.status == "passed" for check in checks) else "failed"
    run_store.add_verification(run_id, status, checks)
    return VerificationResult(run_id=run_id, status=status, checks=checks)


def _evaluate_workflow_source_integrity(run: StoredRun) -> VerificationCheck:
    provenance = run.provenance
    if provenance is None:
        return VerificationCheck(
            type="workflow_source_integrity",
            status="failed",
            message="run does not include immutable workflow provenance",
        )
    if not provenance.workflow_source_path:
        return VerificationCheck(
            type="workflow_source_integrity",
            status="passed",
            message=(
                "workflow source path is unavailable; "
                f"validated persisted snapshot sha256 {provenance.workflow_sha256}"
            ),
        )

    workflow_source = Path(provenance.workflow_source_path)
    if not workflow_source.exists():
        return VerificationCheck(
            type="workflow_source_integrity",
            status="failed",
            message=f"workflow source is unavailable; run snapshot sha256 is {provenance.workflow_sha256}",
        )

    current_sha256 = sha256_text(workflow_source.read_text(encoding="utf-8"))
    if current_sha256 == provenance.workflow_sha256:
        return VerificationCheck(
            type="workflow_source_integrity",
            status="passed",
            message=f"workflow source matches run snapshot sha256 {provenance.workflow_sha256}",
        )
    return VerificationCheck(
        type="workflow_source_integrity",
        status="failed",
        message=(
            "workflow source changed since run: "
            f"current sha256 {current_sha256}, run snapshot sha256 {provenance.workflow_sha256}"
        ),
    )


def _evaluate_validation(validation_type: str, config: dict[str, Any], run: StoredRun) -> VerificationCheck:
    if validation_type == "assertion":
        return _evaluate_assertion_validation(config, run)
    if validation_type == "run_status":
        expected = config.get("equals")
        passed = run.status == expected
        return VerificationCheck(
            type=validation_type,
            status="passed" if passed else "failed",
            message=f"run status is {run.status!r}, expected {expected!r}",
        )
    if validation_type == "node_completed":
        node_id = config.get("node")
        passed = any(event.node_id == node_id and event.status == "completed" for event in run.events)
        return VerificationCheck(
            type=validation_type,
            status="passed" if passed else "failed",
            message=f"node {node_id!r} completed" if passed else f"node {node_id!r} did not complete",
        )
    if validation_type == "node_failed":
        node_id = config.get("node")
        passed = any(event.node_id == node_id and event.status == "failed" for event in run.events)
        return VerificationCheck(
            type=validation_type,
            status="passed" if passed else "failed",
            message=f"node {node_id!r} failed" if passed else f"node {node_id!r} did not fail",
        )
    if validation_type == "node_attempts":
        node_id = config.get("node")
        expected = config.get("equals")
        attempts = [
            event
            for event in run.events
            if event.node_id == node_id and event.status != "skipped"
        ]
        actual = len(attempts)
        passed = actual == expected
        return VerificationCheck(
            type=validation_type,
            status="passed" if passed else "failed",
            message=f"node {node_id!r} attempts is {actual}, expected {expected!r}",
        )
    if validation_type == "node_policy_outcome":
        node_id = config.get("node")
        expected = config.get("equals")
        attempts = [event for event in run.events if event.node_id == node_id]
        actual = _latest_policy_outcome(attempts)
        passed = actual == expected
        return VerificationCheck(
            type=validation_type,
            status="passed" if passed else "failed",
            message=f"node {node_id!r} policy outcome is {actual!r}, expected {expected!r}",
        )
    if validation_type == "node_contract":
        node_id = config.get("node")
        expected = config.get("equals")
        attempts = [event for event in run.events if event.node_id == node_id]
        actual = _latest_contract_status(attempts)
        passed = actual == expected
        return VerificationCheck(
            type=validation_type,
            status="passed" if passed else "failed",
            message=f"node {node_id!r} contract status is {actual!r}, expected {expected!r}",
        )
    if validation_type == "node_resume_action":
        node_id = config.get("node")
        expected = config.get("equals")
        attempts = [event for event in run.events if event.node_id == node_id]
        actual = _latest_resume_action(attempts)
        passed = actual == expected
        return VerificationCheck(
            type=validation_type,
            status="passed" if passed else "failed",
            message=f"node {node_id!r} resume action is {actual!r}, expected {expected!r}",
        )
    if validation_type == "node_artifact":
        node_id = config.get("node")
        name = config.get("name")
        expected_exists = config.get("exists", True)
        artifacts = latest_node_artifacts(run, str(node_id))
        artifact = find_artifact(artifacts, str(name))
        if artifact is None:
            return VerificationCheck(
                type=validation_type,
                status="failed",
                message=f"node {node_id!r} artifact {name!r} evidence is missing",
            )
        recorded_exists = bool(artifact.get("exists"))
        if recorded_exists != expected_exists:
            return VerificationCheck(
                type=validation_type,
                status="failed",
                message=(
                    f"node {node_id!r} artifact {name!r} exists is {recorded_exists}, "
                    f"expected {expected_exists!r}"
                ),
            )
        if not expected_exists:
            return VerificationCheck(
                type=validation_type,
                status="passed",
                message=f"node {node_id!r} artifact {name!r} absence matches expectation",
            )
        path = str(artifact.get("stored_path") or artifact.get("path", ""))
        current_sha256 = current_file_sha256(path)
        recorded_sha256 = artifact.get("sha256")
        if current_sha256 is None:
            return VerificationCheck(
                type=validation_type,
                status="failed",
                message=f"node {node_id!r} artifact {name!r} file is missing at {path!r}",
            )
        if current_sha256 != recorded_sha256:
            return VerificationCheck(
                type=validation_type,
                status="failed",
                message=(
                    f"node {node_id!r} artifact {name!r} sha256 changed: "
                    f"current {current_sha256}, run evidence {recorded_sha256}"
                ),
            )
        return VerificationCheck(
            type=validation_type,
            status="passed",
            message=f"node {node_id!r} artifact {name!r} exists with sha256 {recorded_sha256}",
        )
    if validation_type == "node_governance":
        node_id = config.get("node")
        expected = config.get("equals")
        attempts = [event for event in run.events if event.node_id == node_id]
        actual = _latest_governance_status(attempts)
        passed = actual == expected
        return VerificationCheck(
            type=validation_type,
            status="passed" if passed else "failed",
            message=f"node {node_id!r} governance status is {actual!r}, expected {expected!r}",
        )
    return VerificationCheck(type=validation_type, status="failed", message="unsupported validation type")


def _evaluate_assertion_validation(config: dict[str, Any], run: StoredRun) -> VerificationCheck:
    source = str(config.get("source", ""))
    node_id = config.get("node")
    path = str(config.get("path", ""))
    display_path = _assertion_display_path(source, node_id, path)
    source_value, source_found = _assertion_source_value(source, node_id, run)
    if not source_found:
        return VerificationCheck(
            type="assertion",
            status="failed",
            message=f"assertion {display_path} source is missing",
        )

    actual, found = _lookup_assertion_path(source_value, path)
    if "exists" in config:
        expected_exists = bool(config.get("exists"))
        passed = found is expected_exists
        if passed:
            state = "exists" if found else "is absent"
            return VerificationCheck(
                type="assertion",
                status="passed",
                message=f"assertion {display_path} {state} as expected",
            )
        state = "exists" if found else "is missing"
        return VerificationCheck(
            type="assertion",
            status="failed",
            message=f"assertion {display_path} {state}, expected exists {expected_exists!r}",
        )

    if not found:
        return VerificationCheck(
            type="assertion",
            status="failed",
            message=f"assertion {display_path} is missing",
        )

    if "equals" in config:
        expected = config.get("equals")
        passed = actual == expected
        return VerificationCheck(
            type="assertion",
            status="passed" if passed else "failed",
            message=f"assertion {display_path} actual {actual!r}, expected {expected!r}",
        )

    if "contains" in config:
        expected = config.get("contains")
        passed = _assertion_contains(actual, expected)
        return VerificationCheck(
            type="assertion",
            status="passed" if passed else "failed",
            message=f"assertion {display_path} actual {actual!r} contains {expected!r}",
        )

    if "value_type" in config:
        expected_type = str(config.get("value_type"))
        actual_type = _assertion_type_name(actual)
        passed = _assertion_matches_type(actual, expected_type)
        return VerificationCheck(
            type="assertion",
            status="passed" if passed else "failed",
            message=f"assertion {display_path} type is {actual_type!r}, expected {expected_type!r}",
        )

    return VerificationCheck(
        type="assertion",
        status="failed",
        message=f"assertion {display_path} has no supported operator",
    )


def _assertion_source_value(
    source: str,
    node_id: Any,
    run: StoredRun,
) -> tuple[Any, bool]:
    if source == "run":
        return {
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "status": run.status,
            "inputs": run.inputs,
            "outputs": run.outputs,
        }, True
    if source == "report":
        from .reporting import build_stored_run_report

        return build_stored_run_report(run), True
    if source in {"node_output", "node_metadata", "tool_invocation"}:
        event = _latest_node_event(run.events, str(node_id))
        if event is None:
            return None, False
        if source == "node_output":
            return event.output, True
        if source == "node_metadata":
            return event.metadata, True
        if isinstance(event.output, dict) and isinstance(event.output.get("tool_invocation"), dict):
            return event.output["tool_invocation"], True
        return None, False
    return None, False


def _latest_node_event(events: list[NodeEvent], node_id: str) -> NodeEvent | None:
    for event in reversed(events):
        if event.node_id == node_id:
            return event
    return None


def _lookup_assertion_path(value: Any, path: str) -> tuple[Any, bool]:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return None, False
            current = current[part]
            continue
        if isinstance(current, list) and part.isdecimal():
            index = int(part)
            if index >= len(current):
                return None, False
            current = current[index]
            continue
        return None, False
    return current, True


def _assertion_display_path(source: str, node_id: Any, path: str) -> str:
    if source in {"node_output", "node_metadata", "tool_invocation"}:
        return f"{source}[{str(node_id)!r}].{path}"
    return f"{source}.{path}"


def _assertion_contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str):
        return isinstance(expected, str) and expected in actual
    if isinstance(actual, list | tuple | set):
        return expected in actual
    if isinstance(actual, dict):
        return expected in actual
    return False


def _assertion_type_name(value: Any) -> str:
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


def _assertion_matches_type(value: Any, expected_type: str) -> bool:
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


def _validate_resume_compatibility(stored: StoredRun, workflow: Workflow) -> None:
    if stored.provenance is None:
        raise RuntimeError(f"run {stored.run_id!r} does not include immutable workflow provenance")
    if stored.workflow_id != workflow.id:
        raise RuntimeError(
            f"run {stored.run_id!r} references workflow {stored.workflow_id!r}, "
            f"but resume requested workflow {workflow.id!r}"
        )

    current_provenance = build_run_provenance(workflow, stored.inputs)
    if current_provenance.workflow_sha256 != stored.provenance.workflow_sha256:
        raise RuntimeError(
            "workflow source changed since run: "
            f"current sha256 {current_provenance.workflow_sha256}, "
            f"run snapshot sha256 {stored.provenance.workflow_sha256}"
        )
    if current_provenance.inputs_sha256 != stored.provenance.inputs_sha256:
        raise RuntimeError(
            "run inputs changed since run: "
            f"current sha256 {current_provenance.inputs_sha256}, "
            f"run snapshot sha256 {stored.provenance.inputs_sha256}"
        )


def _resume_state(stored: StoredRun, workflow: Workflow) -> dict[str, Any]:
    latest_by_node: dict[str, NodeEvent] = {}
    attempted: set[str] = set()
    for event in stored.events:
        latest_by_node[event.node_id] = event
        attempted.add(event.node_id)

    rerun_nodes = _rerun_nodes(latest_by_node, workflow)
    reusable_outputs: dict[str, Any] = {}
    reusable_events: dict[str, NodeEvent] = {}
    for node_id, event in latest_by_node.items():
        if node_id in rerun_nodes:
            continue
        if event.status not in ("completed", "skipped"):
            continue
        if node_id not in stored.outputs:
            continue
        reusable_outputs[node_id] = stored.outputs[node_id]
        reusable_events[node_id] = event

    return {
        "enabled": True,
        "attempted": attempted,
        "outputs": reusable_outputs,
        "events": reusable_events,
    }


def _rerun_nodes(latest_by_node: dict[str, NodeEvent], workflow: Workflow) -> set[str]:
    roots = {
        node_id
        for node_id, event in latest_by_node.items()
        if event.status not in ("completed", "skipped")
    }
    successors = _workflow_successors(workflow)
    rerun = set(roots)
    stack = list(roots)
    while stack:
        node_id = stack.pop()
        for target in successors.get(node_id, []):
            if target in rerun:
                continue
            rerun.add(target)
            stack.append(target)
    return rerun


def _workflow_successors(workflow: Workflow) -> dict[str, list[str]]:
    successors: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
    for node in workflow.nodes:
        if node.next:
            successors.setdefault(node.id, []).append(node.next)
    for edge in workflow.edges:
        successors.setdefault(edge.source, []).append(edge.target)
    return successors


def _latest_policy_outcome(events: list[NodeEvent]) -> str | None:
    if not events:
        return None
    output = events[-1].output
    if isinstance(output, dict):
        outcome = output.get("policy_outcome")
        if isinstance(outcome, str):
            return outcome
    return None


def _latest_contract_status(events: list[NodeEvent]) -> str | None:
    if not events:
        return None
    contract = events[-1].metadata.get("contract")
    if not isinstance(contract, dict):
        return None
    output_contract = contract.get("output")
    if not isinstance(output_contract, dict):
        return None
    status = output_contract.get("status")
    return status if isinstance(status, str) else None


def _latest_resume_action(events: list[NodeEvent]) -> str | None:
    for event in reversed(events):
        resume = event.metadata.get("resume")
        if not isinstance(resume, dict):
            continue
        action = resume.get("action")
        if isinstance(action, str):
            return action
    return None


def _latest_governance_status(events: list[NodeEvent]) -> str | None:
    for event in reversed(events):
        governance = event.metadata.get("governance")
        if not isinstance(governance, dict):
            continue
        status = governance.get("status")
        if isinstance(status, str):
            return status
    return None
