from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEMO_SECRET = "production-demo-secret"
ENV_SECRET = "production-demo-env-secret"
FAKE_PROVIDER_KEY = "sk-production-demo-fake"
SENSITIVE_ENV_MARKERS = ("SECRET", "TOKEN", "KEY", "PASSWORD", "CREDENTIAL", "AUTH")
ENV_PASSTHROUGH_KEYS = (
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "PYTHONPATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-production-demo-") as temp:
        state_dir = Path(temp) / "state"
        bundle_dir = Path(temp) / "bundles"
        env = _demo_env()

        hello = _run_success_path(env, state_dir, bundle_dir)
        failure = _run_expected_failure(env, state_dir)
        governance = _run_governance(env, state_dir)
        redaction = _run_redaction(env, state_dir, bundle_dir)
        react = _run_react(env, state_dir)
        provider = _run_provider(env, state_dir)
        mcp = _run_mcp(env, state_dir, bundle_dir)

        payload = {
            "ok": True,
            "runs": {
                "hello": hello,
                "failure": failure,
                "governance": governance,
                "redaction": redaction,
                "react": react,
                "provider": provider,
                "mcp": mcp,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0


def _run_success_path(env: dict[str, str], state_dir: Path, bundle_dir: Path) -> dict[str, Any]:
    validate = _run_cli(env, state_dir, "validate", "examples/hello_workflow.yaml")
    _assert(validate["ok"] is True, "hello workflow should validate")

    run = _run_cli(
        env,
        state_dir,
        "run",
        "examples/hello_workflow.yaml",
        "--input-file",
        "examples/hello_input.json",
    )["run"]
    run_id = str(run["run_id"])
    _assert(run["status"] == "completed", "hello workflow should complete")

    status = _run_cli(env, state_dir, "status", run_id)["run"]
    _assert(status["status"] == "completed", "status command should show completion")

    logs = _run_cli(env, state_dir, "logs", run_id)["events"]
    _assert([event["node_id"] for event in logs] == ["draft", "review"], "logs should expose ordered node events")

    report = _run_cli(env, state_dir, "report", run_id)["report"]
    _assert(report["status"] == "completed", "report should show completion")
    _assert(report["summary"]["total_nodes"] == 2, "report should summarize DAG nodes")
    _assert(report["provenance"]["workflow_sha256"], "report should include workflow provenance")

    verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
    _assert(verification["status"] == "passed", "verify should pass for hello workflow")

    bundle = _run_cli(env, state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))["bundle"]
    _assert_standard_bundle(Path(str(bundle["path"])))

    return {"run_id": run_id, "verify_status": verification["status"], "bundle": bundle["path"]}


def _run_expected_failure(env: dict[str, str], state_dir: Path) -> dict[str, Any]:
    run = _run_cli(
        env,
        state_dir,
        "run",
        "examples/tool_failure_workflow.yaml",
        "--input-file",
        "examples/tool_input.json",
    )["run"]
    run_id = str(run["run_id"])
    _assert(run["status"] == "failed", "failure workflow should fail audibly")
    report = _run_cli(env, state_dir, "report", run_id)["report"]
    _assert(report["failure"]["node_id"] == "failing_shell", "report should localize failed node")
    verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
    _assert(verification["status"] == "passed", "declared failure verification should pass")
    return {"run_id": run_id, "failure_node": report["failure"]["node_id"]}


def _run_governance(env: dict[str, str], state_dir: Path) -> dict[str, Any]:
    run = _run_cli(
        env,
        state_dir,
        "run",
        "examples/governance_workflow.yaml",
        "--input-file",
        "examples/governance_input.json",
    )["run"]
    run_id = str(run["run_id"])
    _assert(run["status"] == "failed", "governance workflow should fail on budget exhaustion")
    report = _run_cli(env, state_dir, "report", run_id)["report"]
    _assert(report["summary"]["governance"]["budget_exhausted"] == 1, "report should expose governance evidence")
    verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
    _assert(verification["status"] == "passed", "governance verification should pass")
    return {"run_id": run_id, "governance": report["summary"]["governance"]}


def _run_redaction(env: dict[str, str], state_dir: Path, bundle_dir: Path) -> dict[str, Any]:
    input_path = state_dir.parent / "redaction_input.json"
    input_path.write_text(json.dumps({"api_key": DEMO_SECRET}), encoding="utf-8")
    run = _run_cli(
        env,
        state_dir,
        "run",
        "examples/redaction_workflow.yaml",
        "--input-file",
        str(input_path),
    )["run"]
    run_id = str(run["run_id"])
    _assert(run["status"] == "completed", "redaction workflow should complete")
    _assert_no_secret(run, "redacted run output should not leak secrets")

    report = _run_cli(env, state_dir, "report", run_id)["report"]
    _assert(report["summary"]["redaction"]["redacted_nodes"] == 1, "report should summarize redaction")
    _assert_no_secret(report, "redacted report should not leak secrets")

    verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
    _assert(verification["status"] == "passed", "redaction verification should pass")

    bundle = _run_cli(env, state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))["bundle"]
    _assert_bundle_redacted(Path(str(bundle["path"])))
    return {"run_id": run_id, "verify_status": verification["status"], "bundle": bundle["path"]}


