from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-mcp-runtime-") as temp:
        state_dir = Path(temp) / "state"
        bundle_dir = Path(temp) / "bundles"

        validate = _run("validate", "examples/mcp_runtime_workflow.yaml", state_dir=state_dir)
        _assert_ok(validate, "mcp runtime validate")

        run = _run(
            "run",
            "examples/mcp_runtime_workflow.yaml",
            "--input-file",
            "examples/mcp_runtime_input.json",
            state_dir=state_dir,
        )
        run_payload = _assert_ok(run, "mcp runtime run")
        run_id = run_payload["run"]["run_id"]
        if run_payload["run"]["status"] != "completed":
            raise AssertionError(f"mcp runtime workflow did not complete: {run_payload!r}")
        output = run_payload["run"]["outputs"]["mcp_echo"]
        if output["tool_invocation"]["reserved"] is not False:
            raise AssertionError(f"mcp runtime should not be marked reserved: {output!r}")
        if output["mcp"]["status"] != "completed":
            raise AssertionError(f"mcp runtime evidence missing completion: {output!r}")

        report = _run("report", run_id, state_dir=state_dir)
        report_payload = _assert_ok(report, "mcp runtime report")
        [node] = report_payload["report"]["timeline"]
        if node["tool"]["mcp"]["status"] != "completed":
            raise AssertionError(f"mcp report did not expose runtime evidence: {node!r}")

        verify = _run("verify", run_id, state_dir=state_dir)
        verify_payload = _assert_ok(verify, "mcp runtime verify")
        if verify_payload["verification"]["status"] != "passed":
            raise AssertionError(f"mcp runtime verification failed: {verify_payload!r}")

        bundle = _run("export-bundle", run_id, "--output-dir", str(bundle_dir), state_dir=state_dir)
        bundle_payload = _assert_ok(bundle, "mcp runtime export bundle")
        bundle_path = Path(bundle_payload["bundle"]["path"])
        with zipfile.ZipFile(bundle_path) as archive:
            events = json.loads(archive.read("events.json"))
            report_doc = json.loads(archive.read("report.json"))
        if events[0]["output"]["tool_invocation"]["adapter"] != "mcp":
            raise AssertionError(f"bundle events missing mcp invocation: {events!r}")
        if report_doc["timeline"][0]["tool"]["mcp"]["status"] != "completed":
            raise AssertionError(f"bundle report missing mcp evidence: {report_doc!r}")

        missing_config_path = Path(temp) / "mcp_missing_tool.yaml"
        missing_config_path.write_text(
            """
id: mcp-missing-tool
entrypoint: mcp_bad
nodes:
  mcp_bad:
    type: tool
    tool:
      adapter: mcp
      runtime: local
      server: local-memory
""".strip(),
            encoding="utf-8",
        )
        missing = _run("validate", str(missing_config_path), state_dir=state_dir)
        missing_payload = json.loads(missing.stdout)
        if missing.returncode == 0 or missing_payload.get("ok"):
            raise AssertionError(f"missing mcp config should fail validation: {missing_payload!r}")
        if "requires tool" not in missing_payload.get("error", ""):
            raise AssertionError(f"missing mcp config error is not actionable: {missing_payload!r}")

        timeout_path = Path(temp) / "mcp_timeout.yaml"
        timeout_path.write_text(
            """
id: mcp-timeout
entrypoint: mcp_timeout
nodes:
  mcp_timeout:
    type: tool
    tool:
      adapter: mcp
      runtime: local
      server: local-memory
      tool: timeout
      timeout_seconds: 1
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: mcp_timeout
  - type: assertion
    source: node_output
    node: mcp_timeout
    path: mcp.status
    equals: timeout
""".strip(),
            encoding="utf-8",
        )
        timeout_input = Path(temp) / "input.json"
        timeout_input.write_text("{}", encoding="utf-8")
        timeout_run = _run("run", str(timeout_path), "--input-file", str(timeout_input), state_dir=state_dir)
        timeout_payload = _assert_ok(timeout_run, "mcp timeout run")
        timeout_run_id = timeout_payload["run"]["run_id"]
        if timeout_payload["run"]["status"] != "failed":
            raise AssertionError(f"mcp timeout should fail audibly: {timeout_payload!r}")
        timeout_verify = _run("verify", timeout_run_id, state_dir=state_dir)
        _assert_ok(timeout_verify, "mcp timeout verify")

        redaction_path = Path(temp) / "mcp_redaction.yaml"
        redaction_input = Path(temp) / "mcp_redaction_input.json"
        redaction_path.write_text(
            """
id: mcp-redaction-cli
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
        message: "secret {api_key}"
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
        redaction_input.write_text(json.dumps({"api_key": "sk-mcp-cli-secret"}), encoding="utf-8")
        redaction_run = _run("run", str(redaction_path), "--input-file", str(redaction_input), state_dir=state_dir)
        redaction_payload = _assert_ok(redaction_run, "mcp redaction run")
        redaction_run_id = redaction_payload["run"]["run_id"]
        redaction_bundle = _run(
            "export-bundle",
            redaction_run_id,
            "--output-dir",
            str(bundle_dir),
            state_dir=state_dir,
        )
        redaction_bundle_payload = _assert_ok(redaction_bundle, "mcp redaction bundle")
        with zipfile.ZipFile(redaction_bundle_payload["bundle"]["path"]) as archive:
            for name in ["inputs.json", "events.json", "report.json"]:
                content = archive.read(name).decode("utf-8")
                if "sk-mcp-cli-secret" in content:
                    raise AssertionError(f"secret leaked in {name}: {content}")
                if "[REDACTED]" not in content:
                    raise AssertionError(f"redaction marker missing from {name}: {content}")

        print(json.dumps({"ok": True, "mcp_run_id": run_id}, ensure_ascii=False))
        return 0


def _run(*args: str, state_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_ok(result: subprocess.CompletedProcess[str], label: str) -> dict:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{label} did not return JSON: {result.stdout!r}") from exc
    if result.returncode != 0 or not payload.get("ok"):
        raise AssertionError(
            f"{label} failed with code {result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
