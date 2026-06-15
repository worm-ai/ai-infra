from pathlib import Path

import pytest

from ai_infra import load_workflow, validate_workflow
from ai_infra.config import WorkflowValidationError


def test_loads_example_workflow_from_yaml():
    workflow = load_workflow(Path("examples/hello_workflow.yaml"))

    assert workflow.id == "hello-workflow"
    assert workflow.entrypoint == "draft"
    assert [node.id for node in workflow.nodes] == ["draft", "review"]
    assert workflow.nodes[0].type == "template"


def test_validate_rejects_missing_entrypoint(tmp_path):
    workflow_path = tmp_path / "bad.yaml"
    workflow_path.write_text(
        """
id: bad
nodes:
  only:
    type: template
    template: "Hello"
""".strip(),
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_path)

    with pytest.raises(WorkflowValidationError, match="entrypoint"):
        validate_workflow(workflow)


def test_validate_rejects_cycle_in_dag_edges(tmp_path):
    workflow_path = tmp_path / "cycle.yaml"
    workflow_path.write_text(
        """
id: cycle
entrypoint: first
nodes:
  first:
    type: template
    template: "first"
  second:
    type: template
    template: "second"
edges:
  - from: first
    to: second
  - from: second
    to: first
""".strip(),
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_path)

    with pytest.raises(WorkflowValidationError, match="cycle"):
        validate_workflow(workflow)
