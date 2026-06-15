from pathlib import Path

from ai_infra import build_run_report, load_workflow, run_workflow
from ai_infra.store import RunStore


def test_build_run_report_summarizes_successful_tool_run(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/tool_workflow.yaml"))
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["run_id"] == result.run_id
    assert report["workflow_id"] == "tool-workflow"
    assert report["status"] == "completed"
    assert report["inputs"] == {"topic": "ABH"}
    assert report["input_summary"] == {"type": "object", "keys": ["topic"]}
    assert report["outputs"]["python_echo"]["result"] == "ABH"
    assert report["output_summary"] == {
        "type": "object",
        "keys": ["http_echo", "python_echo", "shell_echo"],
    }
    assert report["failure"] is None
    assert [node["node_id"] for node in report["timeline"]] == [
        "python_echo",
        "shell_echo",
        "http_echo",
    ]
    assert report["summary"] == {"completed": 3, "failed": 0, "total_nodes": 3}
    assert report["timeline"][0]["tool"]["adapter"] == "python"
    assert report["timeline"][1]["tool"]["exit_code"] == 0
    assert report["timeline"][2]["tool"]["status_code"] == 200


def test_build_run_report_identifies_failed_tool_evidence(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/tool_failure_workflow.yaml"))
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    report = build_run_report(result.run_id, store=store)

    assert report["status"] == "failed"
    assert report["summary"] == {"completed": 0, "failed": 1, "total_nodes": 1}
    assert report["failure"] == {
        "node_id": "failing_shell",
        "message": "shell tool exited with exit code 7",
    }
    [node] = report["timeline"]
    assert node["node_id"] == "failing_shell"
    assert node["status"] == "failed"
    assert node["duration_ms"] >= 0
    assert node["tool"]["adapter"] == "shell"
    assert node["tool"]["exit_code"] == 7
    assert node["tool"]["stdout"].strip() == "expected failure"
    assert node["tool"]["stderr"] == ""
    assert "exit code 7" in node["tool"]["error"]
