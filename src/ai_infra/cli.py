from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import WorkflowValidationError, load_workflow, validate_workflow
from .reporting import build_run_report
from .runtime import default_store, get_run, run_workflow, validate_run, validate_stored_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-infra")
    parser.add_argument("--state-dir", default=".ai-infra")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("workflow")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("workflow")
    run_parser.add_argument("--input-file", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("run_id")

    logs_parser = subparsers.add_parser("logs")
    logs_parser.add_argument("run_id")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("run_id")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("run_id")
    verify_parser.add_argument("--workflow")

    args = parser.parse_args(argv)
    store = default_store(args.state_dir)

    try:
        if args.command == "validate":
            workflow = load_workflow(args.workflow)
            validate_workflow(workflow)
            _print({"ok": True, "workflow": {"id": workflow.id, "nodes": [node.id for node in workflow.nodes]}})
            return 0
        if args.command == "run":
            workflow = load_workflow(args.workflow)
            inputs = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
            result = run_workflow(workflow, inputs, store=store)
            _print({"ok": True, "run": _run_result_payload(result)})
            return 0
        if args.command == "status":
            run = get_run(args.run_id, store=store)
            _print({"ok": True, "run": _stored_run_payload(run, include_events=False)})
            return 0
        if args.command == "logs":
            run = get_run(args.run_id, store=store)
            _print({"ok": True, "events": [asdict(event) for event in run.events]})
            return 0
        if args.command == "report":
            report = build_run_report(args.run_id, store=store)
            _print({"ok": True, "report": report})
            return 0
        if args.command == "verify":
            if args.workflow:
                workflow = load_workflow(args.workflow)
                verification = validate_run(args.run_id, workflow, store=store)
            else:
                verification = validate_stored_run(args.run_id, store=store)
            _print({"ok": verification.status == "passed", "verification": asdict(verification)})
            return 0 if verification.status == "passed" else 1
    except (WorkflowValidationError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2
    return 2


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _run_result_payload(result: Any) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "workflow_id": result.workflow_id,
        "status": result.status,
        "outputs": result.outputs,
    }


def _stored_run_payload(run: Any, include_events: bool) -> dict[str, Any]:
    payload = {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "inputs": run.inputs,
        "outputs": run.outputs,
    }
    if include_events:
        payload["events"] = [asdict(event) for event in run.events]
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
