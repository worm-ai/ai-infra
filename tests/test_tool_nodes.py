import json
import zipfile
from pathlib import Path

from ai_infra import (
    ToolInvocation,
    ToolInvocationEvidence,
    build_run_report,
    export_evidence_bundle,
    get_run,
    load_workflow,
    run_workflow,
    validate_stored_run,
)
from ai_infra.store import RunStore
from ai_infra.tools import build_tool_invocation


def test_tool_nodes_execute_and_persist_audit_evidence(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/tool_workflow.yaml"))

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "completed"
    assert result.outputs["python_echo"]["result"] == "ABH"
    assert result.outputs["shell_echo"]["stdout"].strip() == "ABH"
    assert result.outputs["http_echo"]["status_code"] == 200

    saved = get_run(result.run_id, store=store)
    tool_events = {event.node_id: event for event in saved.events}
    assert tool_events["python_echo"].status == "completed"
    assert tool_events["shell_echo"].output["exit_code"] == 0
    assert tool_events["http_echo"].output["body"]["topic"] == "ABH"
    assert tool_events["http_echo"].output["duration_ms"] >= 0
    assert tool_events["python_echo"].output["tool_invocation"] == {
        "adapter": "python",
        "identity": "echo",
        "input": {"args": {"value": "ABH"}, "name": "echo"},
        "output": {"result": "ABH"},
        "error": None,
        "status": "completed",
        "duration_ms": tool_events["python_echo"].output["duration_ms"],
        "reserved": False,
    }
    assert tool_events["shell_echo"].output["tool_invocation"]["adapter"] == "shell"
    assert tool_events["shell_echo"].output["tool_invocation"]["identity"].startswith("python -c")
    assert tool_events["shell_echo"].output["tool_invocation"]["status"] == "completed"
    assert tool_events["http_echo"].output["tool_invocation"]["adapter"] == "http"
    assert tool_events["http_echo"].output["tool_invocation"]["identity"] == "POST memory://echo"

    verification = validate_stored_run(result.run_id, store=store)
    assert verification.status == "passed"


def test_tool_node_expected_failure_is_auditable(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/tool_failure_workflow.yaml"))

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "failed"
    assert result.outputs["failing_shell"]["exit_code"] == 7

    saved = get_run(result.run_id, store=store)
    event = saved.events[-1]
    assert event.node_id == "failing_shell"
    assert event.status == "failed"
    assert "exit code 7" in event.output["error"]
    assert event.output["tool_invocation"]["adapter"] == "shell"
    assert event.output["tool_invocation"]["status"] == "failed"
    assert event.output["tool_invocation"]["error"] == "shell tool exited with exit code 7"

    verification = validate_stored_run(result.run_id, store=store)
    assert verification.status == "passed"


def test_build_tool_invocation_normalizes_adapter_identity_and_inputs():
    invocation = build_tool_invocation(
        {
            "adapter": "http",
            "method": "POST",
            "url": "memory://echo",
            "json": {"topic": "{topic}"},
        },
        {"topic": "ABH"},
    )

    assert invocation == ToolInvocation(
        adapter="http",
        identity="POST memory://echo",
        input={
            "method": "POST",
            "url": "memory://echo",
            "json": {"topic": "ABH"},
        },
        reserved=False,
    )


def test_build_tool_invocation_enables_explicit_local_mcp_runtime():
    invocation = build_tool_invocation(
        {
            "adapter": "mcp",
            "runtime": "local",
            "server": "local-memory",
            "tool": "echo",
            "args": {"topic": "{topic}"},
            "timeout_seconds": 3,
        },
        {"topic": "ABH"},
    )

    assert invocation == ToolInvocation(
        adapter="mcp",
        identity="local-memory.echo",
        input={
            "runtime": "local",
            "server": "local-memory",
            "tool": "echo",
            "args": {"topic": "ABH"},
            "timeout_seconds": 3,
        },
        reserved=False,
    )


def test_tool_invocation_evidence_is_sdk_serializable():
    evidence = ToolInvocationEvidence(
        adapter="python",
        identity="echo",
        input={"args": {"value": "ABH"}, "name": "echo"},
        output={"result": "ABH"},
        error=None,
        status="completed",
        duration_ms=3,
        reserved=False,
    )

    assert evidence.to_dict() == {
        "adapter": "python",
        "identity": "echo",
        "input": {"args": {"value": "ABH"}, "name": "echo"},
        "output": {"result": "ABH"},
        "error": None,
        "status": "completed",
        "duration_ms": 3,
        "reserved": False,
    }


def test_http_tool_execution_preserves_timeout_for_real_urls(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"accepted": true}'

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = request.data
        return FakeResponse()

    monkeypatch.setattr("ai_infra.tools.urllib.request.urlopen", fake_urlopen)
    execution = build_tool_invocation(
        {
            "adapter": "http",
            "method": "POST",
            "url": "https://example.test/echo",
            "json": {"topic": "{topic}"},
            "timeout_seconds": 7,
        },
        {"topic": "ABH"},
    )

    from ai_infra.tools import ToolRegistry

    result = ToolRegistry().execute(
        {
            "adapter": "http",
            "method": "POST",
            "url": "https://example.test/echo",
            "json": {"topic": "{topic}"},
            "timeout_seconds": 7,
        },
        {"topic": "ABH"},
    )

    assert execution.input["timeout_seconds"] == 7
    assert result.status == "completed"
    assert result.output["status_code"] == 202
    assert result.output["body"] == {"accepted": True}
    assert result.output["tool_invocation"]["identity"] == "POST https://example.test/echo"
    assert captured == {
        "method": "POST",
        "url": "https://example.test/echo",
        "timeout": 7,
        "body": b'{"topic": "ABH"}',
    }


def test_mcp_reserved_tool_node_fails_with_deterministic_invocation_evidence(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/mcp_reserved_workflow.yaml"))

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "failed"
    output = result.outputs["future_mcp_tool"]
    assert output["adapter"] == "mcp"
    assert output["error"] == "mcp adapter is reserved and not implemented"
    assert output["tool_invocation"] == {
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
        "duration_ms": output["duration_ms"],
        "reserved": True,
    }

    saved = get_run(result.run_id, store=store)
    [event] = saved.events
    assert event.status == "failed"
    assert event.output["tool_invocation"]["reserved"] is True

    verification = validate_stored_run(result.run_id, store=store)
    assert verification.status == "passed"


def test_local_mcp_tool_node_completes_with_invocation_evidence(tmp_path):
    workflow_path = tmp_path / "mcp_runtime_workflow.yaml"
    workflow_path.write_text(
        """
id: mcp-runtime
entrypoint: mcp_echo
nodes:
  mcp_echo:
    type: tool
    tool:
      adapter: mcp
      runtime: local
      server: local-memory
      tool: echo
      timeout_seconds: 3
      args:
        topic: "{topic}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: mcp_echo
  - type: assertion
    source: tool_invocation
    node: mcp_echo
    path: reserved
    equals: false
  - type: assertion
    source: node_output
    node: mcp_echo
    path: mcp.status
    equals: completed
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "completed"
    output = result.outputs["mcp_echo"]
    assert output["adapter"] == "mcp"
    assert output["result"] == {"topic": "ABH"}
    assert output["mcp"]["request"] == {
        "args_keys": ["topic"],
        "timeout_seconds": 3,
    }
    assert output["mcp"]["response"] == {
        "result_type": "object",
        "result_keys": ["topic"],
    }
    assert output["tool_invocation"] == {
        "adapter": "mcp",
        "identity": "local-memory.echo",
        "input": {
            "runtime": "local",
            "server": "local-memory",
            "tool": "echo",
            "args": {"topic": "ABH"},
            "timeout_seconds": 3,
        },
        "output": {
            "result": {"topic": "ABH"},
            "mcp": {
                "runtime": "local",
                "server": "local-memory",
                "tool": "echo",
                "status": "completed",
                "request": {"args_keys": ["topic"], "timeout_seconds": 3},
                "response": {"result_type": "object", "result_keys": ["topic"]},
            },
        },
        "error": None,
        "status": "completed",
        "duration_ms": output["duration_ms"],
        "reserved": False,
    }

    saved = get_run(result.run_id, store=store)
    [event] = saved.events
    assert event.status == "completed"
    assert event.output["tool_invocation"]["reserved"] is False
    report = build_run_report(result.run_id, store=store)
    assert report["timeline"][0]["tool"]["mcp"]["status"] == "completed"
    assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_local_mcp_tool_node_failures_are_actionable(tmp_path):
    workflow_path = tmp_path / "mcp_failure_workflow.yaml"
    workflow_path.write_text(
        """
id: mcp-runtime-failure
entrypoint: mcp_fail
nodes:
  mcp_fail:
    type: tool
    tool:
      adapter: mcp
      runtime: local
      server: local-memory
      tool: fail
      timeout_seconds: 3
      args:
        message: "blocked {topic}"
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: mcp_fail
  - type: assertion
    source: node_output
    node: mcp_fail
    path: mcp.status
    equals: tool_error
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "failed"
    output = result.outputs["mcp_fail"]
    assert output["error"] == "mcp tool local-memory.fail failed: blocked ABH"
    assert output["mcp"]["status"] == "tool_error"
    assert output["mcp"]["error"] == {
        "type": "tool_error",
        "message": "mcp tool local-memory.fail failed: blocked ABH",
        "retryable": False,
    }
    assert output["tool_invocation"]["status"] == "failed"
    assert output["tool_invocation"]["reserved"] is False
    assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_local_mcp_timeout_and_malformed_response_are_auditable(tmp_path):
    cases = [
        ("timeout", "timeout", "mcp tool local-memory.timeout timed out after 1s"),
        ("malformed", "malformed_response", "mcp tool local-memory.malformed returned malformed response"),
    ]
    for tool_name, status, message in cases:
        workflow_path = tmp_path / f"mcp_{tool_name}_workflow.yaml"
        workflow_path.write_text(
            f"""
id: mcp-runtime-{tool_name}
entrypoint: mcp_failure
nodes:
  mcp_failure:
    type: tool
    tool:
      adapter: mcp
      runtime: local
      server: local-memory
      tool: {tool_name}
      timeout_seconds: 1
      args:
        topic: "{{topic}}"
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: mcp_failure
  - type: assertion
    source: node_output
    node: mcp_failure
    path: mcp.status
    equals: {status}
""".strip(),
            encoding="utf-8",
        )
        store = RunStore(tmp_path / f"{tool_name}.sqlite")
        workflow = load_workflow(workflow_path)

        result = run_workflow(workflow, {"topic": "ABH"}, store=store)

        assert result.status == "failed"
        output = result.outputs["mcp_failure"]
        assert output["error"] == message
        assert output["mcp"]["status"] == status
        assert output["tool_invocation"]["error"] == message
        report = build_run_report(result.run_id, store=store)
        assert report["failure"] == {"node_id": "mcp_failure", "message": message}
        assert report["timeline"][0]["tool"]["mcp"]["status"] == status
        run = get_run(result.run_id, store=store)
        bundle = export_evidence_bundle(run, report, tmp_path / f"{tool_name}-bundles")
        with zipfile.ZipFile(bundle.path) as archive:
            events = json.loads(archive.read("events.json"))
            report_doc = json.loads(archive.read("report.json"))
        assert events[0]["output"]["mcp"]["status"] == status
        assert report_doc["timeline"][0]["tool"]["mcp"]["status"] == status
        assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_local_mcp_redaction_reaches_report_and_bundle(tmp_path):
    secret = "sk-mcp-secret"
    workflow_path = tmp_path / "mcp_redaction_workflow.yaml"
    workflow_path.write_text(
        """
id: mcp-redaction
entrypoint: mcp_fail
governance:
  sensitive_paths:
    - inputs.api_key
nodes:
  mcp_fail:
    type: tool
    tool:
      adapter: mcp
      runtime: local
      server: local-memory
      tool: fail
      timeout_seconds: 3
      args:
        message: "bad secret {api_key}"
validations:
  - type: run_status
    equals: failed
  - type: assertion
    source: report
    path: summary.redaction.redacted_nodes
    equals: 1
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"api_key": secret}, store=store)
    report = build_run_report(result.run_id, store=store)
    run = get_run(result.run_id, store=store)
    bundle = export_evidence_bundle(run, report, tmp_path / "bundles")

    assert result.status == "failed"
    assert secret not in json.dumps(result.outputs, ensure_ascii=False)
    assert report["summary"]["redaction"]["redacted_nodes"] == 1
    assert report["timeline"][0]["tool"]["input"]["args"]["message"] == "bad secret [REDACTED]"
    assert report["timeline"][0]["tool"]["mcp"]["error"]["message"] == (
        "mcp tool local-memory.fail failed: bad secret [REDACTED]"
    )
    assert secret not in json.dumps(report, ensure_ascii=False)
    with zipfile.ZipFile(bundle.path) as archive:
        for name in ["inputs.json", "events.json", "report.json"]:
            content = archive.read(name).decode("utf-8")
            assert secret not in content
            assert "[REDACTED]" in content


def test_local_mcp_tool_invocation_only_redaction_reaches_run_outputs_report_and_bundle(tmp_path):
    secret = "tool-only-secret"
    workflow_path = tmp_path / "mcp_tool_invocation_redaction_workflow.yaml"
    workflow_path.write_text(
        """
id: mcp-tool-invocation-redaction
entrypoint: mcp_fail
governance:
  sensitive_paths:
    - tool_invocation.mcp_fail.input.args.message
nodes:
  mcp_fail:
    type: tool
    tool:
      adapter: mcp
      runtime: local
      server: local-memory
      tool: fail
      timeout_seconds: 3
      args:
        message: "{message}"
validations:
  - type: run_status
    equals: failed
  - type: assertion
    source: report
    path: summary.redaction.redacted_nodes
    equals: 1
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"message": secret}, store=store)
    report = build_run_report(result.run_id, store=store)
    run = get_run(result.run_id, store=store)
    bundle = export_evidence_bundle(run, report, tmp_path / "bundles")

    assert result.status == "failed"
    assert secret not in json.dumps(result.outputs, ensure_ascii=False)
    assert report["outputs"]["mcp_fail"]["tool_invocation"]["input"]["args"]["message"] == "[REDACTED]"
    assert report["outputs"]["mcp_fail"]["error"] == "mcp tool local-memory.fail failed: [REDACTED]"
    assert report["outputs"]["mcp_fail"]["mcp"]["error"]["message"] == (
        "mcp tool local-memory.fail failed: [REDACTED]"
    )
    assert secret not in json.dumps(report, ensure_ascii=False)
    with zipfile.ZipFile(bundle.path) as archive:
        for name in ["events.json", "report.json"]:
            content = archive.read(name).decode("utf-8")
            assert secret not in content
            assert "[REDACTED]" in content
