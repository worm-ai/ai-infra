import json
import subprocess
import sys
from pathlib import Path
import zipfile


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
    assert report_payload["report"]["summary"] == {
        "completed": 2,
        "failed": 0,
        "retried": 0,
        "total_nodes": 2,
        "total_events": 2,
    }
    assert report_payload["report"]["provenance"]["workflow_sha256"]
    assert report_payload["report"]["provenance"]["inputs_sha256"]

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


def test_cli_verify_reports_workflow_source_drift(tmp_path):
    workflow_path = tmp_path / "cli_drift_workflow.yaml"
    input_path = tmp_path / "input.json"
    workflow_path.write_text(
        """
id: cli-drift-workflow
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: draft
""".strip(),
        encoding="utf-8",
    )
    input_path.write_text('{"topic": "ABH"}', encoding="utf-8")
    run = run_cli("run", str(workflow_path), "--input-file", str(input_path), state_dir=tmp_path)
    assert run.returncode == 0
    run_id = json.loads(run.stdout)["run"]["run_id"]

    workflow_path.write_text(
        """
id: cli-drift-workflow
entrypoint: changed
nodes:
  changed:
    type: template
    template: "Changed {topic}"
validations:
  - type: run_status
    equals: completed
""".strip(),
        encoding="utf-8",
    )

    verify = run_cli("verify", run_id, state_dir=tmp_path)

    assert verify.returncode == 1
    payload = json.loads(verify.stdout)
    assert payload["ok"] is False
    assert payload["verification"]["status"] == "failed"
    [integrity_check] = [
        check
        for check in payload["verification"]["checks"]
        if check["type"] == "workflow_source_integrity"
    ]
    assert integrity_check["status"] == "failed"
    assert "changed since run" in integrity_check["message"]


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


def test_cli_retry_policy_report_and_verify(tmp_path):
    validate = run_cli("validate", "examples/retry_workflow.yaml", state_dir=tmp_path)
    assert validate.returncode == 0

    run = run_cli(
        "run",
        "examples/retry_workflow.yaml",
        "--input-file",
        "examples/retry_input.json",
        state_dir=tmp_path,
    )
    assert run.returncode == 0
    run_payload = json.loads(run.stdout)
    run_id = run_payload["run"]["run_id"]
    assert run_payload["run"]["status"] == "completed"

    report = run_cli("report", run_id, state_dir=tmp_path)
    assert report.returncode == 0
    report_payload = json.loads(report.stdout)
    assert report_payload["report"]["summary"]["retried"] == 1
    [node] = report_payload["report"]["timeline"]
    assert node["node_id"] == "flaky_python"
    assert node["attempts"] == 2
    assert node["policy"]["outcome"] == "retry_succeeded"

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    checks = {check["type"]: check for check in json.loads(verify.stdout)["verification"]["checks"]}
    assert checks["node_attempts"]["status"] == "passed"
    assert checks["node_policy_outcome"]["status"] == "passed"


def test_cli_retry_exhausted_policy_report_and_verify(tmp_path):
    validate = run_cli("validate", "examples/retry_exhausted_workflow.yaml", state_dir=tmp_path)
    assert validate.returncode == 0

    run = run_cli(
        "run",
        "examples/retry_exhausted_workflow.yaml",
        "--input-file",
        "examples/retry_input.json",
        state_dir=tmp_path,
    )
    assert run.returncode == 0
    run_id = json.loads(run.stdout)["run"]["run_id"]

    report = run_cli("report", run_id, state_dir=tmp_path)
    assert report.returncode == 0
    report_payload = json.loads(report.stdout)
    assert report_payload["report"]["status"] == "failed"
    assert report_payload["report"]["failure"]["policy_outcome"] == "retry_exhausted"
    assert report_payload["report"]["timeline"][0]["attempts"] == 2

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    assert json.loads(verify.stdout)["verification"]["status"] == "passed"


def test_cli_output_contract_report_and_verify(tmp_path):
    validate = run_cli("validate", "examples/output_contract_workflow.yaml", state_dir=tmp_path)
    assert validate.returncode == 0

    run = run_cli(
        "run",
        "examples/output_contract_workflow.yaml",
        "--input-file",
        "examples/output_contract_input.json",
        state_dir=tmp_path,
    )
    assert run.returncode == 0
    run_payload = json.loads(run.stdout)
    run_id = run_payload["run"]["run_id"]
    assert run_payload["run"]["status"] == "completed"

    report = run_cli("report", run_id, state_dir=tmp_path)
    assert report.returncode == 0
    report_payload = json.loads(report.stdout)
    assert report_payload["report"]["summary"]["contracts"] == {
        "passed": 1,
        "failed": 0,
        "unchecked": 0,
    }
    [node] = report_payload["report"]["timeline"]
    assert node["contract"]["output"]["status"] == "passed"

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    checks = {check["type"]: check for check in json.loads(verify.stdout)["verification"]["checks"]}
    assert checks["node_contract"]["status"] == "passed"


