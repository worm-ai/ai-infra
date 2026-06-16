from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-governance-") as temp:
        state_dir = Path(temp) / "state"
        validate = _run_cli(state_dir, "validate", "examples/governance_workflow.yaml")
        _assert(validate.get("ok") is True, "governance workflow should validate")

        run = _run_cli(
            state_dir,
            "run",
            "examples/governance_workflow.yaml",
            "--input-file",
            "examples/governance_input.json",
        )["run"]
        run_id = str(run["run_id"])
        report = _run_cli(state_dir, "report", run_id)["report"]
        verification = _run_cli(state_dir, "verify", run_id)["verification"]

    _assert(run["status"] == "failed", "governance workflow should fail when budget is exhausted")
    _assert(
        report["summary"]["governance"] == {
            "within_limits": 1,
            "timeout": 0,
            "budget_exhausted": 1,
            "aborted": 0,
            "skipped": 1,
        },
        "report should summarize governance outcomes",
    )
    _assert(
        report["timeline"][1]["governance"]["status"] == "budget_exhausted",
        "second node should carry budget exhausted evidence",
    )
    _assert(verification["status"] == "passed", "governance verification should pass")

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "run_status": run["status"],
                "governance": report["summary"]["governance"],
                "verify_status": verification["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


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
