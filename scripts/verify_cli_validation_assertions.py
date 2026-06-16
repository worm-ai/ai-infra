from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-validation-assertions-") as temp:
        state_dir = Path(temp) / "state"

        passing_validate = _run_cli(
            state_dir,
            "validate",
            "examples/validation_assertion_workflow.yaml",
        )
        _assert(passing_validate["ok"] is True, "passing assertion workflow should validate")

        passing_run = _run_cli(
            state_dir,
            "run",
            "examples/validation_assertion_workflow.yaml",
            "--input-file",
            "examples/validation_assertion_input.json",
        )["run"]
        passing_run_id = str(passing_run["run_id"])
        passing_verify = _run_cli(state_dir, "verify", passing_run_id)["verification"]
        _assert(passing_run["status"] == "completed", "passing assertion workflow should complete")
        _assert(passing_verify["status"] == "passed", "passing assertion verification should pass")
        _assert(
            any(
                check["type"] == "assertion"
                and check["status"] == "passed"
                and "tool_invocation['python_echo'].input.args.value" in check["message"]
                for check in passing_verify["checks"]
            ),
            "passing verification should include tool invocation assertion evidence",
        )

        failing_validate = _run_cli(
            state_dir,
            "validate",
            "examples/validation_assertion_failure_workflow.yaml",
        )
        _assert(failing_validate["ok"] is True, "failing assertion workflow should validate")

        failing_run = _run_cli(
            state_dir,
            "run",
            "examples/validation_assertion_failure_workflow.yaml",
            "--input-file",
            "examples/validation_assertion_input.json",
        )["run"]
        failing_run_id = str(failing_run["run_id"])
        failing_verify = _run_cli(state_dir, "verify", failing_run_id, allow_verify_failure=True)["verification"]
        _assert(failing_run["status"] == "completed", "failing assertion workflow execution should complete")
        _assert(failing_verify["status"] == "failed", "failing assertion verification should fail")
        _assert(
            any(
                check["type"] == "assertion"
                and check["status"] == "failed"
                and "expected 'expected-other-value'" in check["message"]
                for check in failing_verify["checks"]
            ),
            "failing verification should include localized assertion mismatch evidence",
        )

    print(
        json.dumps(
            {
                "ok": True,
                "passing_run_id": passing_run_id,
                "failing_run_id": failing_run_id,
                "passing_verify_status": passing_verify["status"],
                "failing_verify_status": failing_verify["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _run_cli(
    state_dir: Path,
    *args: str,
    allow_verify_failure: bool = False,
) -> dict[str, object]:
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
    expected_codes = (0, 1) if allow_verify_failure else (0,)
    if result.returncode not in expected_codes:
        raise RuntimeError(
            f"command failed with code {result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    payload = json.loads(result.stdout)
    if payload.get("ok") is False and not allow_verify_failure:
        raise RuntimeError(result.stdout)
    return payload


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
