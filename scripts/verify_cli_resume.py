from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        state_dir = tmp_path / "state"
        input_path = tmp_path / "resume_input.json"
        marker_path = tmp_path / "resume_marker.txt"
        input_path.write_text(
            json.dumps({"topic": "ABH", "marker": marker_path.as_posix()}),
            encoding="utf-8",
        )

        first = _run_cli(
            state_dir,
            "run",
            "examples/resume_workflow.yaml",
            "--input-file",
            str(input_path),
        )["run"]
        run_id = str(first["run_id"])
        resumed = _run_cli(
            state_dir,
            "resume",
            run_id,
            "--workflow",
            "examples/resume_workflow.yaml",
        )["run"]
        report = _run_cli(state_dir, "report", run_id)["report"]
        verification = _run_cli(state_dir, "verify", run_id)["verification"]

    _assert(first["status"] == "failed", "initial resume workflow run should fail")
    _assert(resumed["status"] == "completed", "resumed workflow should complete")
    _assert(
        resumed["outputs"]["downstream"] == "Done finished:ABH",
        "resumed workflow should produce downstream output",
    )
    _assert(
        report["summary"]["resume"] == {"skipped": 1, "rerun": 1, "run": 1},
        "report should summarize resume actions",
    )
    _assert(verification["status"] == "passed", "resume verification should pass")

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "first_status": first["status"],
                "resumed_status": resumed["status"],
                "resume": report["summary"]["resume"],
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
