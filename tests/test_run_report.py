import hashlib
from pathlib import Path

from ai_infra import build_run_report, load_workflow, resume_workflow, run_workflow
from ai_infra.store import RunStore
from ai_infra.tools import default_tool_registry


def test_build_run_report_summarizes_successful_tool_run(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow_path = Path("examples/tool_workflow.yaml")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["run_id"] == result.run_id
    assert report["workflow_id"] == "tool-workflow"
    assert report["status"] == "completed"
    assert report["inputs"] == {"topic": "ABH"}
    assert report["provenance"]["workflow_source_path"] == str(workflow_path)
    assert report["provenance"]["workflow_snapshot_present"] is True
    assert "tool-workflow" in report["provenance"]["workflow_snapshot"]
    assert report["provenance"]["workflow_sha256"]
    assert report["provenance"]["inputs_sha256"]
    assert report["provenance"]["git_commit"] is None or len(report["provenance"]["git_commit"]) >= 7
    assert "python_version" in report["provenance"]["environment"]
    assert report["input_summary"] == {"type": "object", "keys": ["topic"]}
    assert report["outputs"]["python_echo"]["result"] == "ABH"
    assert report["output_summary"] == {
        "type": "object",
        "keys": ["http_echo", "python_echo", "shell_echo"],
    }
    assert report["failure"] is None
    assert [node["node_id"] for node in report["timeline"]] == [
        "python_echo",
        "shell_echo",
        "http_echo",
    ]
    assert report["summary"] == {
        "completed": 3,
        "failed": 0,
        "retried": 0,
        "total_nodes": 3,
        "total_events": 3,
    }
    assert report["timeline"][0]["tool"]["adapter"] == "python"
    assert report["timeline"][0]["tool"]["identity"] == "echo"
    assert report["timeline"][0]["tool"]["status"] == "completed"
    assert report["timeline"][0]["tool"]["reserved"] is False
    assert report["timeline"][0]["tool"]["input"] == {"args": {"value": "ABH"}, "name": "echo"}
    assert report["timeline"][0]["tool"]["output"] == {"result": "ABH"}
    assert report["timeline"][1]["tool"]["exit_code"] == 0
    assert report["timeline"][2]["tool"]["status_code"] == 200


def test_build_run_report_summarizes_redaction_governance_without_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INFRA_TEST_TOKEN", "env-secret-value")
    store = RunStore(tmp_path / "runs.sqlite")
    workflow_path = tmp_path / "redaction_report_workflow.yaml"
    workflow_path.write_text(
        """
id: redaction-report-workflow
entrypoint: secret_echo
governance:
  required_env:
    - AI_INFRA_TEST_TOKEN
  sensitive_paths:
    - inputs.api_key
    - node_output.secret_echo.result
    - tool_invocation.secret_echo.input.args.value
nodes:
  secret_echo:
    type: tool
    tool:
      adapter: python
      name: echo
      args:
        value: "{api_key}"
validations:
  - type: run_status
    equals: completed
""".strip(),
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"api_key": "sk-live-secret"}, store=store)
    report = build_run_report(result.run_id, store=store)

    assert report["inputs"]["api_key"] == "[REDACTED]"
    assert report["outputs"]["secret_echo"]["result"] == "[REDACTED]"
    assert report["provenance"]["environment"]["required_env"] == [
        {"name": "AI_INFRA_TEST_TOKEN", "present": True}
    ]
    [node] = report["timeline"]
    assert node["output"]["result"] == "[REDACTED]"
    assert node["tool"]["input"]["args"]["value"] == "[REDACTED]"
    assert node["redaction"]["status"] == "redacted"
    serialized = str(report)
    assert "sk-live-secret" not in serialized
    assert "env-secret-value" not in serialized


