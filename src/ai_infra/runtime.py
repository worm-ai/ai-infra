from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Workflow, validate_workflow
from .langgraph_runner import compile_workflow
from .store import NodeEvent, RunStore, StoredRun, VerificationCheck, StoredVerification


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

    run_store.save_run(
        StoredRun(
            run_id=run_id,
            workflow_id=workflow.id,
            status="running",
            inputs=inputs,
            outputs={},
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
        )
    )
    return RunResult(run_id=run_id, workflow_id=workflow.id, status=status, outputs=outputs, events=events)


def get_run(run_id: str, store: RunStore | None = None) -> StoredRun:
    return (store or default_store()).get_run(run_id)


def validate_run(run_id: str, workflow: Workflow, store: RunStore | None = None) -> VerificationResult:
    run_store = store or default_store()
    stored = run_store.get_run(run_id)
    checks: list[VerificationCheck] = []
    for validation in workflow.validations:
        check = _evaluate_validation(validation.type, validation.config, stored)
        checks.append(check)
    status = "passed" if all(check.status == "passed" for check in checks) else "failed"
    run_store.add_verification(run_id, status, checks)
    return VerificationResult(run_id=run_id, status=status, checks=checks)


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
    return VerificationCheck(type=validation_type, status="failed", message="unsupported validation type")
