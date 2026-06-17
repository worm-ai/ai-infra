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
    backup_run_store,
    inspect_state_dir,
    list_run_summaries,
    plan_retention_cleanup,
    preflight_restore_run_store,
)
from .release_trust import (
    build_release_trust_manifest,
    current_source_commit,
    current_tree_state,
    default_build_environment,
    verify_release_trust_manifest,
    write_release_trust_manifest,
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

    release_manifest_parser = subparsers.add_parser("release-manifest")
    release_manifest_parser.add_argument("--artifact", action="append", required=True)
    release_manifest_parser.add_argument("--output", required=True)
    release_manifest_parser.add_argument("--source-commit")
    release_manifest_parser.add_argument("--tree-state")
    release_manifest_parser.add_argument("--verification", action="append", default=[])

    verify_release_parser = subparsers.add_parser("verify-release")
    verify_release_parser.add_argument("manifest")
    verify_release_parser.add_argument("--artifact-dir")
    verify_release_parser.add_argument("--expected-source-commit")

    subparsers.add_parser("store-health")

    backup_parser = subparsers.add_parser("store-backup")
    backup_parser.add_argument("--output", required=True)

    restore_preflight_parser = subparsers.add_parser("store-restore-preflight")
    restore_preflight_parser.add_argument("backup")
    restore_preflight_parser.add_argument("--restore-state-dir", required=True)

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

    if args.command == "release-manifest":
        manifest = build_release_trust_manifest(
            [Path(path) for path in args.artifact],
            source_commit=args.source_commit or current_source_commit(),
            tree_state=args.tree_state or current_tree_state(),
            build_environment=default_build_environment(),
            verification_commands=_parse_release_verification_args(args.verification),
        )
        path = write_release_trust_manifest(manifest, args.output)
        _print({"ok": True, "manifest": {"path": str(path), "package": manifest["package"]}})
        return 0

    if args.command == "verify-release":
        verification = verify_release_trust_manifest(
            args.manifest,
            artifact_dir=args.artifact_dir,
            expected_source_commit=args.expected_source_commit,
        )
        _print({"ok": verification.status == "passed", "verification": asdict(verification)})
        return 0 if verification.status == "passed" else 1

    if args.command == "store-health":
        _print({"ok": True, "health": inspect_state_dir(args.state_dir)})
        return 0

    if args.command == "store-backup":
        backup = backup_run_store(args.state_dir, args.output)
        _print({"ok": backup["ok"], "backup": backup})
        return 0 if backup["ok"] else 1

    if args.command == "store-restore-preflight":
        preflight = preflight_restore_run_store(
            args.backup,
            restore_state_dir=args.restore_state_dir,
        )
        _print({"ok": preflight["ok"], "restore_preflight": preflight})
        return 0 if preflight["ok"] else 1

    store = default_store(args.state_dir)

    try:
        if args.command == "validate":
            workflow = load_workflow(args.workflow)
            compatibility = validate_workflow(workflow)
            _print(
                {
                    "ok": True,
                    "workflow": {"id": workflow.id, "nodes": [node.id for node in workflow.nodes]},
                    "compatibility": compatibility,
                }
            )
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
    except WorkflowValidationError as exc:
        payload: dict[str, Any] = {"ok": False, "error": str(exc)}
        if exc.compatibility is not None:
            payload["compatibility"] = exc.compatibility
        _print(payload)
        return 2
    except (KeyError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
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
            "release-manifest",
            "verify-release",
            "store-health",
            "store-backup",
            "store-restore-preflight",
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


def _parse_release_verification_args(values: list[str]) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    for value in values:
        if "=" in value:
            command, status = value.rsplit("=", 1)
        else:
            command, status = value, "passed"
        commands.append({"command": command, "status": status})
    return commands


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