def test_cli_output_contract_failure_report_and_verify(tmp_path):
    validate = run_cli("validate", "examples/output_contract_failure_workflow.yaml", state_dir=tmp_path)
    assert validate.returncode == 0

    run = run_cli(
        "run",
        "examples/output_contract_failure_workflow.yaml",
        "--input-file",
        "examples/output_contract_input.json",
        state_dir=tmp_path,
    )
    assert run.returncode == 0
    run_id = json.loads(run.stdout)["run"]["run_id"]

    report = run_cli("report", run_id, state_dir=tmp_path)
    assert report.returncode == 0
    report_payload = json.loads(report.stdout)
    assert report_payload["report"]["status"] == "failed"
    assert report_payload["report"]["summary"]["contracts"] == {
        "passed": 0,
        "failed": 1,
        "unchecked": 0,
    }
    assert report_payload["report"]["failure"]["contract_status"] == "failed"

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    assert json.loads(verify.stdout)["verification"]["status"] == "passed"


def test_cli_resume_report_and_verify(tmp_path):
    workflow_path = tmp_path / "cli_resume_workflow.yaml"
    input_path = tmp_path / "cli_resume_input.json"
    marker_path = (tmp_path / "cli_resume_marker.txt").as_posix()
    workflow_path.write_text(
        """
id: cli-resume-workflow
entrypoint: prepare
nodes:
  prepare:
    type: tool
    next: flaky
    tool:
      adapter: python
      name: echo
      args:
        value: "{topic}"
  flaky:
    type: tool
    next: downstream
    tool:
      adapter: shell
      command: >-
        python -c "from pathlib import Path; import sys; marker=Path(sys.argv[1]); value=sys.argv[2]; marker.parent.mkdir(parents=True, exist_ok=True); sys.stdout.write('finished:'+value) if marker.exists() else (marker.write_text('seen'), sys.exit(9))" {marker} {prepare.result}
      timeout_seconds: 5
  downstream:
    type: template
    template: "Done {flaky.stdout}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: downstream
  - type: node_resume_action
    node: prepare
    equals: skipped
  - type: node_resume_action
    node: flaky
    equals: rerun
  - type: node_resume_action
    node: downstream
    equals: run
""".strip(),
        encoding="utf-8",
    )
    input_path.write_text(json.dumps({"topic": "ABH", "marker": marker_path}), encoding="utf-8")
    run = run_cli("run", str(workflow_path), "--input-file", str(input_path), state_dir=tmp_path)
    assert run.returncode == 0
    run_payload = json.loads(run.stdout)
    run_id = run_payload["run"]["run_id"]
    assert run_payload["run"]["status"] == "failed"

    resume = run_cli("resume", run_id, "--workflow", str(workflow_path), state_dir=tmp_path)
    assert resume.returncode == 0
    resume_payload = json.loads(resume.stdout)
    assert resume_payload["run"]["run_id"] == run_id
    assert resume_payload["run"]["status"] == "completed"
    assert resume_payload["run"]["outputs"]["downstream"] == "Done finished:ABH"

    report = run_cli("report", run_id, state_dir=tmp_path)
    assert report.returncode == 0
    report_payload = json.loads(report.stdout)
    assert report_payload["report"]["summary"]["resume"] == {"skipped": 1, "rerun": 1, "run": 1}
    assert [node["resume"]["action"] for node in report_payload["report"]["timeline"]] == [
        "skipped",
        "rerun",
        "run",
    ]

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    checks = {check["type"]: check for check in json.loads(verify.stdout)["verification"]["checks"]}
    assert checks["node_resume_action"]["status"] == "passed"


