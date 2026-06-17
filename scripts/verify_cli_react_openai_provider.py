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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-react-openai-") as temp:
        state_dir = Path(temp) / "state"
        bundle_dir = Path(temp) / "bundles"
        env = {**os.environ, "AI_INFRA_FAKE_OPENAI_API_KEY": "sk-fake-cli-secret"}
        missing_key_env = dict(env)
        missing_key_env.pop("AI_INFRA_MISSING_OPENAI_KEY", None)

        validate = _run_cli(env, state_dir, "validate", "examples/react_openai_compatible_workflow.yaml")
        _assert(validate["ok"] is True, "OpenAI-compatible workflow should validate")

        run = _run_cli(
            env,
            state_dir,
            "run",
            "examples/react_openai_compatible_workflow.yaml",
            "--input-file",
            "examples/react_openai_compatible_input.json",
        )["run"]
        run_id = str(run["run_id"])
        _assert(run["status"] == "completed", "fake provider workflow should complete")
        _assert(run["outputs"]["answer"]["answer"] == "[REDACTED]", "configured answer should be redacted")
        _assert(
            run["outputs"]["answer"]["react"]["provider"]["status"] == "completed",
            "provider evidence should show completion",
        )
        _assert(
            "sk-fake-cli-secret" not in json.dumps(run, ensure_ascii=False),
            "API key value must not leak in run output",
        )

        report = _run_cli(env, state_dir, "report", run_id)["report"]
        _assert(
            report["timeline"][0]["react"]["provider"]["request"]["endpoint"] == "/chat/completions",
            "report should expose provider request summary",
        )
        _assert(
            report["summary"]["redaction"]["redacted_nodes"] == 1,
            "report should summarize redaction",
        )
        _assert("customer-secret" not in json.dumps(report, ensure_ascii=False), "report should redact input secret")
        _assert("sk-fake-cli-secret" not in json.dumps(report, ensure_ascii=False), "report should not contain API key")

        verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
        _assert(verification["status"] == "passed", "fake provider verification should pass")

        bundle = _run_cli(env, state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))["bundle"]
        _assert_bundle_redacted(Path(str(bundle["path"])))

        missing = _run_cli(
            missing_key_env,
            state_dir,
            "run",
            "examples/react_openai_missing_key_workflow.yaml",
            "--input-file",
            "examples/react_openai_missing_key_input.json",
        )["run"]
        missing_run_id = str(missing["run_id"])
        _assert(missing["status"] == "failed", "missing API key workflow should fail")
        _assert(
            missing["outputs"]["answer"]["react"]["provider"]["status"] == "missing_api_key",
            "missing-key provider evidence should be explicit",
        )
        _assert(
            _run_cli(missing_key_env, state_dir, "verify", missing_run_id)["verification"]["status"] == "passed",
            "missing-key verification should pass expected failure checks",
        )

        budget = _run_cli(
            env,
            state_dir,
            "run",
            "examples/react_openai_budget_workflow.yaml",
            "--input-file",
            "examples/react_openai_budget_input.json",
        )["run"]
        budget_run_id = str(budget["run_id"])
        _assert(budget["status"] == "failed", "budget workflow should fail")
        _assert(
            budget["outputs"]["answer"]["react"]["provider"]["status"] == "token_budget_exhausted",
            "budget evidence should show token exhaustion",
        )
        _assert(
            _run_cli(env, state_dir, "verify", budget_run_id)["verification"]["status"] == "passed",
            "budget verification should pass expected failure checks",
        )

        timeout = _run_cli(
            env,
            state_dir,
            "run",
            "examples/react_openai_timeout_workflow.yaml",
            "--input-file",
            "examples/react_openai_timeout_input.json",
        )["run"]
        timeout_run_id = str(timeout["run_id"])
        _assert(timeout["status"] == "failed", "timeout workflow should fail")
        _assert(
            timeout["outputs"]["answer"]["react"]["provider"]["status"] == "timeout",
            "timeout evidence should be explicit",
        )
        _assert(
            _run_cli(env, state_dir, "verify", timeout_run_id)["verification"]["status"] == "passed",
            "timeout verification should pass expected failure checks",
        )

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "verify_status": verification["status"],
                "bundle": bundle["path"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


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
        raise AssertionError(
            f"command failed: {' '.join(args)}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    payload = json.loads(result.stdout)
    if payload.get("ok") is False:
        raise AssertionError(result.stdout)
    return payload


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_bundle_redacted(path: Path) -> None:
    _assert(path.exists(), "evidence bundle should exist")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        _assert(
            {"report.json", "inputs.json", "events.json", "workflow_snapshot.yaml", "manifest.json"}.issubset(names),
            "evidence bundle should include standard evidence files",
        )
        for name in ["inputs.json", "events.json", "report.json"]:
            content = archive.read(name).decode("utf-8")
            _assert("customer-secret" not in content, f"{name} should redact input secret")
            _assert("sk-fake-cli-secret" not in content, f"{name} should not include API key")
            _assert("[REDACTED]" in content, f"{name} should include redaction marker")


if __name__ == "__main__":
    raise SystemExit(main())
