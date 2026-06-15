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

    report = run_cli("report", run_id, state_dir=tmp_path)
    assert report.returncode == 0
    report_payload = json.loads(report.stdout)
    assert report_payload["ok"] is True
    assert report_payload["report"]["run_id"] == run_id
    assert report_payload["report"]["summary"] == {"completed": 2, "failed": 0, "total_nodes": 2}

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    assert json.loads(verify.stdout)["verification"]["status"] == "passed"


def test_cli_report_summarizes_failed_tool_run(tmp_path):
    run = run_cli(
        "run",
        "examples/tool_failure_workflow.yaml",
        "--input-file",
        "examples/tool_input.json",
        state_dir=tmp_path,
    )
    assert run.returncode == 0
    run_id = json.loads(run.stdout)["run"]["run_id"]

    report = run_cli("report", run_id, state_dir=tmp_path)

    assert report.returncode == 0
    payload = json.loads(report.stdout)
    assert payload["ok"] is True
    assert payload["report"]["status"] == "failed"
    assert payload["report"]["failure"]["node_id"] == "failing_shell"
    assert "exit code 7" in payload["report"]["failure"]["message"]
    assert payload["report"]["timeline"][0]["tool"]["exit_code"] == 7


def test_cli_validate_reports_schema_contract_error(tmp_path):
    workflow_path = tmp_path / "invalid_workflow.yaml"
    workflow_path.write_text(
        """
id: invalid-cli
entrypoint: tool_node
nodes:
  tool_node:
    type: tool
    tool:
      adapter: shell
      command: "   "
""".strip(),
        encoding="utf-8",
    )

    validate = run_cli("validate", str(workflow_path), state_dir=tmp_path)

    assert validate.returncode == 2
    payload = json.loads(validate.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "shell tool node 'tool_node' requires non-empty command"
    assert validate.stderr == ""
