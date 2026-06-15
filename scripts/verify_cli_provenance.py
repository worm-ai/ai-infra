from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-provenance-") as temp:
        state_dir = Path(temp) / "state"
        _run_cli("validate", "examples/tool_workflow.yaml", state_dir=state_dir)
        run_payload = _run_cli(
            "run",
            "examples/tool_workflow.yaml",
            "--input-file",
            "examples/tool_input.json",
            state_dir=state_dir,
        )
        run_id = run_payload["run"]["run_id"]

        report_payload = _run_cli("report", run_id, state_dir=state_dir)
        provenance = report_payload["report"]["provenance"]
        assert provenance["workflow_sha256"]
        assert provenance["inputs_sha256"]
        assert "id: tool-workflow" in provenance["workflow_snapshot"]

        verify_payload = _run_cli("verify", run_id, state_dir=state_dir)
        assert verify_payload["verification"]["status"] == "passed"
        assert verify_payload["verification"]["checks"][0]["type"] == "workflow_source_integrity"

        drift_summary = _verify_drift_detection(Path(temp) / "drift", state_dir=Path(temp) / "drift-state")
        print(
            json.dumps(
                {
                    "ok": True,
                    "run_id": run_id,
                    "workflow_sha256": provenance["workflow_sha256"],
                    "inputs_sha256": provenance["inputs_sha256"],
                    "verify_status": verify_payload["verification"]["status"],
                    "drift": drift_summary,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return 0


def _verify_drift_detection(work_dir: Path, state_dir: Path) -> dict:
    work_dir.mkdir(parents=True)
    workflow_path = work_dir / "workflow.yaml"
    input_path = work_dir / "input.json"
    original_source = """
id: cli-provenance-drift
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Original {topic}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: draft
""".strip()
    workflow_path.write_text(original_source, encoding="utf-8")
    input_path.write_text('{"topic": "ABH"}', encoding="utf-8")
    run_payload = _run_cli("run", str(workflow_path), "--input-file", str(input_path), state_dir=state_dir)
    run_id = run_payload["run"]["run_id"]

    workflow_path.write_text(
        """
id: cli-provenance-drift
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Changed {topic}"
validations:
  - type: run_status
    equals: failed
""".strip(),
        encoding="utf-8",
    )

    report_payload = _run_cli("report", run_id, state_dir=state_dir)
    assert report_payload["report"]["provenance"]["workflow_snapshot"] == original_source

    verify_payload = _run_cli("verify", run_id, state_dir=state_dir, expected_returncode=1)
    integrity_check = verify_payload["verification"]["checks"][0]
    assert verify_payload["verification"]["status"] == "failed"
    assert integrity_check["type"] == "workflow_source_integrity"
    assert integrity_check["status"] == "failed"
    assert "changed since run" in integrity_check["message"]
    return {
        "run_id": run_id,
        "report_snapshot_matches_original": True,
        "verify_status": verify_payload["verification"]["status"],
        "integrity_status": integrity_check["status"],
    }


def _run_cli(*args: str, state_dir: Path, expected_returncode: int = 0) -> dict:
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
    if result.returncode != expected_returncode:
        raise RuntimeError(
            f"command {' '.join(args)} exited {result.returncode}, "
            f"expected {expected_returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