def test_cli_artifact_report_verify_and_export_bundle(tmp_path):
    artifact_path = tmp_path / "cli_artifact.txt"
    workflow_path = tmp_path / "cli_artifact_workflow.yaml"
    input_path = tmp_path / "cli_artifact_input.json"
    workflow_path.write_text(
        f"""
id: cli-artifact-workflow
entrypoint: writer
nodes:
  writer:
    type: tool
    artifacts:
      - name: note
        path: "{artifact_path.as_posix()}"
        content_type: text/plain
    tool:
      adapter: shell
      command: >-
        python -c "from pathlib import Path; import sys; path=Path(sys.argv[1]); path.write_text(sys.argv[2], encoding='utf-8'); print(path)" {artifact_path.as_posix()} "{{topic}} artifact"
validations:
  - type: run_status
    equals: completed
  - type: node_artifact
    node: writer
    name: note
    exists: true
""".strip(),
        encoding="utf-8",
    )
    input_path.write_text(json.dumps({"topic": "ABH"}), encoding="utf-8")

    validate = run_cli("validate", str(workflow_path), state_dir=tmp_path)
    assert validate.returncode == 0

    run = run_cli("run", str(workflow_path), "--input-file", str(input_path), state_dir=tmp_path)
    assert run.returncode == 0
    run_id = json.loads(run.stdout)["run"]["run_id"]

    report = run_cli("report", run_id, state_dir=tmp_path)
    assert report.returncode == 0
    report_payload = json.loads(report.stdout)
    assert report_payload["report"]["summary"]["artifacts"] == {
        "declared": 1,
        "present": 1,
        "missing": 0,
    }

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    checks = {check["type"]: check for check in json.loads(verify.stdout)["verification"]["checks"]}
    assert checks["node_artifact"]["status"] == "passed"

    bundle = run_cli("export-bundle", run_id, "--output-dir", str(tmp_path / "bundles"), state_dir=tmp_path)
    assert bundle.returncode == 0
    bundle_payload = json.loads(bundle.stdout)
    bundle_path = Path(bundle_payload["bundle"]["path"])
    assert bundle_path.exists()
    assert bundle_path.name == f"{run_id}-evidence-bundle.zip"

    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        assert {
            "manifest.json",
            "report.json",
            "workflow_snapshot.yaml",
            "inputs.json",
            "events.json",
            "artifacts/writer/note/cli_artifact.txt",
        }.issubset(names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["run_id"] == run_id
        assert manifest["workflow_id"] == "cli-artifact-workflow"
        assert manifest["artifacts"][0]["archive_path"] == "artifacts/writer/note/cli_artifact.txt"
        assert archive.read("artifacts/writer/note/cli_artifact.txt").decode("utf-8") == "ABH artifact"


def test_cli_example_artifact_workflow_uses_input_artifact_path(tmp_path):
    artifact_path = tmp_path / "isolated_artifact.txt"
    input_path = tmp_path / "artifact_input.json"
    input_path.write_text(
        json.dumps({"topic": "ABH", "artifact_path": artifact_path.as_posix()}),
        encoding="utf-8",
    )

    run = run_cli(
        "run",
        "examples/artifact_workflow.yaml",
        "--input-file",
        str(input_path),
        state_dir=tmp_path / "state",
    )
    assert run.returncode == 0
    run_id = json.loads(run.stdout)["run"]["run_id"]

    report = run_cli("report", run_id, state_dir=tmp_path / "state")
    assert report.returncode == 0
    artifact = json.loads(report.stdout)["report"]["timeline"][0]["artifacts"][0]

    assert artifact["path"] == artifact_path.as_posix()
    assert artifact_path.read_text(encoding="utf-8") == "ABH artifact evidence"


def test_cli_governance_report_and_verify(tmp_path):
    workflow_path = tmp_path / "cli_governance_workflow.yaml"
    input_path = tmp_path / "cli_governance_input.json"
    workflow_path.write_text(
        """
id: cli-governance-workflow
entrypoint: first
governance:
  max_node_executions: 1
nodes:
  first:
    type: template
    next: second
    template: "First {topic}"
  second:
    type: template
    template: "Second {first}"
validations:
  - type: run_status
    equals: failed
  - type: node_governance
    node: first
    equals: within_limits
  - type: node_governance
    node: second
    equals: budget_exhausted
""".strip(),
        encoding="utf-8",
    )
    input_path.write_text(json.dumps({"topic": "ABH"}), encoding="utf-8")

    validate = run_cli("validate", str(workflow_path), state_dir=tmp_path)
    assert validate.returncode == 0

    run = run_cli("run", str(workflow_path), "--input-file", str(input_path), state_dir=tmp_path)
    assert run.returncode == 0
    run_payload = json.loads(run.stdout)
    run_id = run_payload["run"]["run_id"]
    assert run_payload["run"]["status"] == "failed"

    report = run_cli("report", run_id, state_dir=tmp_path)
    assert report.returncode == 0
    report_payload = json.loads(report.stdout)
    assert report_payload["report"]["summary"]["governance"] == {
        "within_limits": 1,
        "timeout": 0,
        "budget_exhausted": 1,
        "aborted": 0,
        "skipped": 1,
    }
    assert report_payload["report"]["timeline"][1]["governance"]["status"] == "budget_exhausted"

    verify = run_cli("verify", run_id, state_dir=tmp_path)
    assert verify.returncode == 0
    checks = {check["message"] for check in json.loads(verify.stdout)["verification"]["checks"]}
    assert "node 'first' governance status is 'within_limits', expected 'within_limits'" in checks
    assert "node 'second' governance status is 'budget_exhausted', expected 'budget_exhausted'" in checks