def test_build_run_report_summarizes_mcp_reserved_tool_boundary(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/mcp_reserved_workflow.yaml"))
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["status"] == "failed"
    assert report["failure"] == {
        "node_id": "future_mcp_tool",
        "message": "mcp adapter is reserved and not implemented",
    }
    [node] = report["timeline"]
    assert node["tool"] == {
        "adapter": "mcp",
        "identity": "local-memory.echo",
        "input": {
            "server": "local-memory",
            "tool": "echo",
            "args": {"topic": "ABH"},
        },
        "output": None,
        "error": "mcp adapter is reserved and not implemented",
        "status": "failed",
        "duration_ms": node["duration_ms"],
        "reserved": True,
    }


def test_build_run_report_includes_snapshot_after_workflow_source_mutates(tmp_path):
    workflow_path = tmp_path / "report_drift_workflow.yaml"
    original_source = """
id: report-drift-workflow
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Original {topic}"
validations:
  - type: run_status
    equals: completed
""".strip()
    workflow_path.write_text(original_source, encoding="utf-8")
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    workflow_path.write_text(
        """
id: report-drift-workflow
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

    report = build_run_report(result.run_id, store=store)

    assert "report-drift-workflow" in report["provenance"]["workflow_snapshot"]
    assert "Original {topic}" in report["provenance"]["workflow_snapshot"]
    assert "Changed {topic}" not in report["provenance"]["workflow_snapshot"]
    assert report["provenance"]["workflow_snapshot_present"] is True


def test_build_run_report_redacts_prompt_values_from_external_snapshot(tmp_path):
    workflow_path = tmp_path / "report_prompt_snapshot_workflow.yaml"
    workflow_path.write_text(
        """
id: report-prompt-snapshot
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: mock
      model: fake
      prompt: "Answer {secret}"
      max_steps: 1
validations:
  - type: run_status
    equals: completed
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"secret": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    snapshot = report["provenance"]["workflow_snapshot"]
    assert "Answer {secret}" not in snapshot
    assert "prompt: '[REDACTED_PROMPT]'" in snapshot or "prompt: [REDACTED_PROMPT]" in snapshot
    assert report["provenance"]["workflow_snapshot_present"] is True


def test_build_run_report_identifies_failed_tool_evidence(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/tool_failure_workflow.yaml"))
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["status"] == "failed"
    assert report["summary"] == {
        "completed": 0,
        "failed": 1,
        "retried": 0,
        "total_nodes": 1,
        "total_events": 1,
    }
    assert report["failure"] == {
        "node_id": "failing_shell",
        "message": "shell tool exited with exit code 7",
    }
    [node] = report["timeline"]
    assert node["node_id"] == "failing_shell"
    assert node["status"] == "failed"
    assert node["duration_ms"] >= 0
    assert node["tool"]["adapter"] == "shell"
    assert node["tool"]["exit_code"] == 7
    assert node["tool"]["stdout"].strip() == "expected failure"
    assert node["tool"]["stderr"] == ""
    assert "exit code 7" in node["tool"]["error"]


def test_build_run_report_summarizes_retry_policy_evidence(tmp_path):
    attempts = {"count": 0}

    def flaky_tool(args):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary outage")
        return "recovered"

    default_tool_registry.register_python("report_flaky_once", flaky_tool)
    workflow_path = tmp_path / "report_retry_workflow.yaml"
    workflow_path.write_text(
        """
id: report-retry-workflow
entrypoint: flaky
nodes:
  flaky:
    type: tool
    policy:
      on_failure: halt
      max_attempts: 2
    tool:
      adapter: python
      name: report_flaky_once
validations:
  - type: run_status
    equals: completed
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["status"] == "completed"
    assert report["summary"] == {
        "completed": 1,
        "failed": 0,
        "retried": 1,
        "total_nodes": 1,
        "total_events": 2,
    }
    assert report["failure"] is None
    [node] = report["timeline"]
    assert node["node_id"] == "flaky"
    assert node["status"] == "completed"
    assert node["attempts"] == 2
    assert node["policy"]["on_failure"] == "halt"
    assert node["policy"]["max_attempts"] == 2
    assert node["policy"]["outcome"] == "retry_succeeded"
    assert node["attempt_events"][0]["status"] == "failed"
    assert node["attempt_events"][0]["policy_outcome"] == "retrying"
    assert node["attempt_events"][1]["status"] == "completed"
    assert node["attempt_events"][1]["policy_outcome"] == "retry_succeeded"


def test_build_run_report_identifies_retry_exhausted_failure(tmp_path):
    def always_fails(args):
        raise RuntimeError("still down")

    default_tool_registry.register_python("report_always_fails", always_fails)
    workflow_path = tmp_path / "report_retry_exhausted_workflow.yaml"
    workflow_path.write_text(
        """
id: report-retry-exhausted-workflow
entrypoint: flaky
nodes:
  flaky:
    type: tool
    policy:
      on_failure: halt
      max_attempts: 2
    tool:
      adapter: python
      name: report_always_fails
validations:
  - type: run_status
    equals: failed
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["status"] == "failed"
    assert report["summary"]["retried"] == 1
    assert report["failure"] == {
        "node_id": "flaky",
        "message": "still down",
        "policy_outcome": "retry_exhausted",
    }
    [node] = report["timeline"]
    assert node["attempts"] == 2
    assert node["policy"]["outcome"] == "retry_exhausted"


def test_build_run_report_summarizes_output_contract_status(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow_path = tmp_path / "report_output_contract_workflow.yaml"
    workflow_path.write_text(
        """
id: report-output-contract-workflow
entrypoint: python_echo
nodes:
  python_echo:
    type: tool
    contract:
      output:
        type: object
        required_fields:
          result: string
          adapter: string
    tool:
      adapter: python
      name: echo
      args:
        value: "{topic}"
validations:
  - type: run_status
    equals: completed
  - type: node_contract
    node: python_echo
    equals: passed
""".strip(),
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["summary"]["contracts"] == {
        "passed": 1,
        "failed": 0,
        "unchecked": 0,
    }
    [node] = report["timeline"]
    assert node["contract"] == {
        "output": {
            "status": "passed",
            "type": "object",
            "required_fields": {
                "result": "string",
                "adapter": "string",
            },
            "missing_fields": [],
            "type_errors": [],
        }
    }


def test_build_run_report_identifies_output_contract_failure(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow_path = tmp_path / "report_output_contract_failure_workflow.yaml"
    workflow_path.write_text(
        """
id: report-output-contract-failure-workflow
entrypoint: python_echo
nodes:
  python_echo:
    type: tool
    contract:
      output:
        type: object
        required_fields:
          missing: string
    tool:
      adapter: python
      name: echo
      args:
        value: "{topic}"
validations:
  - type: run_status
    equals: failed
  - type: node_contract
    node: python_echo
    equals: failed
""".strip(),
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["status"] == "failed"
    assert report["summary"]["contracts"] == {
        "passed": 0,
        "failed": 1,
        "unchecked": 0,
    }
    assert report["failure"] == {
        "node_id": "python_echo",
        "message": "output contract failed for node 'python_echo': missing field 'missing'",
        "contract_status": "failed",
    }
    [node] = report["timeline"]
    assert node["contract"]["output"]["status"] == "failed"
    assert node["contract"]["output"]["missing_fields"] == ["missing"]


def test_build_run_report_summarizes_resume_evidence(tmp_path):
    calls = {"prepare": 0, "flaky": 0}

    def prepare(args):
        calls["prepare"] += 1
        return f"prepared:{args['value']}"

    def flaky(args):
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise RuntimeError("temporary report failure")
        return f"finished:{args['value']}"

    default_tool_registry.register_python("report_resume_prepare", prepare)
    default_tool_registry.register_python("report_resume_flaky", flaky)
    workflow_path = tmp_path / "report_resume_workflow.yaml"
    workflow_path.write_text(
        """
id: report-resume-workflow
entrypoint: prepare
nodes:
  prepare:
    type: tool
    next: flaky
    tool:
      adapter: python
      name: report_resume_prepare
      args:
        value: "{topic}"
  flaky:
    type: tool
    tool:
      adapter: python
      name: report_resume_flaky
      args:
        value: "{prepare.result}"
validations:
  - type: run_status
    equals: completed
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    first = run_workflow(workflow, {"topic": "ABH"}, store=store)

    resumed = resume_workflow(first.run_id, workflow, store=store)
    report = build_run_report(resumed.run_id, store=store)

    assert report["status"] == "completed"
    assert report["summary"]["resume"] == {"skipped": 1, "rerun": 1, "run": 0}
    assert [node["resume"]["action"] for node in report["timeline"]] == ["skipped", "rerun"]
    assert report["timeline"][0]["status"] == "skipped"
    assert report["timeline"][0]["resume"]["source_event_status"] == "completed"
    assert report["timeline"][1]["status"] == "completed"
    assert report["timeline"][1]["resume"]["action"] == "rerun"


def test_build_run_report_summarizes_artifact_evidence(tmp_path):
    artifact_path = tmp_path / "report-artifact.txt"

    def write_artifact(args):
        path = Path(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return {"path": path.as_posix()}

    default_tool_registry.register_python("report_write_artifact", write_artifact)
    workflow_path = tmp_path / "report_artifact_workflow.yaml"
    workflow_path.write_text(
        f"""
id: report-artifact-workflow
entrypoint: writer
nodes:
  writer:
    type: tool
    artifacts:
      - name: report
        path: "{artifact_path.as_posix()}"
        content_type: text/plain
    tool:
      adapter: python
      name: report_write_artifact
      args:
        path: "{artifact_path.as_posix()}"
        content: "ABH artifact"
validations:
  - type: run_status
    equals: completed
  - type: node_artifact
    node: writer
    name: report
    exists: true
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["summary"]["artifacts"] == {
        "declared": 1,
        "present": 1,
        "missing": 0,
    }
    [node] = report["timeline"]
    assert node["artifacts"] == [
        {
            "name": "report",
            "path": artifact_path.as_posix(),
            "stored_path": (tmp_path / "artifacts" / result.run_id / "writer" / "report" / "report-artifact.txt").as_posix(),
            "content_type": "text/plain",
            "exists": True,
            "size_bytes": len("ABH artifact"),
            "sha256": hashlib.sha256(b"ABH artifact").hexdigest(),
        }
    ]


def test_build_run_report_summarizes_governance_evidence(tmp_path):
    workflow_path = tmp_path / "report_governance_workflow.yaml"
    workflow_path.write_text(
        """
id: report-governance-workflow
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
    node: second
    equals: budget_exhausted
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["status"] == "failed"
    assert report["summary"]["governance"] == {
        "within_limits": 1,
        "timeout": 0,
        "budget_exhausted": 1,
        "aborted": 0,
        "skipped": 1,
    }
    assert report["failure"] == {
        "node_id": "second",
        "message": "workflow execution budget exhausted before node 'second'",
        "governance_status": "budget_exhausted",
    }
    assert [node["node_id"] for node in report["timeline"]] == ["first", "second"]
    assert report["timeline"][0]["governance"]["status"] == "within_limits"
    assert report["timeline"][1]["status"] == "skipped"
    assert report["timeline"][1]["governance"] == {
        "status": "budget_exhausted",
        "reason": "max_node_executions",
        "max_node_executions": 1,
        "executions_used": 1,
    }
