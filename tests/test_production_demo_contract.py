import importlib.util
from pathlib import Path


def _load_demo_module():
    path = Path("scripts/verify_cli_production_demo.py")
    spec = importlib.util.spec_from_file_location("verify_cli_production_demo", path)
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
