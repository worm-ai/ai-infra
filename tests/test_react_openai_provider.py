from __future__ import annotations

import hashlib
import json
import re
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

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
from ai_infra.react import execute_react_node
from ai_infra.store import RunStore


def write_workflow(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "workflow.yaml"
    path.write_text(content.strip(), encoding="utf-8")
    return path


def test_validate_workflow_accepts_openai_compatible_provider_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: react-openai-contract
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
      base_url: memory://fake-openai
      api_key_env: AI_INFRA_FAKE_OPENAI_API_KEY
      timeout_ms: 1000
      prompt: "Answer {question}"
      max_steps: 1
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    config = workflow.node_map["answer"].config["config"]
    assert config["provider"] == "openai-compatible"
    assert config["base_url"] == "memory://fake-openai"
    assert config["api_key_env"] == "AI_INFRA_FAKE_OPENAI_API_KEY"
    assert config["timeout_ms"] == 1000


@pytest.mark.parametrize(
    ("config", "expected_error"),
    [
        (
            """
      timeout_ms: 0
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
""",
            "react node 'answer' timeout_ms must be a positive integer",
        ),
        (
            """
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
""",
            "react node 'answer' openai-compatible provider requires timeout_ms",
        ),
        (
            """
      timeout_ms: 1000
""",
            "react node 'answer' openai-compatible provider requires budget",
        ),
        (
            """
      base_url: file://provider
      timeout_ms: 1000
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
""",
            "react node 'answer' openai-compatible provider has unsupported base_url",
        ),
        (
            """
      timeout_ms: 1000
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
""",
            "react node 'answer' openai-compatible provider budget requires completion_cost_per_1k_tokens",
        ),
    ],
)
def test_validate_workflow_rejects_invalid_openai_compatible_provider_config(
    tmp_path,
    config,
    expected_error,
):
    base_url = "memory://fake-openai" if "base_url:" not in config else None
    base_url_line = f"      base_url: {base_url}\n" if base_url else ""
    path = write_workflow(
        tmp_path,
        f"""
id: bad-react-openai-contract
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
{base_url_line.rstrip()}
      api_key_env: AI_INFRA_FAKE_OPENAI_API_KEY
      prompt: "Answer {{question}}"
      max_steps: 1
{config}
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(expected_error)):
        validate_workflow(workflow)


def test_react_sdk_rejects_unknown_provider_without_openai_fallback():
    result = execute_react_node(
        {
            "provider": "custom-live-provider",
            "model": "fake-chat",
            "prompt": "Answer {question}",
            "max_steps": 1,
        },
        {"question": "ABH"},
    )

    assert result.status == "failed"
    assert result.output["error"] == "react provider 'custom-live-provider' is unsupported"
    assert "provider" not in result.output["react"]
    assert result.output["react"]["budget"]["status"] == "unsupported_provider"


def test_openai_compatible_fake_provider_persists_auditable_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INFRA_FAKE_OPENAI_API_KEY", "test-key")
    workflow_path = write_workflow(
        tmp_path,
        """
id: react-openai-runtime
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
      base_url: memory://fake-openai
      api_key_env: AI_INFRA_FAKE_OPENAI_API_KEY
      timeout_ms: 1000
      prompt: "Answer {question}"
      max_steps: 1
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: answer
  - type: assertion
    source: node_output
    node: answer
    path: react.provider.status
    equals: completed
  - type: assertion
    source: report
    path: timeline.0.react.provider.request.endpoint
    equals: /chat/completions
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"question": "ABH"}, store=store)

    assert result.status == "completed"
    output = result.outputs["answer"]
    assert output["answer"] == "Answer ABH"
    assert output["react"]["model"]["provider"] == "openai-compatible"
    assert output["react"]["model"]["base_url"] == "memory://fake-openai"
    assert output["react"]["model"]["api_key_env"] == "AI_INFRA_FAKE_OPENAI_API_KEY"
    assert "test-key" not in json.dumps(output, ensure_ascii=False)
    assert "prompt" not in output["react"]["model"]
    assert output["react"]["provider"]["status"] == "completed"
    assert output["react"]["provider"]["request"] == {
        "endpoint": "/chat/completions",
        "message_count": 1,
        "prompt_sha256": hashlib.sha256(b"Answer ABH").hexdigest(),
        "timeout_ms": 1000,
    }
    assert output["react"]["provider"]["response"]["finish_reason"] == "stop"
    assert output["react"]["provider"]["response"]["content_sha256"]
    assert output["react"]["provider"]["usage"]["total_tokens"] >= 1
    assert output["react"]["provider"]["usage"]["estimated_cost_usd"] > 0
    assert output["react"]["budget"]["status"] == "within_limits"
    assert output["react"]["steps"][0]["action"]["type"] == "provider_call"

    saved = get_run(result.run_id, store=store)
    [event] = saved.events
    assert event.output["react"]["provider"]["usage"]["total_tokens"] == output["react"]["provider"]["usage"]["total_tokens"]
    report = build_run_report(result.run_id, store=store)
    assert report["timeline"][0]["react"]["provider"]["status"] == "completed"
    assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_openai_compatible_missing_key_fails_with_redaction_safe_governance_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_INFRA_MISSING_OPENAI_KEY", raising=False)
    workflow_path = write_workflow(
        tmp_path,
        """
id: react-openai-missing-key
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
      base_url: memory://fake-openai
      api_key_env: AI_INFRA_MISSING_OPENAI_KEY
      timeout_ms: 1000
      prompt: "Answer {question}"
      max_steps: 1
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: answer
  - type: assertion
    source: node_output
    node: answer
    path: react.provider.status
    equals: missing_api_key
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"question": "ABH"}, store=store)

    assert result.status == "failed"
    output = result.outputs["answer"]
    assert output["error"] == "react openai-compatible provider missing required environment variable 'AI_INFRA_MISSING_OPENAI_KEY'"
    assert output["react"]["provider"]["status"] == "missing_api_key"
    assert output["react"]["provider"]["governance"] == {
        "api_key_env": "AI_INFRA_MISSING_OPENAI_KEY",
        "api_key_present": False,
        "timeout_ms": 1000,
    }
    assert validate_stored_run(result.run_id, store=store).status == "passed"


@pytest.mark.parametrize(
    ("budget", "expected_status", "expected_error"),
    [
        (
            """
        max_total_tokens: 1
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
""",
            "token_budget_exhausted",
            "react openai-compatible provider exceeded token budget",
        ),
        (
            """
        max_total_tokens: 100
        max_cost_usd: 0
        prompt_cost_per_1k_tokens: 1
        completion_cost_per_1k_tokens: 1
""",
            "cost_budget_exhausted",
            "react openai-compatible provider exceeded cost budget",
        ),
    ],
)
def test_openai_compatible_budget_failures_are_actionable_and_auditable(
    tmp_path,
    monkeypatch,
    budget,
    expected_status,
    expected_error,
):
    monkeypatch.setenv("AI_INFRA_FAKE_OPENAI_API_KEY", "test-key")
    workflow_path = write_workflow(
        tmp_path,
        f"""
id: react-openai-budget
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
      base_url: memory://fake-openai
      api_key_env: AI_INFRA_FAKE_OPENAI_API_KEY
      timeout_ms: 1000
      prompt: "Answer the production governance question: {{question}}"
      max_steps: 1
      budget:
{budget}
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: answer
  - type: assertion
    source: node_output
    node: answer
    path: react.provider.status
    equals: {expected_status}
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"question": "ABH"}, store=store)
    report = build_run_report(result.run_id, store=store)

    assert result.status == "failed"
    output = result.outputs["answer"]
    assert output["error"] == expected_error
    assert output["react"]["provider"]["status"] == expected_status
    assert output["react"]["budget"]["status"] == expected_status
    assert report["failure"] == {"node_id": "answer", "message": expected_error}
    assert validate_stored_run(result.run_id, store=store).status == "passed"


