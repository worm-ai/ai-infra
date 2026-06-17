from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import current_file_sha256, find_artifact, latest_node_artifacts
from .config import Workflow, load_workflow_from_source, validate_workflow
from .langgraph_runner import compile_workflow
from .provenance import build_run_provenance, sha256_text
from .store import NodeEvent, RunStore, StoredRun, VerificationCheck

REDACTION_MARKER = "[REDACTED]"


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
    compatibility: dict[str, Any]


def default_store(state_dir: str | Path = ".ai-infra") -> RunStore:
    return RunStore(Path(state_dir) / "runs.sqlite")


def run_workflow(workflow: Workflow, inputs: dict[str, Any], store: RunStore | None = None) -> RunResult:
    validate_workflow(workflow)
    run_store = store or default_store()
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    workflow_source_path = str(workflow.source_path) if workflow.source_path else None
    governance_evidence = _environment_governance_evidence(workflow)
    sensitive_values = _sensitive_input_values(inputs, workflow.governance)
    safe_inputs = _redact_run_inputs(inputs, workflow.governance, sensitive_values)
    provenance = _governed_provenance(workflow, safe_inputs, governance_evidence)
    missing_required_env = [
        item["name"]
        for item in governance_evidence["required_env"]
        if item.get("present") is False
    ]
    if missing_required_env:
        provenance.environment["governance"] = {
            "status": "failed",
            "missing_required_env": missing_required_env,
        }
        run_store.save_run(
            StoredRun(
                run_id=run_id,
                workflow_id=workflow.id,
                status="failed",
                inputs=safe_inputs,
                outputs={},
                workflow_source_path=workflow_source_path,
                provenance=provenance,
            )
        )
        return RunResult(run_id=run_id, workflow_id=workflow.id, status="failed", outputs={}, events=[])

    run_store.save_run(
        StoredRun(
            run_id=run_id,
            workflow_id=workflow.id,
            status="running",
            inputs=safe_inputs,
            outputs={},
            workflow_source_path=workflow_source_path,
            provenance=provenance,
        )
    )

    graph = compile_workflow(
        workflow,
        store=_RedactingRunStore(run_store, workflow.governance, sensitive_values),
    )
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
    final_sensitive_values = set(sensitive_values)
    final_sensitive_values.update(_configured_run_output_values(outputs, workflow.governance))
    safe_inputs = _redact_run_inputs(inputs, workflow.governance, final_sensitive_values)
    provenance = _governed_provenance(workflow, safe_inputs, governance_evidence)
    safe_outputs, safe_events = _redact_run_evidence(workflow.governance, outputs, events, sensitive_values)
    if safe_events != events:
        run_store.replace_events(run_id, safe_events)

    run_store.save_run(
        StoredRun(
            run_id=run_id,
            workflow_id=workflow.id,
            status=status,
            inputs=safe_inputs,
            outputs=safe_outputs,
            workflow_source_path=workflow_source_path,
            provenance=provenance,
        )
    )
    return RunResult(run_id=run_id, workflow_id=workflow.id, status=status, outputs=safe_outputs, events=safe_events)


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
    compatibility = validate_workflow(workflow)
    run_store = store or default_store()
    stored = run_store.get_run(run_id)
    checks = _evaluate_workflow_validations(workflow, stored)
    return _record_verification(run_store, run_id, checks, compatibility)


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
    validate_workflow(workflow)
    checks = [_evaluate_workflow_source_integrity(stored)]
    checks.extend(_evaluate_workflow_validations(workflow, stored))
    return _record_verification(run_store, run_id, checks, _stored_compatibility(stored))


def _evaluate_workflow_validations(workflow: Workflow, stored: StoredRun) -> list[VerificationCheck]:
    return [
        _evaluate_validation(validation.type, validation.config, stored)
        for validation in workflow.validations
    ]


def _environment_governance_evidence(workflow: Workflow) -> dict[str, Any]:
    required_env = workflow.governance.get("required_env", [])
    if not isinstance(required_env, list):
        required_env = []
    return {
        "required_env": [
            {"name": str(name), "present": str(name) in os.environ}
            for name in required_env
        ]
    }


