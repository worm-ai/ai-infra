from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .artifacts import export_evidence_bundle, verify_evidence_bundle
from .config import WorkflowValidationError, load_workflow, validate_workflow
from . import __version__
from .maintenance import (
    apply_retention_cleanup,
    inspect_state_dir,
    list_run_summaries,
    plan_retention_cleanup,
)
from .reporting import build_run_report
from .runtime import default_store, get_run, resume_workflow, run_workflow, validate_run, validate_stored_run


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if "--version" in raw_args and not _contains_subcommand(raw_args):
        _print(_version_payload())
        return 0

    parser = argparse.ArgumentParser(prog="ai-infra")
    parser.add_argument("--state-dir", default=".ai-infra")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("workflow")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("workflow")
    run_parser.add_argument("--input-file", required=True)

    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--workflow", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("run_id")

    logs_parser = subparsers.add_parser("logs")
    logs_parser.add_argument("run_id")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("run_id")

    export_parser = subparsers.add_parser("export-bundle")
    export_parser.add_argument("run_id")
    export_parser.add_argument("--output-dir", required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("run_id")
    verify_parser.add_argument("--workflow")

    verify_bundle_parser = subparsers.add_parser("verify-bundle")
    verify_bundle_parser.add_argument("bundle")

    subparsers.add_parser("store-health")

    runs_parser = subparsers.add_parser("runs")
    runs_parser.add_argument("--status")

    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--keep-last", type=int, required=True)
    cleanup_parser.add_argument("--status")
    cleanup_parser.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "verify-bundle":
        try:
            verification = verify_evidence_bundle(args.bundle)
        except ValueError as exc:
            _print({"ok": False, "error": str(exc)})
            return 2
        _print({"ok": verification.status == "passed", "verification": asdict(verification)})
        return 0 if verification.status == "passed" else 1

    if args.command == "store-health":
        _print({"ok": True, "health": inspect_state_dir(args.state_dir)})
        return 0

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
        if args.command == "resume":
            workflow = load_workflow(args.workflow)
            result = resume_workflow(args.run_id, workflow, store=store)
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
        if args.command == "export-bundle":
            run = get_run(args.run_id, store=store)
            report = build_run_report(args.run_id, store=store)
            bundle = export_evidence_bundle(run, report, args.output_dir)
            _print({"ok": True, "bundle": asdict(bundle)})
            return 0
        if args.command == "verify":
            if args.workflow:
                workflow = load_workflow(args.workflow)
                verification = validate_run(args.run_id, workflow, store=store)
            else:
                verification = validate_stored_run(args.run_id, store=store)
            _print({"ok": verification.status == "passed", "verification": asdict(verification)})
            return 0 if verification.status == "passed" else 1
        if args.command == "runs":
            _print({"ok": True, "runs": list_run_summaries(store, status=args.status)})
            return 0
        if args.command == "cleanup":
            if args.apply:
                cleanup = apply_retention_cleanup(store, keep_last=args.keep_last, status=args.status)
            else:
                cleanup = plan_retention_cleanup(store, keep_last=args.keep_last, status=args.status)
            _print({"ok": True, "cleanup": cleanup})
            return 0
    except (WorkflowValidationError, KeyError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2
    return 2


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _version_payload() -> dict[str, Any]:
    return {"ok": True, "package": "ai-infra", "version": __version__}


def _contains_subcommand(argv: list[str]) -> bool:
    return any(
        token
        in {
            "validate",
            "run",
            "resume",
            "status",
            "logs",
            "report",
            "export-bundle",
            "verify",
            "verify-bundle",
            "store-health",
            "runs",
            "cleanup",
        }
        for token in argv
    )


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
