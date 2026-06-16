from pathlib import Path

from ai_infra import (
    ToolInvocation,
    ToolInvocationEvidence,
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