def _sensitive_input_values(inputs: dict[str, Any], governance: dict[str, Any]) -> set[Any]:
    values: set[Any] = set()
    for path in _sensitive_paths(governance, "inputs"):
        value, found = _lookup_path(inputs, path)
        if found and isinstance(value, (str, int, float, bool)):
            values.add(value)
    return values


def _governed_provenance(
    workflow: Workflow,
    safe_inputs: dict[str, Any],
    governance_evidence: dict[str, Any],
):
    provenance = build_run_provenance(workflow, safe_inputs)
    environment = dict(provenance.environment)
    environment["required_env"] = list(governance_evidence.get("required_env", []))
    provenance.environment.clear()
    provenance.environment.update(environment)
    return provenance


def _redact_run_inputs(
    inputs: dict[str, Any],
    governance: dict[str, Any],
    sensitive_values: set[Any],
) -> dict[str, Any]:
    safe_inputs = _deep_copy(inputs)
    for path in _sensitive_paths(governance, "inputs"):
        _redact_path(safe_inputs, path)
    _redact_values(safe_inputs, sensitive_values)
    return safe_inputs if isinstance(safe_inputs, dict) else {}


def _redact_run_evidence(
    governance: dict[str, Any],
    outputs: dict[str, Any],
    events: list[NodeEvent],
    sensitive_values: set[Any],
) -> tuple[dict[str, Any], list[NodeEvent]]:
    safe_outputs = _redact_run_outputs(outputs, governance, sensitive_values)
    redacted_events = [
        _redact_node_event(governance, event, sensitive_values)
        for event in events
    ]
    return safe_outputs if isinstance(safe_outputs, dict) else {}, redacted_events


class _RedactingRunStore:
    def __init__(self, inner: RunStore, governance: dict[str, Any], sensitive_values: set[Any]):
        self._inner = inner
        self._governance = governance
        self._sensitive_values = set(sensitive_values)

    @property
    def state_dir(self) -> Path:
        return self._inner.state_dir

    def add_event(self, event: NodeEvent) -> None:
        self._inner.add_event(_redact_node_event(self._governance, event, self._sensitive_values))

    def count_node_executions(self, run_id: str) -> int:
        return self._inner.count_node_executions(run_id)

    def reserve_node_execution(
        self,
        run_id: str,
        node_id: str,
        max_node_executions: int,
    ) -> tuple[bool, int]:
        return self._inner.reserve_node_execution(run_id, node_id, max_node_executions)


def _redact_run_outputs(
    outputs: dict[str, Any],
    governance: dict[str, Any],
    sensitive_values: set[Any],
) -> dict[str, Any]:
    safe_outputs = _deep_copy(outputs)
    output_sensitive_values = set(sensitive_values)
    output_sensitive_values.update(_configured_run_output_values(outputs, governance))
    for path in _sensitive_paths(governance, "outputs"):
        _redact_path(safe_outputs, path)
    for node_id, path in _node_scoped_paths(governance, "node_output"):
        _redact_path(safe_outputs.get(node_id), path)
    _redact_values(safe_outputs, output_sensitive_values)
    return safe_outputs if isinstance(safe_outputs, dict) else {}


def _redact_node_event(
    governance: dict[str, Any],
    event: NodeEvent,
    sensitive_values: set[Any],
) -> NodeEvent:
    event_input = _deep_copy(event.input)
    event_output = _deep_copy(event.output)
    event_metadata = _deep_copy(event.metadata)
    event_sensitive_values = set(sensitive_values)
    event_sensitive_values.update(
        _configured_event_sensitive_values(
            governance,
            event.node_id,
            event_input,
            event_output,
            event_metadata,
        )
    )
    redacted_count = _redact_configured_event_paths(
        governance,
        event.node_id,
        event_input,
        event_output,
        event_metadata,
    )
    redacted_count += _redact_values(event_input, event_sensitive_values)
    redacted_count += _redact_values(event_output, event_sensitive_values)
    redacted_count += _redact_values(event_metadata, event_sensitive_values)
    if redacted_count and isinstance(event_metadata, dict):
        event_metadata["redaction"] = {
            "status": "redacted",
            "marker": REDACTION_MARKER,
            "paths": list(governance.get("sensitive_paths", [])),
            "redacted_count": redacted_count,
        }
    return NodeEvent(
        run_id=event.run_id,
        node_id=event.node_id,
        status=event.status,
        input=event_input if isinstance(event_input, dict) else {},
        output=event_output,
        metadata=event_metadata if isinstance(event_metadata, dict) else {},
    )


