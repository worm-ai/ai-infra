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
        retry = _run_workflow(state_dir, "examples/retry_workflow.yaml")
        exhausted = _run_workflow(state_dir, "examples/retry_exhausted_workflow.yaml")
        retry_report = _report(state_dir, retry["run_id"])
        exhausted_report = _report(state_dir, exhausted["run_id"])
        retry_verify = _verify(state_dir, retry["run_id"])
        exhausted_verify = _verify(state_dir, exhausted["run_id"])

    _assert(retry["status"] == "completed", "retry workflow should complete")
    _assert(exhausted["status"] == "failed", "retry exhausted workflow should fail")
    _assert(retry_report["summary"]["retried"] == 1, "retry report should count retried node")
    _assert(retry_report["timeline"][0]["policy"]["outcome"] == "retry_succeeded", "retry outcome mismatch")
    _assert(exhausted_report["failure"]["policy_outcome"] == "retry_exhausted", "exhausted outcome mismatch")
    _assert(retry_verify["status"] == "passed", "retry verify should pass")
    _assert(exhausted_verify["status"] == "passed", "retry exhausted verify should pass")

    print(
        json.dumps(
            {
                "ok": True,
                "retry": {
                    "run_id": retry["run_id"],
                    "status": retry["status"],
                    "attempts": retry_report["timeline"][0]["attempts"],
                    "policy_outcome": retry_report["timeline"][0]["policy"]["outcome"],
                    "verify_status": retry_verify["status"],
                },
                "retry_exhausted": {
                    "run_id": exhausted["run_id"],
                    "status": exhausted["status"],
                    "attempts": exhausted_report["timeline"][0]["attempts"],
                    "policy_outcome": exhausted_report["failure"]["policy_outcome"],
                    "verify_status": exhausted_verify["status"],
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
        "examples/retry_input.json",
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
