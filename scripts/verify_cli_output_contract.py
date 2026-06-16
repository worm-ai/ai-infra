from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "state"
        passing = _run_workflow(state_dir, "examples/output_contract_workflow.yaml")
        failing = _run_workflow(state_dir, "examples/output_contract_failure_workflow.yaml")
        passing_report = _report(state_dir, passing["run_id"])
        failing_report = _report(state_dir, failing["run_id"])
        passing_verify = _verify(state_dir, passing["run_id"])
        failing_verify = _verify(state_dir, failing["run_id"])

    _assert(passing["status"] == "completed", "passing output contract workflow should complete")
    _assert(failing["status"] == "failed", "failing output contract workflow should fail")
    _assert(
        passing_report["timeline"][0]["contract"]["output"]["status"] == "passed",
        "passing report should include passed contract evidence",
    )
    _assert(
        failing_report["timeline"][0]["contract"]["output"]["status"] == "failed",
        "failing report should include failed contract evidence",
    )
    _assert(passing_verify["status"] == "passed", "passing output contract verify should pass")
    _assert(failing_verify["status"] == "passed", "failing output contract verify should pass")

    print(
        json.dumps(
            {
                "ok": True,
                "passing": {
                    "run_id": passing["run_id"],
                    "status": passing["status"],
                    "contract_status": passing_report["timeline"][0]["contract"]["output"]["status"],
                    "verify_status": passing_verify["status"],
                },
                "failing": {
                    "run_id": failing["run_id"],
                    "status": failing["status"],
                    "contract_status": failing_report["timeline"][0]["contract"]["output"]["status"],
                    "verify_status": failing_verify["status"],
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _run_workflow(state_dir: Path, workflow: str) -> dict[str, object]:
    payload = _run_cli(
        state_dir,
        "run",
        workflow,
        "--input-file",
        "examples/output_contract_input.json",
    )
    return dict(payload["run"])


def _report(state_dir: Path, run_id: str) -> dict[str, object]:
    return dict(_run_cli(state_dir, "report", run_id)["report"])


def _verify(state_dir: Path, run_id: str) -> dict[str, object]:
    return dict(_run_cli(state_dir, "verify", run_id)["verification"])


def _run_cli(state_dir: Path, *args: str) -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_infra.cli",
            "--state-dir",
            str(state_dir),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stdout + result.stderr)
    payload = json.loads(result.stdout)
    if payload.get("ok") is False and args[0] != "verify":
        raise RuntimeError(result.stdout)
    return payload


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