def _configured_run_output_values(outputs: dict[str, Any], governance: dict[str, Any]) -> set[Any]:
    values: set[Any] = set()
    for path in _sensitive_paths(governance, "outputs"):
        _add_scalar_path_value(values, outputs, path)
    for node_id, path in _node_scoped_paths(governance, "node_output"):
        _add_scalar_path_value(values, outputs.get(node_id), path)
    for node_id, path in _node_scoped_paths(governance, "tool_invocation"):
        node_output = outputs.get(node_id)
        if isinstance(node_output, dict) and isinstance(node_output.get("tool_invocation"), dict):
            _add_scalar_path_value(values, node_output["tool_invocation"], path)
    return values


def _configured_event_sensitive_values(
    governance: dict[str, Any],
    node_id: str,
    event_input: Any,
    event_output: Any,
    event_metadata: Any,
) -> set[Any]:
    values: set[Any] = set()
    for path in _sensitive_paths(governance, "inputs"):
        _add_scalar_path_value(values, event_input, path)
    for path in _sensitive_paths(governance, "outputs"):
        _add_scalar_path_value(values, event_input, path)
        if path and path[0] == node_id:
            _add_scalar_path_value(values, event_output, path[1:])
    for scoped_node_id, path in _node_scoped_paths(governance, "node_output"):
        _add_scalar_path_value(values, event_input, [scoped_node_id, *path])
        if scoped_node_id == node_id:
            _add_scalar_path_value(values, event_output, path)
    for scoped_node_id, path in _node_scoped_paths(governance, "node_metadata"):
        if scoped_node_id == node_id:
            _add_scalar_path_value(values, event_metadata, path)
    if isinstance(event_output, dict) and isinstance(event_output.get("tool_invocation"), dict):
        for scoped_node_id, path in _node_scoped_paths(governance, "tool_invocation"):
            if scoped_node_id == node_id:
                _add_scalar_path_value(values, event_output["tool_invocation"], path)
    return values


def _redact_configured_event_paths(
    governance: dict[str, Any],
    node_id: str,
    event_input: Any,
    event_output: Any,
    event_metadata: Any,
) -> int:
    count = 0
    for path in _sensitive_paths(governance, "inputs"):
        count += _redact_path(event_input, path)
    for path in _sensitive_paths(governance, "outputs"):
        count += _redact_path(event_input, path)
        if path and path[0] == node_id:
            count += _redact_path(event_output, path[1:])
    for scoped_node_id, path in _node_scoped_paths(governance, "node_output"):
        count += _redact_path(event_input, [scoped_node_id, *path])
        if scoped_node_id == node_id:
            count += _redact_path(event_output, path)
    for scoped_node_id, path in _node_scoped_paths(governance, "node_metadata"):
        if scoped_node_id == node_id:
            count += _redact_path(event_metadata, path)
    if isinstance(event_output, dict) and isinstance(event_output.get("tool_invocation"), dict):
        for scoped_node_id, path in _node_scoped_paths(governance, "tool_invocation"):
            if scoped_node_id == node_id:
                count += _redact_path(event_output["tool_invocation"], path)
    return count


def _sensitive_paths(governance: dict[str, Any], root: str) -> list[list[str]]:
    raw_paths = governance.get("sensitive_paths", [])
    if not isinstance(raw_paths, list):
        return []
    prefix = f"{root}."
    return [
        str(path)[len(prefix):].split(".")
        for path in raw_paths
        if isinstance(path, str) and path.startswith(prefix)
    ]


