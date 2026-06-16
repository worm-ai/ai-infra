from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-tool-boundary-") as temp:
        state_dir = Path(temp) / "state"

        tool_validate = _run("validate", "examples/tool_workflow.yaml", state_dir=state_dir)
        _assert_ok(tool_validate, "tool validate")

        tool_run = _run(
            "run",
            "examples/tool_workflow.yaml",
            "--input-file",
            "examples/tool_input.json",
            state_dir=state_dir,
        )
        tool_payload = _assert_ok(tool_run, "tool run")
        tool_run_id = tool_payload["run"]["run_id"]
        if tool_payload["run"]["status"] != "completed":
            raise AssertionError(f"tool workflow did not complete: {tool_payload!r}")

        tool_report = _run("report", tool_run_id, state_dir=state_dir)
        report_payload = _assert_ok(tool_report, "tool report")
        tool_nodes = report_payload["report"]["timeline"]
        python_tool = tool_nodes[0]["tool"]
        if python_tool["adapter"] != "python" or python_tool["identity"] != "echo":
            raise AssertionError(f"python tool invocation was not normalized: {python_tool!r}")
        if python_tool["input"] != {"args": {"value": "ABH"}, "name": "echo"}:
            raise AssertionError(f"python tool input was not normalized: {python_tool!r}")
        if python_tool["reserved"] is not False:
            raise AssertionError(f"python tool was marked reserved: {python_tool!r}")
        if tool_nodes[1]["tool"]["adapter"] != "shell" or tool_nodes[1]["tool"]["exit_code"] != 0:
            raise AssertionError(f"shell tool compatibility evidence missing: {tool_nodes[1]!r}")
        if tool_nodes[2]["tool"]["adapter"] != "http" or tool_nodes[2]["tool"]["status_code"] != 200:
            raise AssertionError(f"http tool compatibility evidence missing: {tool_nodes[2]!r}")

        mcp_validate = _run("validate", "examples/mcp_reserved_workflow.yaml", state_dir=state_dir)
        _assert_ok(mcp_validate, "mcp validate")

        mcp_run = _run(
            "run",
            "examples/mcp_reserved_workflow.yaml",
            "--input-file",
            "examples/mcp_reserved_input.json",
            state_dir=state_dir,
        )
        mcp_payload = _assert_ok(mcp_run, "mcp run")
        mcp_run_id = mcp_payload["run"]["run_id"]
        if mcp_payload["run"]["status"] != "failed":
            raise AssertionError(f"mcp reserved run should fail audibly: {mcp_payload!r}")

        mcp_logs = _run("logs", mcp_run_id, state_dir=state_dir)
        logs_payload = _assert_ok(mcp_logs, "mcp logs")
        [event] = logs_payload["events"]
        invocation = event["output"]["tool_invocation"]
        if invocation != {
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
            "duration_ms": invocation["duration_ms"],
            "reserved": True,
        }:
            raise AssertionError(f"unexpected mcp invocation evidence: {invocation!r}")

        mcp_report = _run("report", mcp_run_id, state_dir=state_dir)
        mcp_report_payload = _assert_ok(mcp_report, "mcp report")
        [mcp_node] = mcp_report_payload["report"]["timeline"]
        if mcp_node["tool"]["reserved"] is not True:
            raise AssertionError(f"mcp report did not expose reserved boundary: {mcp_node!r}")

        mcp_verify = _run("verify", mcp_run_id, state_dir=state_dir)
        verify_payload = _assert_ok(mcp_verify, "mcp verify")
        if verify_payload["verification"]["status"] != "passed":
            raise AssertionError(f"mcp verification did not pass declared failure checks: {verify_payload!r}")

        print(
            json.dumps(
                {
                    "ok": True,
                    "tool_run_id": tool_run_id,
                    "mcp_run_id": mcp_run_id,
                    "mcp_reserved": True,
                },
                ensure_ascii=False,
            )
        )
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
