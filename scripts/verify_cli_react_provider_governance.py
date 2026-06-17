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
    with tempfile.TemporaryDirectory(prefix="ai-infra-react-provider-governance-") as temp:
        state_dir = Path(temp) / "state"
        bundle_dir = Path(temp) / "bundles"
        env = {**os.environ, "AI_INFRA_FAKE_OPENAI_API_KEY": "sk-provider-governance-secret"}

        for workflow_path in (
            "examples/react_openai_compatible_workflow.yaml",
            "examples/react_openai_dry_run_workflow.yaml",
            "examples/react_openai_live_disabled_workflow.yaml",
        ):
            validate = _run_cli(env, state_dir, "validate", workflow_path)
            _assert(validate["ok"] is True, f"{workflow_path} should validate")

        fake = _run_cli(
            env,
            state_dir,
            "run",
            "examples/react_openai_compatible_workflow.yaml",
            "--input-file",
            "examples/react_openai_compatible_input.json",
        )["run"]
        fake_run_id = str(fake["run_id"])
        _assert(fake["status"] == "completed", "fake provider workflow should complete")
        _assert(
            fake["outputs"]["answer"]["react"]["provider"]["governance"]["runtime"]["mode"] == "fake",
            "fake provider runtime mode should be explicit",
        )

        dry_run = _run_cli(
            env,
            state_dir,
            "run",
            "examples/react_openai_dry_run_workflow.yaml",
            "--input-file",
            "examples/react_openai_provider_governance_input.json",
        )["run"]
        dry_run_id = str(dry_run["run_id"])
        _assert(dry_run["status"] == "completed", "dry-run provider workflow should complete")
        _assert(dry_run["outputs"]["answer"]["answer"] == "[DRY_RUN]", "dry-run answer should be explicit")
        _assert(
            dry_run["outputs"]["answer"]["react"]["provider"]["governance"]["runtime"]
            == {
                "mode": "dry_run",
                "allow_live_http": False,
                "decision": "dry_run",
                "reason": "local provider governance rehearsal",
                "network_attempted": False,
            },
            "dry-run provider governance evidence should be deterministic",
        )

        disabled = _run_cli(
            env,
            state_dir,
            "run",
            "examples/react_openai_live_disabled_workflow.yaml",
            "--input-file",
            "examples/react_openai_provider_governance_input.json",
        )["run"]
        disabled_run_id = str(disabled["run_id"])
        _assert(disabled["status"] == "failed", "disabled live provider workflow should fail")
        _assert(
            disabled["outputs"]["answer"]["react"]["provider"]["status"] == "live_http_disabled",
            "disabled live provider status should be explicit",
        )
        _assert(
            disabled["outputs"]["answer"]["react"]["provider"]["governance"]["runtime"]["network_attempted"]
            is False,
            "disabled live provider must fail before network access",
        )

        for run_id, expected_mode in (
            (fake_run_id, "fake"),
            (dry_run_id, "dry_run"),
            (disabled_run_id, "live"),
        ):
            report = _run_cli(env, state_dir, "report", run_id)["report"]
            runtime = report["timeline"][0]["react"]["provider"]["governance"]["runtime"]
            _assert(runtime["mode"] == expected_mode, f"{run_id} report should include runtime mode")
            _assert(
                "sk-provider-governance-secret" not in json.dumps(report, ensure_ascii=False),
                f"{run_id} report should not leak API key values",
            )
            verification = _run_cli(env, state_dir, "verify", run_id)["verification"]
            _assert(verification["status"] == "passed", f"{run_id} verification should pass")

        bundle = _run_cli(env, state_dir, "export-bundle", dry_run_id, "--output-dir", str(bundle_dir))["bundle"]
        _assert_bundle_has_runtime_evidence(Path(str(bundle["path"])))

    print(
        json.dumps(
            {
                "ok": True,
                "fake_run_id": fake_run_id,
                "dry_run_id": dry_run_id,
                "disabled_run_id": disabled_run_id,
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


def _assert_bundle_has_runtime_evidence(path: Path) -> None:
    _assert(path.exists(), "evidence bundle should exist")
    with zipfile.ZipFile(path) as archive:
        for name in ["events.json", "report.json"]:
            content = archive.read(name).decode("utf-8")
            _assert('"mode": "dry_run"' in content, f"{name} should include dry-run runtime mode")
            _assert('"network_attempted": false' in content, f"{name} should include network attempt evidence")
            _assert("sk-provider-governance-secret" not in content, f"{name} should not leak API key values")


if __name__ == "__main__":
    raise SystemExit(main())