def _node_scoped_paths(governance: dict[str, Any], root: str) -> list[tuple[str, list[str]]]:
    raw_paths = governance.get("sensitive_paths", [])
    if not isinstance(raw_paths, list):
        return []
    prefix = f"{root}."
    paths: list[tuple[str, list[str]]] = []
    for path in raw_paths:
        if not isinstance(path, str) or not path.startswith(prefix):
            continue
        parts = path[len(prefix):].split(".")
        if len(parts) >= 2:
            paths.append((parts[0], parts[1:]))
    return paths


def _add_scalar_path_value(values: set[Any], value: Any, parts: list[str]) -> None:
    path_value, found = _lookup_path(value, parts)
    if found and isinstance(path_value, (str, int, float, bool)):
        values.add(path_value)


def _lookup_path(value: Any, parts: list[str]) -> tuple[Any, bool]:
    current = value
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
            continue
        return None, False
    return current, True


def _redact_values(value: Any, sensitive_values: set[Any]) -> int:
    if not sensitive_values:
        return 0
    count = 0
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if _is_sensitive_scalar(item, sensitive_values):
                value[key] = REDACTION_MARKER
                count += 1
            elif isinstance(item, str):
                redacted, replacements = _redact_sensitive_substrings(item, sensitive_values)
                if replacements:
                    value[key] = redacted
                    count += replacements
            else:
                count += _redact_values(item, sensitive_values)
    elif isinstance(value, list):
        for index, item in enumerate(list(value)):
            if _is_sensitive_scalar(item, sensitive_values):
                value[index] = REDACTION_MARKER
                count += 1
            elif isinstance(item, str):
                redacted, replacements = _redact_sensitive_substrings(item, sensitive_values)
                if replacements:
                    value[index] = redacted
                    count += replacements
            else:
                count += _redact_values(item, sensitive_values)
    return count


def _is_sensitive_scalar(value: Any, sensitive_values: set[Any]) -> bool:
    return isinstance(value, (str, int, float, bool)) and value in sensitive_values


def _redact_sensitive_substrings(value: str, sensitive_values: set[Any]) -> tuple[str, int]:
    redacted = value
    count = 0
    for sensitive_value in sensitive_values:
        if not isinstance(sensitive_value, str) or not sensitive_value:
            continue
        occurrences = redacted.count(sensitive_value)
        if not occurrences:
            continue
        redacted = redacted.replace(sensitive_value, REDACTION_MARKER)
        count += occurrences
    return redacted, count


def _redact_path(value: Any, parts: list[str]) -> int:
    if not parts:
        return 0
    current = value
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
            continue
        return 0
    final = parts[-1]
    if isinstance(current, dict) and final in current:
        if current[final] != REDACTION_MARKER:
            current[final] = REDACTION_MARKER
            return 1
        return 0
    if isinstance(current, list) and final.isdecimal() and int(final) < len(current):
        index = int(final)
        if current[index] != REDACTION_MARKER:
            current[index] = REDACTION_MARKER
            return 1
    return 0


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def _record_verification(
    run_store: RunStore,
    run_id: str,
    checks: list[VerificationCheck],
    compatibility: dict[str, Any] | None = None,
) -> VerificationResult:
    status = "passed" if all(check.status == "passed" for check in checks) else "failed"
    run_store.add_verification(run_id, status, checks, compatibility)
    return VerificationResult(
        run_id=run_id,
        status=status,
        checks=checks,
        compatibility=compatibility or {},
    )


def _stored_compatibility(run: StoredRun) -> dict[str, Any]:
    if run.provenance is not None and run.provenance.compatibility:
        return run.provenance.compatibility
    return {
        "schema_version": {
            "declared": "unknown",
            "supported": [],
            "status": "unknown",
        },
        "features": [],
        "status": "unknown",
        "failure_category": None,
        "diagnostics": [
            {
                "category": "missing_compatibility_evidence",
                "severity": "warning",
                "message": "run does not include workflow compatibility evidence",
            }
        ],
    }


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
