from pathlib import Path

from ai_infra import load_workflow
from ai_infra.langgraph_runner import compile_workflow
from ai_infra.store import RunStore


def test_compile_workflow_returns_langgraph_runnable(tmp_path):
    workflow = load_workflow(Path("examples/hello_workflow.yaml"))
    store = RunStore(tmp_path / "runs.sqlite")

    graph = compile_workflow(workflow, store=store)
    result = graph.invoke({"inputs": {"topic": "ABH"}})

    assert result["status"] == "completed"
    assert result["outputs"]["draft"] == "Draft a short note about ABH."
    assert result["outputs"]["review"] == "Review result: Draft a short note about ABH."
    assert len(result["events"]) == 2


def test_compile_workflow_executes_fan_out_dag_edges(tmp_path):
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
    workflow = load_workflow(workflow_path)

    graph = compile_workflow(workflow)
    result = graph.invoke({"inputs": {"topic": "ABH"}})

    assert result["status"] == "completed"
    assert result["outputs"]["start"] == "Start ABH"
    assert result["outputs"]["left"] == "Left sees Start ABH"
    assert result["outputs"]["right"] == "Right sees Start ABH"
    assert {event.node_id for event in result["events"]} == {"start", "left", "right"}


def test_output_contract_evidence_does_not_change_scalar_context_values(tmp_path):
    workflow_path = tmp_path / "scalar_contract.yaml"
    workflow_path.write_text(
        """
id: scalar-contract
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
    contract:
      output:
        type: string
  review:
    type: template
    template: "Review {draft}"
edges:
  - from: draft
    to: review
""".strip(),
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_path)
    store = RunStore(tmp_path / "runs.sqlite")

    graph = compile_workflow(workflow, store=store)
    result = graph.invoke({"run_id": "run-scalar", "inputs": {"topic": "ABH"}})

    assert result["outputs"]["draft"] == "Draft ABH"
    assert result["outputs"]["review"] == "Review Draft ABH"
    draft_event = [event for event in result["events"] if event.node_id == "draft"][0]
    assert draft_event.output["result"] == "Draft ABH"
    assert draft_event.metadata["contract"]["output"]["status"] == "passed"
