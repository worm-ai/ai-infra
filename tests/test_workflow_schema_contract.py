from pathlib import Path
import re

import pytest

from ai_infra import load_workflow, validate_workflow
from ai_infra.config import WorkflowValidationError


def write_workflow(tmp_path, content: str) -> Path:
    path = tmp_path / "workflow.yaml"
    path.write_text(content.strip(), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            """
- not
- a
- mapping
""",
            "workflow YAML root must be a mapping",
        ),
        (
            """
id: bad
entrypoint: only
owner: unexpected
nodes:
  only:
    type: template
    template: Hello
""",
            "unsupported top-level field 'owner'",
        ),
        (
            """
id: bad
entrypoint: only
nodes:
  only: template
""",
            "node 'only' must be a mapping",
        ),
        (
            """
id: bad
entrypoint: only
nodes:
  only:
    type: template
    template: Hello
    retries: 3
""",
            "node 'only' has unsupported field 'retries'",
        ),
        (
            """
id: bad
entrypoint: only
nodes:
  only:
    type: template
    template: Hello
edges:
  - only
""",
            "edge[0] must be a mapping",
        ),
        (
            """
id: bad
entrypoint: only
nodes:
  only:
    type: template
    template: Hello
validations:
  - run_status
""",
            "validation[0] must be a mapping",
        ),
    ],
)
def test_load_workflow_rejects_invalid_yaml_contract(tmp_path, content, message):
    path = write_workflow(tmp_path, content)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        load_workflow(path)


@pytest.mark.parametrize(
    ("tool", "message"),
    [
        (
            """
adapter: python
args:
  value: "{topic}"
""",
            "python tool node 'tool_node' requires name",
        ),
        (
            """
adapter: shell
command: "   "
""",
            "shell tool node 'tool_node' requires non-empty command",
        ),
        (
            """
adapter: http
method: POST
url: "ftp://example.test"
""",
            "http tool node 'tool_node' has unsupported url",
        ),
        (
            """
adapter: mcp
name: future
""",
            "tool node 'tool_node' has unsupported adapter 'mcp'",
        ),
    ],
)
def test_validate_workflow_rejects_adapter_specific_tool_contract(tmp_path, tool, message):
    path = write_workflow(
        tmp_path,
        f"""
id: bad-tool
entrypoint: tool_node
nodes:
  tool_node:
    type: tool
    tool:
{_indent(tool, spaces=6)}
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        validate_workflow(workflow)


@pytest.mark.parametrize(
    ("validations", "message"),
    [
        (
            """
- type: run_status
""",
            "validation[0] run_status requires equals",
        ),
        (
            """
- type: node_completed
  node: missing
""",
            "validation[0] references missing node 'missing'",
        ),
        (
            """
- type: node_failed
  node: only
  extra: nope
""",
            "validation[0] has unsupported field 'extra'",
        ),
    ],
)
def test_validate_workflow_rejects_invalid_validation_contract(tmp_path, validations, message):
    path = write_workflow(
        tmp_path,
        f"""
id: bad-validation
entrypoint: only
nodes:
  only:
    type: template
    template: Hello
validations:
{_indent(validations, spaces=2)}
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        validate_workflow(workflow)


def test_validate_workflow_rejects_duplicate_edges(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: duplicate-edge
entrypoint: first
nodes:
  first:
    type: template
    template: First
  second:
    type: template
    template: Second
edges:
  - from: first
    to: second
  - from: first
    to: second
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape("duplicate edge 'first' -> 'second'")):
        validate_workflow(workflow)


def _indent(value: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" if line else line for line in value.strip().splitlines())
