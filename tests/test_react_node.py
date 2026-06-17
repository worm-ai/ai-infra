import hashlib
import json
import re
import zipfile
from pathlib import Path

import pytest

import ai_infra
from ai_infra import (
    build_run_report,
    export_evidence_bundle,
    get_run,
    load_workflow,
    run_workflow,
    validate_stored_run,
    validate_workflow,
)
from ai_infra.config import WorkflowValidationError
from ai_infra.store import RunStore


def write_workflow(tmp_path, content: str) -> Path:
    path = tmp_path / "workflow.yaml"
    path.write_text(content.strip(), encoding="utf-8")
    return path


def test_validate_workflow_accepts_react_atomic_node_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: react-contract
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: mock
      model: mock-react
      prompt: "Answer {question}"
      max_steps: 2
      budget:
        max_tool_calls: 1
      tools:
        - adapter: python
          name: echo
          args:
            value: "{question}"
validations:
  - type: run_status
    equals: completed
  - type: assertion
    source: node_output
    node: answer
    path: react.steps.0.action.type
    equals: tool
  - type: assertion
    source: tool_invocation
    node: answer
    path: input.args.value
    equals: ABH
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.node_map["answer"].config["config"]["provider"] == "mock"
    assert workflow.node_map["answer"].config["config"]["tools"][0]["adapter"] == "python"


@pytest.mark.parametrize(
    ("react_config", "message"),
    [
        (
            """
model: mock-react
prompt: "Answer {question}"
max_steps: 2
""",
            "react node 'answer' requires provider",
        ),
        (
            """
provider: anthropic
model: mock-react
prompt: "Answer {question}"
max_steps: 2
""",
            "react node 'answer' provider must be one of",
        ),
        (
            """
provider: mock
prompt: "Answer {question}"
max_steps: 2
""",
            "react node 'answer' requires model",
        ),
        (
            """
provider: mock
model: mock-react
prompt: "   "
max_steps: 2
""",
            "react node 'answer' requires prompt",
        ),
        (
            """
provider: mock
model: mock-react
prompt: "Answer {question}"
max_steps: 0
""",
            "react node 'answer' max_steps must be an integer between 1 and 10",
        ),
        (
            """
provider: mock
model: mock-react
prompt: "Answer {question}"
max_steps: 2
planner: dynamic
""",
            "react node 'answer' config has unsupported field 'planner'",
        ),
        (
            """
provider: mock
model: mock-react
prompt: "Answer {question}"
max_steps: 2
budget:
  max_tool_calls: 3
""",
            "react node 'answer' budget max_tool_calls must be a positive integer not greater than max_steps",
        ),
        (
            """
provider: mock
model: mock-react
prompt: "Answer {question}"
max_steps: 2
tools:
  - adapter: python
    args:
      value: "{question}"
""",
            "python react node 'answer' tool[0] requires name",
        ),
    ],
)
def test_validate_workflow_rejects_invalid_react_config(tmp_path, react_config, message):
    path = write_workflow(
        tmp_path,
        f"""
id: bad-react
entrypoint: answer
nodes:
  answer:
    type: react
    config:
{_indent(react_config, spaces=6)}
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        validate_workflow(workflow)


def test_validate_workflow_rejects_react_node_without_config(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: bad-react
entrypoint: answer
nodes:
  answer:
    type: react
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape("react node 'answer' requires config")):
        validate_workflow(workflow)


def test_react_node_executes_as_bounded_dag_atomic_node_with_persisted_evidence(tmp_path):
    workflow_path = write_workflow(
        tmp_path,
        """
id: react-runtime
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: mock
      model: mock-react
      prompt: "Use declared tools to answer {question}"
      max_steps: 2
      budget:
        max_tool_calls: 1
      tools:
        - adapter: python
          name: echo
          args:
            value: "{question}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: answer
  - type: assertion
    source: node_output
    node: answer
    path: answer
    equals: ABH
  - type: assertion
    source: node_output
    node: answer
    path: react.steps.0.action.type
    equals: tool
  - type: assertion
    source: node_output
    node: answer
    path: react.steps.1.action.type
    equals: final_answer
  - type: assertion
    source: tool_invocation
    node: answer
    path: status
    equals: completed
  - type: assertion
    source: report
    path: timeline.0.react.model.provider
    equals: mock
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"question": "ABH"}, store=store)

    assert result.status == "completed"
    output = result.outputs["answer"]
    assert output["answer"] == "ABH"
    assert output["react"]["status"] == "completed"
    assert output["react"]["model"]["provider"] == "mock"
    assert output["react"]["model"]["model"] == "mock-react"
    assert "prompt" not in output["react"]["model"]
    assert output["react"]["budget"] == {
        "max_steps": 2,
        "steps_used": 2,
        "max_tool_calls": 1,
        "tool_calls_used": 1,
        "status": "within_limits",
    }
    assert [step["action"]["type"] for step in output["react"]["steps"]] == ["tool", "final_answer"]
    assert output["react"]["steps"][0]["thought_summary"]
    assert "thought" not in output["react"]["steps"][0]
    assert output["tool_invocation"]["input"]["args"]["value"] == "ABH"

    saved = get_run(result.run_id, store=store)
    [event] = saved.events
    assert event.node_id == "answer"
    assert event.status == "completed"
    assert event.output["react"]["steps"][0]["tool_invocation"]["identity"] == "echo"

    verification = validate_stored_run(result.run_id, store=store)
    assert verification.status == "passed"


