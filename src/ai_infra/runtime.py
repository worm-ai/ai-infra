from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def get_run(run_id: str, store: RunStore | None = None) -> StoredRun:
    return (store or default_store()).get_run(run_id)


def validate_run(run_id: str, workflow: Workflow, store: RunStore | None = None) -> VerificationResult:
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
        attempts = [event for event in run.events if event.node_id == node_id]
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
    return VerificationCheck(type=validation_type, status="failed", message="unsupported validation type")


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
