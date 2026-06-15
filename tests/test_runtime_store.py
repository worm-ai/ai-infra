from pathlib import Path

from ai_infra import get_run, load_workflow, run_workflow, validate_run
from ai_infra.store import RunStore


def test_run_workflow_persists_completed_run_and_node_events(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/hello_workflow.yaml"))

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "completed"
    assert result.outputs["draft"] == "Draft a short note about ABH."
    assert result.outputs["review"] == "Review result: Draft a short note about ABH."

    saved = get_run(result.run_id, store=store)
    assert saved.run_id == result.run_id
    assert saved.status == "completed"
    assert [event.node_id for event in saved.events] == ["draft", "review"]


def test_validate_run_records_validation_results(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/hello_workflow.yaml"))
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    verification = validate_run(result.run_id, workflow, store=store)

    assert verification.status == "passed"
    assert [check.status for check in verification.checks] == ["passed", "passed", "passed"]
    saved = get_run(result.run_id, store=store)
    assert saved.verifications[-1].status == "passed"


def test_run_workflow_persists_all_fan_out_dag_node_events(tmp_path):
    workflow_path = tmp_path / "fan_out.yaml"
    workflow_path.write_text(
        """
id: fan-out
name: Fan Out
version: "0.1"
entrypoint: start
nodes:
  start:
    type: template
    template: "Start {topic}"
  left:
    type: template
    template: "Left sees {start}"
  right:
    type: template
    template: "Right sees {start}"
edges:
  - from: start
    to: left
  - from: start
    to: right
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "completed"
    assert result.outputs["left"] == "Left sees Start ABH"
    assert result.outputs["right"] == "Right sees Start ABH"
    saved = get_run(result.run_id, store=store)
    assert {event.node_id for event in saved.events} == {"start", "left", "right"}