def test_react_node_can_call_local_mcp_tool_as_atomic_node_tool(tmp_path):
    workflow_path = write_workflow(
        tmp_path,
        """
id: react-mcp-runtime
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: mock
      model: mock-react
      prompt: "Use declared MCP tool for {question}"
      max_steps: 2
      budget:
        max_tool_calls: 1
      tools:
        - adapter: mcp
          runtime: local
          server: local-memory
          tool: echo
          timeout_seconds: 3
          args:
            question: "{question}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: answer
  - type: assertion
    source: tool_invocation
    node: answer
    path: adapter
    equals: mcp
  - type: assertion
    source: node_output
    node: answer
    path: react.steps.0.tool_invocation.output.mcp.status
    equals: completed
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"question": "ABH"}, store=store)

    assert result.status == "completed"
    output = result.outputs["answer"]
    assert output["answer"] == {"question": "ABH"}
    assert output["tool_invocation"]["adapter"] == "mcp"
    assert output["tool_invocation"]["reserved"] is False
    assert output["react"]["steps"][0]["action"] == {
        "type": "tool",
        "adapter": "mcp",
        "identity": "local-memory.echo",
    }
    assert output["react"]["steps"][0]["tool_invocation"]["output"]["mcp"]["status"] == "completed"
    assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_react_node_max_steps_failure_is_actionable_and_auditable(tmp_path):
    workflow_path = write_workflow(
        tmp_path,
        """
id: react-max-steps
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: mock
      model: mock-react
      prompt: "Use declared tools to answer {question}"
      max_steps: 1
      budget:
        max_tool_calls: 1
      tools:
        - adapter: python
          name: echo
          args:
            value: "{question}"
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: answer
  - type: assertion
    source: node_output
    node: answer
    path: react.budget.status
    equals: max_steps_exhausted
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"question": "ABH"}, store=store)
    report = build_run_report(result.run_id, store=store)

    assert result.status == "failed"
    output = result.outputs["answer"]
    assert output["error"] == "react node exceeded max_steps before final answer"
    assert output["react"]["budget"]["status"] == "max_steps_exhausted"
    assert output["react"]["steps"][0]["action"]["type"] == "tool"
    assert report["failure"] == {
        "node_id": "answer",
        "message": "react node exceeded max_steps before final answer",
    }
    assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_react_report_redacts_nested_tool_evidence_and_exports_bundle(tmp_path):
    secret = "sk-react-secret"
    workflow_path = write_workflow(
        tmp_path,
        """
id: react-redaction
entrypoint: answer
governance:
  sensitive_paths:
    - inputs.api_key
    - node_output.answer.answer
    - tool_invocation.answer.input.args.value
    - node_output.answer.react.steps.0.tool_invocation.input.args.value
nodes:
  answer:
    type: react
    config:
      provider: mock
      model: mock-react
      prompt: "Use declared tools safely"
      max_steps: 2
      budget:
        max_tool_calls: 1
      tools:
        - adapter: python
          name: echo
          args:
            value: "{api_key}"
validations:
  - type: run_status
    equals: completed
  - type: assertion
    source: node_output
    node: answer
    path: answer
    equals: "[REDACTED]"
  - type: assertion
    source: report
    path: summary.redaction.redacted_nodes
    equals: 1
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"api_key": secret}, store=store)
    report = build_run_report(result.run_id, store=store)
    run = get_run(result.run_id, store=store)
    bundle = export_evidence_bundle(run, report, tmp_path / "bundles")

    assert result.outputs["answer"]["answer"] == "[REDACTED]"
    assert report["summary"]["react"] == {
        "nodes": 1,
        "completed": 1,
        "failed": 0,
        "steps": 2,
        "tool_calls": 1,
    }
    assert report["timeline"][0]["react"]["steps"][0]["tool_invocation"]["input"]["args"]["value"] == "[REDACTED]"
    assert secret not in json.dumps(report, ensure_ascii=False)

    with zipfile.ZipFile(bundle.path) as archive:
        for name in ["inputs.json", "events.json", "report.json"]:
            content = archive.read(name).decode("utf-8")
            assert secret not in content
            assert "[REDACTED]" in content


def test_react_sdk_boundary_objects_are_serializable_without_prompt_leakage():
    model = ai_infra.ReActModelConfig(
        provider="mock",
        model="mock-react",
        prompt="Answer {secret}",
        max_steps=2,
    )
    summary = model.to_summary()

    assert summary == {
        "provider": "mock",
        "model": "mock-react",
        "base_url": None,
        "api_key_env": None,
        "prompt_sha256": hashlib.sha256(b"Answer {secret}").hexdigest(),
        "max_steps": 2,
        "timeout_ms": None,
    }
    assert "secret" not in json.dumps(summary)

    step = ai_infra.ReActStepEvidence(
        index=1,
        thought_summary="selected declared tool",
        action={"type": "tool", "identity": "echo"},
        observation={"status": "completed"},
    )

    assert step.to_dict() == {
        "index": 1,
        "thought_summary": "selected declared tool",
        "action": {"type": "tool", "identity": "echo"},
        "observation": {"status": "completed"},
    }


def _indent(value: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" if line else line for line in value.strip().splitlines())