def _run_react(env: dict[str, str], state_dir: Path) -> dict[str, Any]:
    run = _run_cli(env, state_dir, "run", "examples/react_workflow.yaml", "--input-file", "examples/react_input.json")[
        "run"
    ]
    run_id = str(run["run_id"])
    _assert(run["status"] == "completed", "mock ReAct workflow should complete")
    output = run["outputs"]["answer"]
    _assert(output["react"]["budget"]["status"] == "within_limits", "ReAct budget should stay bounded")
    _assert(output["tool_invocation"]["status"] == "completed", "ReAct tool invocation should be auditable")
    verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
    _assert(verification["status"] == "passed", "ReAct verification should pass")
    return {"run_id": run_id, "steps": len(output["react"]["steps"])}


def _run_provider(env: dict[str, str], state_dir: Path) -> dict[str, Any]:
    run = _run_cli(
        env,
        state_dir,
        "run",
        "examples/react_openai_compatible_workflow.yaml",
        "--input-file",
        "examples/react_openai_compatible_input.json",
    )["run"]
    run_id = str(run["run_id"])
    _assert(run["status"] == "completed", "fake OpenAI-compatible provider workflow should complete")
    provider = run["outputs"]["answer"]["react"]["provider"]
    _assert(provider["status"] == "completed", "provider evidence should show completion")
    _assert_no_secret(run, "provider run output should not leak secrets")
    verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
    _assert(verification["status"] == "passed", "provider verification should pass")
    return {"run_id": run_id, "provider_status": provider["status"]}


def _run_mcp(env: dict[str, str], state_dir: Path, bundle_dir: Path) -> dict[str, Any]:
    run = _run_cli(
        env,
        state_dir,
        "run",
        "examples/mcp_runtime_workflow.yaml",
        "--input-file",
        "examples/mcp_runtime_input.json",
    )["run"]
    run_id = str(run["run_id"])
    _assert(run["status"] == "completed", "MCP runtime workflow should complete")
    mcp = run["outputs"]["mcp_echo"]["mcp"]
    _assert(mcp["status"] == "completed", "MCP runtime evidence should show completion")
    report = _run_cli(env, state_dir, "report", run_id)["report"]
    _assert(report["timeline"][0]["tool"]["mcp"]["status"] == "completed", "report should expose MCP evidence")
    verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
    _assert(verification["status"] == "passed", "MCP verification should pass")
    bundle = _run_cli(env, state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))["bundle"]
    _assert_standard_bundle(Path(str(bundle["path"])))
    return {"run_id": run_id, "mcp_status": mcp["status"], "bundle": bundle["path"]}


def _run_cli(env: dict[str, str], state_dir: Path, *args: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(_failure_message(args, result.stdout, result.stderr, env))
    payload = json.loads(result.stdout)
    if payload.get("ok") is False:
        raise AssertionError(_sanitize_text(result.stdout, env))
    return payload


def _demo_env() -> dict[str, str]:
    env = {
        key: value
        for key in ENV_PASSTHROUGH_KEYS
        if (value := os.environ.get(key))
    }
    env["AI_INFRA_TEST_TOKEN"] = ENV_SECRET
    env["AI_INFRA_FAKE_OPENAI_API_KEY"] = FAKE_PROVIDER_KEY
    return env


def _failure_message(args: tuple[str, ...], stdout: str, stderr: str, env: dict[str, str]) -> str:
    message = f"command failed: {' '.join(args)}\nstdout={stdout}\nstderr={stderr}"
    return _sanitize_text(message, env)


def _sanitize_text(text: str, env: dict[str, str]) -> str:
    sanitized = text
    for value in _secret_values(env):
        sanitized = sanitized.replace(value, "[REDACTED]")
    return sanitized


def _secret_values(env: dict[str, str]) -> set[str]:
    values = {DEMO_SECRET, ENV_SECRET, FAKE_PROVIDER_KEY}
    for key, value in env.items():
        upper_key = key.upper()
        if value and any(marker in upper_key for marker in SENSITIVE_ENV_MARKERS):
            values.add(value)
    return values


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_no_secret(payload: Any, message: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    _assert(DEMO_SECRET not in serialized, message)
    _assert(ENV_SECRET not in serialized, message)
    _assert(FAKE_PROVIDER_KEY not in serialized, message)


def _assert_standard_bundle(path: Path) -> None:
    _assert(path.exists(), "evidence bundle should exist")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    _assert(
        {"report.json", "inputs.json", "events.json", "workflow_snapshot.yaml", "manifest.json"}.issubset(names),
        "evidence bundle should include standard files",
    )


def _assert_bundle_redacted(path: Path) -> None:
    _assert_standard_bundle(path)
    with zipfile.ZipFile(path) as archive:
        for name in ["inputs.json", "events.json", "report.json", "manifest.json"]:
            content = archive.read(name).decode("utf-8")
            _assert(DEMO_SECRET not in content, f"{name} should not contain input secret")
            _assert(ENV_SECRET not in content, f"{name} should not contain env secret")
        _assert("[REDACTED]" in archive.read("report.json").decode("utf-8"), "report should contain redaction marker")


if __name__ == "__main__":
    raise SystemExit(main())
