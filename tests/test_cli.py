import json
import subprocess
import sys
from pathlib import Path


def run_cli(*args, state_dir):
    return subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_validate_run_status_logs_and_verify(tmp_path):
    validate = run_cli("validate", "examples/hello_workflow.yaml", state_dir=tmp_path)
    assert validate.returncode == 0
    assert json.loads(validate.stdout)["ok"] is True

    run = run_cli(
        "run",
        "examples/hello_workflow.yaml",
        "--input-file",
        "examples/hello_input.json",
        state_dir=tmp_path,
    )
    assert run.returncode == 0
    run_payload = json.loads(run.stdout)
    run_id = run_payload["run"]["run_id"]
    assert run_payload["run"]["status"] == "completed"

    status = run_cli("status", run_id, state_dir=tmp_path)
    assert status.returncode == 0
    assert json.loads(status.stdout)["run"]["status"] == "completed"

    logs = run_cli("logs", run_id, state_dir=tmp_path)
    assert logs.returncode == 0
    assert [event["node_id"] for event in json.loads(logs.stdout)["events"]] == ["draft", "review"]

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    assert json.loads(verify.stdout)["verification"]["status"] == "passed"
