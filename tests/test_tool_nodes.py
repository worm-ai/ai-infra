from pathlib import Path

from ai_infra import get_run, load_workflow, run_workflow, validate_stored_run
from ai_infra.store import RunStore


def test_tool_nodes_execute_and_persist_audit_evidence(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/tool_workflow.yaml"))

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "completed"
    assert result.outputs["python_echo"]["result"] == "ABH"
    assert result.outputs["shell_echo"]["stdout"].strip() == "ABH"
    assert result.outputs["http_echo"]["status_code"] == 200

    saved = get_run(result.run_id, store=store)
    tool_events = {event.node_id: event for event in saved.events}
    assert tool_events["python_echo"].status == "completed"
    assert tool_events["shell_echo"].output["exit_code"] == 0
    assert tool_events["http_echo"].output["body"]["topic"] == "ABH"
    assert tool_events["http_echo"].output["duration_ms"] >= 0

    verification = validate_stored_run(result.run_id, store=store)
    assert verification.status == "passed"


def test_tool_node_expected_failure_is_auditable(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/tool_failure_workflow.yaml"))

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "failed"
    assert result.outputs["failing_shell"]["exit_code"] == 7

    saved = get_run(result.run_id, store=store)
    event = saved.events[-1]
    assert event.node_id == "failing_shell"
    assert event.status == "failed"
    assert "exit code 7" in event.output["error"]

    verification = validate_stored_run(result.run_id, store=store)
    assert verification.status == "passed"
