from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-react-node-") as temp:
        state_dir = Path(temp) / "state"
        bundle_dir = Path(temp) / "bundles"

        validate = _run_cli(state_dir, "validate", "examples/react_workflow.yaml")
        _assert(validate["ok"] is True, "react workflow should validate")

        run = _run_cli(
            state_dir,
            "run",
            "examples/react_workflow.yaml",
            "--input-file",
            "examples/react_input.json",
        )["run"]
        run_id = str(run["run_id"])
        _assert(run["status"] == "completed", "react workflow should complete")
        _assert(run["outputs"]["answer"]["answer"] == "ABH", "react answer should come from declared tool")
        _assert(
            run["outputs"]["answer"]["react"]["budget"]["status"] == "within_limits",
            "react node should remain inside configured bounds",
        )

        logs = _run_cli(state_dir, "logs", run_id)["events"]
        _assert(len(logs) == 1, "react workflow should persist one DAG node event")
        [event] = logs
        _assert(event["node_id"] == "answer", "react event should be scoped to the DAG node")
        _assert(
            event["output"]["react"]["steps"][0]["tool_invocation"]["identity"] == "echo",
            "react event should include nested tool invocation evidence",
        )
        _assert(
            "thought" not in event["output"]["react"]["steps"][0],
            "react event should persist thought summaries, not hidden chain-of-thought",
        )

        report = _run_cli(state_dir, "report", run_id)["report"]
        _assert(report["summary"]["react"]["nodes"] == 1, "report should summarize react nodes")
        _assert(report["timeline"][0]["react"]["model"]["provider"] == "mock", "report should expose model summary")
        _assert("prompt" not in report["timeline"][0]["react"]["model"], "report should not persist raw prompt text")

        verification = _run_cli(state_dir, "verify", run_id)["verification"]
        _assert(verification["status"] == "passed", "react workflow verification should pass")
        _assert(
            any(
                check["type"] == "assertion"
                and check["status"] == "passed"
                and "timeline.0.react.model.provider" in check["message"]
                for check in verification["checks"]
            ),
            "verification should include report-level react assertion evidence",
        )

        bundle = _run_cli(state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))["bundle"]
        _assert_bundle_contains_react_evidence(Path(str(bundle["path"])))

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "verify_status": verification["status"],
                "bundle": bundle["path"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _run_cli(state_dir: Path, *args: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(args)}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    payload = json.loads(result.stdout)
    if payload.get("ok") is False:
        raise AssertionError(result.stdout)
    return payload


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_bundle_contains_react_evidence(path: Path) -> None:
    _assert(path.exists(), "evidence bundle should exist")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        _assert(
            {"report.json", "inputs.json", "events.json", "workflow_snapshot.yaml", "manifest.json"}.issubset(names),
            "react evidence bundle should include standard evidence files",
        )
        report = json.loads(archive.read("report.json"))
        events = json.loads(archive.read("events.json"))
        _assert(report["summary"]["react"]["nodes"] == 1, "bundle report should include react summary")
        _assert(
            events[0]["output"]["react"]["steps"][0]["tool_invocation"]["identity"] == "echo",
            "bundle events should include nested react tool evidence",
        )


if __name__ == "__main__":
    raise SystemExit(main())