@pytest.mark.parametrize(
    ("base_url", "expected_status", "expected_error"),
    [
        ("memory://timeout", "timeout", "react openai-compatible provider timed out"),
        ("memory://provider-error", "provider_error", "react openai-compatible provider failed"),
    ],
)
def test_openai_compatible_timeout_and_provider_errors_are_auditable(
    tmp_path,
    monkeypatch,
    base_url,
    expected_status,
    expected_error,
):
    monkeypatch.setenv("AI_INFRA_FAKE_OPENAI_API_KEY", "test-key")
    workflow_path = write_workflow(
        tmp_path,
        f"""
id: react-openai-provider-failure
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
      base_url: {base_url}
      api_key_env: AI_INFRA_FAKE_OPENAI_API_KEY
      timeout_ms: 1000
      prompt: "Answer {{question}}"
      max_steps: 1
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: answer
  - type: assertion
    source: node_output
    node: answer
    path: react.provider.status
    equals: {expected_status}
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"question": "ABH"}, store=store)

    assert result.status == "failed"
    output = result.outputs["answer"]
    assert output["error"] == expected_error
    assert output["react"]["provider"]["status"] == expected_status
    assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_openai_compatible_http_response_usage_drives_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INFRA_FAKE_OPENAI_API_KEY", "test-key")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = {
                "choices": [{"message": {"content": "short"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            }
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    workflow_path = write_workflow(
        tmp_path,
        f"""
id: react-openai-http-usage
entrypoint: answer
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
      base_url: http://127.0.0.1:{server.server_port}
      api_key_env: AI_INFRA_FAKE_OPENAI_API_KEY
      timeout_ms: 1000
      prompt: "Answer {{question}}"
      max_steps: 1
      budget:
        max_total_tokens: 17
        max_cost_usd: 1
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
validations:
  - type: run_status
    equals: failed
  - type: assertion
    source: node_output
    node: answer
    path: react.provider.status
    equals: token_budget_exhausted
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    try:
        result = run_workflow(workflow, {"question": "ABH"}, store=store)
    finally:
        server.shutdown()
        server.server_close()

    assert result.status == "failed"
    usage = result.outputs["answer"]["react"]["provider"]["usage"]
    assert usage["prompt_tokens"] == 11
    assert usage["completion_tokens"] == 7
    assert usage["total_tokens"] == 18
    assert usage["source"] == "provider"
    assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_openai_compatible_http_provider_error_includes_redacted_failure_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INFRA_FAKE_OPENAI_API_KEY", "test-key")
    secret = "customer-secret"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = {
                "error": {
                    "message": f"bad auth test-key sk-should-not-leak and {secret}",
                    "type": "auth_error",
                }
            }
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    workflow_path = write_workflow(
        tmp_path,
        f"""
id: react-openai-http-error
entrypoint: answer
governance:
  sensitive_paths:
    - inputs.secret
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
      base_url: http://127.0.0.1:{server.server_port}
      api_key_env: AI_INFRA_FAKE_OPENAI_API_KEY
      timeout_ms: 1000
      prompt: "Answer {{question}}"
      max_steps: 1
      budget:
        max_total_tokens: 100
        max_cost_usd: 1
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
validations:
  - type: run_status
    equals: failed
  - type: assertion
    source: node_output
    node: answer
    path: react.provider.error.status_code
    equals: 401
""",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    try:
        result = run_workflow(workflow, {"question": "ABH", "secret": secret}, store=store)
    finally:
        server.shutdown()
        server.server_close()

    assert result.status == "failed"
    provider_error = result.outputs["answer"]["react"]["provider"]["error"]
    assert provider_error["status_code"] == 401
    assert provider_error["error_type"] == "auth_error"
    assert provider_error["retryable"] is False
    encoded_output = json.dumps(result.outputs["answer"], ensure_ascii=False)
    assert "test-key" not in encoded_output
    assert "sk-should-not-leak" not in encoded_output
    assert secret not in encoded_output
    report = build_run_report(result.run_id, store=store)
    run = get_run(result.run_id, store=store)
    bundle = export_evidence_bundle(run, report, tmp_path / "bundles")
    assert secret not in json.dumps(report, ensure_ascii=False)
    with zipfile.ZipFile(bundle.path) as archive:
        for name in ["events.json", "report.json"]:
            assert secret not in archive.read(name).decode("utf-8")
    assert validate_stored_run(result.run_id, store=store).status == "passed"


def test_openai_compatible_redaction_reaches_report_and_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_INFRA_FAKE_OPENAI_API_KEY", "sk-test-secret")
    secret = "customer-secret"
    workflow_path = write_workflow(
        tmp_path,
        """
id: react-openai-redaction
entrypoint: answer
governance:
  sensitive_paths:
    - inputs.secret
    - node_output.answer.answer
nodes:
  answer:
    type: react
    config:
      provider: openai-compatible
      model: fake-chat
      base_url: memory://fake-openai
      api_key_env: AI_INFRA_FAKE_OPENAI_API_KEY
      timeout_ms: 1000
      prompt: "Echo {secret}"
      max_steps: 1
      budget:
        max_total_tokens: 100
        max_cost_usd: 0.01
        prompt_cost_per_1k_tokens: 0.001
        completion_cost_per_1k_tokens: 0.002
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

    result = run_workflow(workflow, {"secret": secret}, store=store)
    report = build_run_report(result.run_id, store=store)
    run = get_run(result.run_id, store=store)
    bundle = export_evidence_bundle(run, report, tmp_path / "bundles")

    assert result.status == "completed"
    assert result.outputs["answer"]["answer"] == "[REDACTED]"
    encoded_report = json.dumps(report, ensure_ascii=False)
    assert secret not in encoded_report
    assert "sk-test-secret" not in encoded_report
    assert "Echo {secret}" not in report["provenance"]["workflow_snapshot"]
    assert report["provenance"]["workflow_snapshot_present"] is True
    assert report["provenance"]["workflow_sha256"]
    assert report["timeline"][0]["react"]["provider"]["request"]["prompt_sha256"]
    assert "prompt" not in report["timeline"][0]["react"]["provider"]["request"]

    with zipfile.ZipFile(bundle.path) as archive:
        for name in ["inputs.json", "events.json", "report.json"]:
            content = archive.read(name).decode("utf-8")
            assert secret not in content
            assert "sk-test-secret" not in content
            assert "[REDACTED]" in content
        snapshot = archive.read("workflow_snapshot.yaml").decode("utf-8")
        assert "Echo {secret}" not in snapshot
