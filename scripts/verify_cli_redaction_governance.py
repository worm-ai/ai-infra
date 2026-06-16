from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


SECRET = "DEMO_INPUT_SECRET"
ENV_SECRET = "DEMO_ENV_SECRET"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-redaction-") as temp:
        state_dir = Path(temp) / "state"
        bundle_dir = Path(temp) / "bundles"
        env = dict(os.environ)
        env["AI_INFRA_TEST_TOKEN"] = ENV_SECRET

        validate = _run_cli(env, state_dir, "validate", "examples/redaction_workflow.yaml")
        _assert(validate["ok"] is True, "redaction workflow should validate")

        run = _run_cli(
            env,
            state_dir,
            "run",
            "examples/redaction_workflow.yaml",
            "--input-file",
            "examples/redaction_input.json",
        )["run"]
        run_id = run["run_id"]
        _assert(run["status"] == "completed", "redaction workflow should complete")
        _assert(run["outputs"]["secret_echo"]["result"] == "[REDACTED]", "run output should be redacted")

        logs_payload = _run_cli(env, state_dir, "logs", run_id)
        report = _run_cli(env, state_dir, "report", run_id)["report"]
        verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
        bundle = _run_cli(env, state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))["bundle"]

        _assert(verification["status"] == "passed", "redaction verification should pass")
        _assert(report["summary"]["redaction"]["redacted_nodes"] == 1, "report should summarize redaction")
        _assert_no_secret(logs_payload, "logs should not contain secret values")
        _assert_no_secret(report, "report should not contain secret values")
        _assert_bundle_is_redacted(Path(bundle["path"]))

        missing_env = dict(os.environ)
        missing_env.pop("AI_INFRA_TEST_TOKEN", None)
        missing_run = _run_cli(
            missing_env,
            state_dir,
            "run",
            "examples/missing_env_workflow.yaml",
            "--input-file",
            "examples/redaction_input.json",
        )["run"]
        _assert(missing_run["status"] == "failed", "missing env workflow should fail fast")
        missing_report = _run_cli(missing_env, state_dir, "report", missing_run["run_id"])["report"]
        _assert(
            missing_report["provenance"]["environment"]["governance"]["missing_required_env"]
            == ["AI_INFRA_TEST_TOKEN"],
            "missing env report should identify variable name only",
        )
        _assert_no_secret(missing_report, "missing env report should not contain secret values")

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "verify_status": verification["status"],
                "bundle": bundle["path"],
                "missing_env_run_id": missing_run["run_id"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _run_cli(env: dict[str, str], state_dir: Path, *args: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if result.returncode not in (0,):
        raise AssertionError(
            f"command failed: {' '.join(args)}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return json.loads(result.stdout)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_no_secret(payload: Any, message: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    _assert(SECRET not in serialized, message)
    _assert(ENV_SECRET not in serialized, message)


def _assert_bundle_is_redacted(path: Path) -> None:
    _assert(path.exists(), "evidence bundle should exist")
    with zipfile.ZipFile(path) as archive:
        for name in ["inputs.json", "events.json", "report.json", "manifest.json"]:
            content = archive.read(name).decode("utf-8")
            _assert(SECRET not in content, f"{name} should not contain input secret")
            _assert(ENV_SECRET not in content, f"{name} should not contain environment secret")
        _assert("[REDACTED]" in archive.read("report.json").decode("utf-8"), "report should contain marker")


if __name__ == "__main__":
    raise SystemExit(main())
