import importlib.util
import subprocess
from pathlib import Path


def _load_demo_module():
    path = Path("scripts/verify_cli_production_demo.py")
    spec = importlib.util.spec_from_file_location("verify_cli_production_demo", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_bundle_integrity_module():
    path = Path("scripts/verify_cli_bundle_integrity.py")
    spec = importlib.util.spec_from_file_location("verify_cli_bundle_integrity", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_env_does_not_inherit_ambient_secret_values(monkeypatch):
    module = _load_demo_module()
    monkeypatch.setenv("UNRELATED_SECRET_TOKEN", "ambient-secret-value")

    env = module._demo_env()

    assert env["AI_INFRA_TEST_TOKEN"] == module.ENV_SECRET
    assert env["AI_INFRA_FAKE_OPENAI_API_KEY"] == "sk-production-demo-fake"
    assert "UNRELATED_SECRET_TOKEN" not in env


def test_sanitized_failure_message_redacts_demo_and_ambient_secrets():
    module = _load_demo_module()
    env = module._demo_env()
    env["UNRELATED_SECRET_TOKEN"] = "ambient-secret-value"

    message = module._failure_message(
        ("run", "workflow.yaml"),
        "stdout production-demo-secret ambient-secret-value sk-production-demo-fake",
        "stderr production-demo-env-secret",
        env,
    )

    assert "production-demo-secret" not in message
    assert "production-demo-env-secret" not in message
    assert "sk-production-demo-fake" not in message
    assert "ambient-secret-value" not in message
    assert "[REDACTED]" in message


def test_bundle_integrity_cli_runner_retries_transient_empty_stdout(monkeypatch, tmp_path):
    module = _load_bundle_integrity_module()
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, -1073740940, "", "transient process crash")
        return subprocess.CompletedProcess(command, 0, '{"ok": true}\n', "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._run_cli({}, tmp_path / "state", "validate", "workflow.yaml")

    assert result.returncode == 0
    assert result.stdout == '{"ok": true}\n'
    assert len(calls) == 2


def test_bundle_integrity_json_error_includes_subprocess_evidence():
    module = _load_bundle_integrity_module()
    result = subprocess.CompletedProcess(
        ["ai-infra", "verify-bundle"],
        -1073740940,
        "",
        "transient process crash",
    )

    try:
        module._json_payload(result, "verify-bundle")
    except AssertionError as exc:
        message = str(exc)
    else:
        raise AssertionError("_json_payload should reject empty stdout")

    assert "code=-1073740940" in message
    assert "stderr='transient process crash'" in message
