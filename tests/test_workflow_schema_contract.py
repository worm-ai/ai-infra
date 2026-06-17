from pathlib import Path
import re

import pytest

from ai_infra import load_workflow, validate_workflow
from ai_infra.config import WorkflowValidationError


def write_workflow(tmp_path, content: str) -> Path:
    path = tmp_path / "workflow.yaml"
    path.write_text(content.strip(), encoding="utf-8")
    return path


def test_workflow_compatibility_contract_reports_supported_schema_and_features(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: compatibility-supported
schema_version: "1"
features:
  - template_nodes
  - edge_list
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
""",
    )

    workflow = load_workflow(path)
    compatibility = validate_workflow(workflow)

    assert compatibility == {
        "schema_version": {
            "declared": "1",
            "supported": ["1"],
            "status": "supported",
        },
        "features": [
            {"name": "template_nodes", "status": "supported"},
            {"name": "edge_list", "status": "supported"},
        ],
        "status": "supported",
        "failure_category": None,
        "diagnostics": [],
    }
    assert workflow.schema_version == "1"
    assert workflow.features == ["template_nodes", "edge_list"]


def test_workflow_compatibility_contract_defaults_legacy_workflows_to_schema_one(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: compatibility-legacy
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
""",
    )

    workflow = load_workflow(path)
    compatibility = validate_workflow(workflow)

    assert compatibility["schema_version"] == {
        "declared": "1",
        "supported": ["1"],
        "status": "supported",
    }
    assert compatibility["status"] == "supported"


def test_workflow_compatibility_contract_warns_on_deprecated_feature(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: compatibility-deprecated
schema_version: "1"
features:
  - legacy_llm_node
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
""",
    )

    workflow = load_workflow(path)
    compatibility = validate_workflow(workflow)

    assert compatibility["status"] == "deprecated"
    assert compatibility["features"] == [
        {
            "name": "legacy_llm_node",
            "status": "deprecated",
            "replacement": "react_nodes",
        }
    ]
    assert compatibility["diagnostics"] == [
        {
            "category": "deprecated_feature",
            "severity": "warning",
            "message": "feature 'legacy_llm_node' is deprecated; use 'react_nodes'",
        }
    ]


def test_workflow_compatibility_contract_rejects_unsupported_feature(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: compatibility-unsupported
schema_version: "1"
features:
  - distributed_a2a
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
""",
    )

    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError) as error:
        validate_workflow(workflow)

    assert error.value.compatibility["status"] == "unsupported"
    assert error.value.compatibility["failure_category"] == "unsupported_feature"
    assert "feature 'distributed_a2a' is unsupported by this local DAG runtime" in str(error.value)


def test_workflow_compatibility_contract_rejects_future_schema_version(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: compatibility-future
schema_version: "99"
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
""",
    )

    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError) as error:
        validate_workflow(workflow)

    assert error.value.compatibility["status"] == "future"
    assert error.value.compatibility["failure_category"] == "future_schema"
    assert "workflow schema_version '99' is newer than supported schema versions: 1" in str(error.value)


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


def test_load_workflow_accepts_node_failure_policy_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: retry-contract
entrypoint: flaky
nodes:
  flaky:
    type: tool
    policy:
      on_failure: halt
      max_attempts: 2
    tool:
      adapter: shell
      command: "python -c 'print(1)'"
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.node_map["flaky"].config["policy"] == {
        "on_failure": "halt",
        "max_attempts": 2,
    }


def test_load_workflow_accepts_node_output_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: output-contract
entrypoint: python_echo
nodes:
  python_echo:
    type: tool
    contract:
      output:
        type: object
        required_fields:
          result: string
          adapter: string
    tool:
      adapter: python
      name: echo
      args:
        value: "{topic}"
validations:
  - type: node_contract
    node: python_echo
    equals: passed
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.node_map["python_echo"].config["contract"] == {
        "output": {
            "type": "object",
            "required_fields": {
                "result": "string",
                "adapter": "string",
            },
        }
    }


def test_load_workflow_accepts_node_resume_action_validation(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: resume-validation-contract
entrypoint: only
nodes:
  only:
    type: template
    template: Hello
validations:
  - type: node_resume_action
    node: only
    equals: skipped
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.validations[0].type == "node_resume_action"
    assert workflow.validations[0].config == {"node": "only", "equals": "skipped"}


def test_load_workflow_accepts_node_artifact_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: artifact-contract
entrypoint: writer
nodes:
  writer:
    type: tool
    artifacts:
      - name: note
        path: "{artifact_path}"
        content_type: text/plain
    tool:
      adapter: shell
      command: "python -c 'print(1)'"
validations:
  - type: node_artifact
    node: writer
    name: note
    exists: true
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.node_map["writer"].config["artifacts"] == [
        {
            "name": "note",
            "path": "{artifact_path}",
            "content_type": "text/plain",
        }
    ]
    assert workflow.validations[0].type == "node_artifact"
    assert workflow.validations[0].config == {"node": "writer", "name": "note", "exists": True}


def test_load_workflow_accepts_governance_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: governance-contract
entrypoint: guarded
governance:
  max_node_executions: 3
  default_node_timeout_ms: 1000
nodes:
  guarded:
    type: template
    governance:
      timeout_ms: 500
    template: "Govern {topic}"
validations:
  - type: node_governance
    node: guarded
    equals: within_limits
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.governance == {
        "max_node_executions": 3,
        "default_node_timeout_ms": 1000,
    }
    assert workflow.node_map["guarded"].config["governance"] == {"timeout_ms": 500}
    assert workflow.validations[0].type == "node_governance"
    assert workflow.validations[0].config == {"node": "guarded", "equals": "within_limits"}


def test_load_workflow_accepts_input_secret_environment_governance_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: secret-governance-contract
entrypoint: secret_echo
governance:
  required_env:
    - AI_INFRA_TEST_TOKEN
  sensitive_paths:
    - inputs.api_key
    - node_output.secret_echo.result
    - tool_invocation.secret_echo.input.args.value
nodes:
  secret_echo:
    type: tool
    tool:
      adapter: python
      name: echo
      args:
        value: "{api_key}"
validations:
  - type: run_status
    equals: completed
  - type: assertion
    source: node_output
    node: secret_echo
    path: result
    equals: "[REDACTED]"
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.governance["required_env"] == ["AI_INFRA_TEST_TOKEN"]
    assert workflow.governance["sensitive_paths"] == [
        "inputs.api_key",
        "node_output.secret_echo.result",
        "tool_invocation.secret_echo.input.args.value",
    ]


def test_load_workflow_accepts_reserved_mcp_tool_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: mcp-reserved-contract
entrypoint: future_mcp_tool
nodes:
  future_mcp_tool:
    type: tool
    tool:
      adapter: mcp
      server: local-memory
      tool: echo
      args:
        topic: "{topic}"
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: future_mcp_tool
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.node_map["future_mcp_tool"].config["tool"] == {
        "adapter": "mcp",
        "server": "local-memory",
        "tool": "echo",
        "args": {"topic": "{topic}"},
    }


def test_load_workflow_accepts_local_mcp_runtime_tool_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: mcp-runtime-contract
entrypoint: mcp_tool
nodes:
  mcp_tool:
    type: tool
    tool:
      adapter: mcp
      runtime: local
      server: local-memory
      tool: echo
      timeout_seconds: 3
      args:
        topic: "{topic}"
validations:
  - type: run_status
    equals: completed
  - type: assertion
    source: node_output
    node: mcp_tool
    path: mcp.status
    equals: completed
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.node_map["mcp_tool"].config["tool"] == {
        "adapter": "mcp",
        "runtime": "local",
        "server": "local-memory",
        "tool": "echo",
        "timeout_seconds": 3,
        "args": {"topic": "{topic}"},
    }


def test_load_workflow_accepts_validation_assertion_contract(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: assertion-contract
entrypoint: python_echo
nodes:
  python_echo:
    type: tool
    tool:
      adapter: python
      name: echo
      args:
        value: "{topic}"
validations:
  - type: assertion
    source: node_output
    node: python_echo
    path: result
    equals: ABH
  - type: assertion
    source: tool_invocation
    node: python_echo
    path: reserved
    equals: false
  - type: assertion
    source: run
    path: status
    equals: completed
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.validations[0].type == "assertion"
    assert workflow.validations[0].config == {
        "source": "node_output",
        "node": "python_echo",
        "path": "result",
        "equals": "ABH",
    }


def test_load_workflow_accepts_aborted_governance_validation(tmp_path):
    path = write_workflow(
        tmp_path,
        """
id: governance-aborted-contract
entrypoint: first
governance:
  max_node_executions: 1
nodes:
  first:
    type: template
    next: second
    template: "First"
  second:
    type: template
    template: "Second"
validations:
  - type: node_governance
    node: second
    equals: aborted
""",
    )

    workflow = load_workflow(path)
    validate_workflow(workflow)

    assert workflow.validations[0].config == {"node": "second", "equals": "aborted"}


@pytest.mark.parametrize(
    ("governance", "message"),
    [
        (
            """
- max_node_executions: 1
""",
            "workflow governance must be a mapping",
        ),
        (
            """
max_node_executions: 0
""",
            "workflow governance max_node_executions must be a positive integer",
        ),
        (
            """
default_node_timeout_ms: soon
""",
            "workflow governance default_node_timeout_ms must be a positive integer",
        ),
        (
            """
max_node_executions: 2
remote_cancel: true
""",
            "workflow governance has unsupported field 'remote_cancel'",
        ),
        (
            """
required_env: AI_INFRA_TEST_TOKEN
""",
            "workflow governance required_env must be a list",
        ),
        (
            """
required_env:
  - ""
""",
            "workflow governance required_env[0] must be a non-empty string",
        ),
        (
            """
sensitive_paths: inputs.api_key
""",
            "workflow governance sensitive_paths must be a list",
        ),
        (
            """
sensitive_paths:
  - secrets.api_key
""",
            "workflow governance sensitive_paths[0] has unsupported root 'secrets'",
        ),
        (
            """
sensitive_paths:
  - inputs
""",
            "workflow governance sensitive_paths[0] must include a root and path",
        ),
    ],
)
def test_validate_workflow_rejects_invalid_workflow_governance(tmp_path, governance, message):
    path = write_workflow(
        tmp_path,
        f"""
id: bad-workflow-governance
entrypoint: only
governance:
{_indent(governance, spaces=2)}
nodes:
  only:
    type: template
    template: "Hello"
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        validate_workflow(workflow)


@pytest.mark.parametrize(
    ("governance", "message"),
    [
        (
            """
timeout_ms: 0
""",
            "node 'guarded' governance timeout_ms must be a positive integer",
        ),
        (
            """
timeout_ms: 100
cancel_service: external
""",
            "node 'guarded' governance has unsupported field 'cancel_service'",
        ),
    ],
)
def test_validate_workflow_rejects_invalid_node_governance(tmp_path, governance, message):
    path = write_workflow(
        tmp_path,
        f"""
id: bad-node-governance
entrypoint: guarded
nodes:
  guarded:
    type: template
    governance:
{_indent(governance, spaces=6)}
    template: "Hello"
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        validate_workflow(workflow)


@pytest.mark.parametrize(
    ("artifacts", "message"),
    [
        (
            """
name: note
path: "{artifact_path}"
content_type: text/plain
""",
            "node 'writer' artifacts must be a list",
        ),
        (
            """
- path: "{artifact_path}"
  content_type: text/plain
""",
            "node 'writer' artifact[0] requires name",
        ),
        (
            """
- name: note
  content_type: text/plain
""",
            "node 'writer' artifact[0] requires path",
        ),
        (
            """
- name: note
  path: "{artifact_path}"
""",
            "node 'writer' artifact[0] requires content_type",
        ),
        (
            """
- name: note
  path: "{artifact_path}"
  content_type: text/plain
  remote_store: s3
""",
            "node 'writer' artifact[0] has unsupported field 'remote_store'",
        ),
    ],
)
def test_validate_workflow_rejects_invalid_artifact_contract(tmp_path, artifacts, message):
    path = write_workflow(
        tmp_path,
        f"""
id: bad-artifact-contract
entrypoint: writer
nodes:
  writer:
    type: tool
    artifacts:
{_indent(artifacts, spaces=6)}
    tool:
      adapter: shell
      command: "python -c 'print(1)'"
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        validate_workflow(workflow)


@pytest.mark.parametrize(
    ("contract", "message"),
    [
        (
            """
output:
  type: tuple
""",
            "node 'python_echo' output contract type must be one of",
        ),
        (
            """
input:
  type: object
""",
            "node 'python_echo' contract has unsupported field 'input'",
        ),
        (
            """
output:
  type: string
  required_fields:
    result: string
""",
            "node 'python_echo' output contract required_fields requires type object",
        ),
        (
            """
output:
  type: object
  required_fields:
    result: datetime
""",
            "node 'python_echo' output contract field 'result' has unsupported type 'datetime'",
        ),
    ],
)
def test_validate_workflow_rejects_invalid_output_contract(tmp_path, contract, message):
    path = write_workflow(
        tmp_path,
        f"""
id: bad-output-contract
entrypoint: python_echo
nodes:
  python_echo:
    type: tool
    contract:
{_indent(contract, spaces=6)}
    tool:
      adapter: python
      name: echo
      args:
        value: "{{topic}}"
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        validate_workflow(workflow)


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        (
            """
on_failure: skip
max_attempts: 2
""",
            "node 'flaky' policy on_failure must be one of",
        ),
        (
            """
on_failure: halt
max_attempts: 0
""",
            "node 'flaky' policy max_attempts must be an integer between 1 and 10",
        ),
        (
            """
on_failure: continue
max_attempts: 11
""",
            "node 'flaky' policy max_attempts must be an integer between 1 and 10",
        ),
    ],
)
def test_validate_workflow_rejects_invalid_failure_policy_contract(tmp_path, policy, message):
    path = write_workflow(
        tmp_path,
        f"""
id: bad-policy
entrypoint: flaky
nodes:
  flaky:
    type: tool
    policy:
{_indent(policy, spaces=6)}
    tool:
      adapter: shell
      command: "python -c 'print(1)'"
""",
    )
    workflow = load_workflow(path)

    with pytest.raises(WorkflowValidationError, match=re.escape(message)):
        validate_workflow(workflow)


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
server: local-memory
""",
            "mcp tool node 'tool_node' requires tool",
        ),
        (
            """
adapter: mcp
server: local-memory
tool: echo
transport: stdio
""",
            "mcp tool node 'tool_node' has unsupported field 'transport'",
        ),
        (
            """
adapter: mcp
runtime: stdio
server: local-memory
tool: echo
""",
            "mcp tool node 'tool_node' runtime must be 'local'",
        ),
        (
            """
adapter: mcp
runtime: local
server: local-memory
tool: echo
timeout_seconds: 0
""",
            "mcp tool node 'tool_node' timeout_seconds must be a positive integer",
        ),
        (
            """
adapter: mcp
runtime: local
server: local-memory
tool: echo
timeout_seconds: true
""",
            "mcp tool node 'tool_node' timeout_seconds must be a positive integer",
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
        (
            """
- type: node_attempts
  node: only
""",
            "validation[0] node_attempts requires equals",
        ),
        (
            """
- type: node_policy_outcome
  node: only
  equals: unknown
""",
            "validation[0] node_policy_outcome has unsupported equals 'unknown'",
        ),
        (
            """
- type: node_contract
  node: only
  equals: unknown
""",
            "validation[0] node_contract has unsupported equals 'unknown'",
        ),
        (
            """
- type: node_resume_action
  node: only
  equals: reused
""",
            "validation[0] node_resume_action has unsupported equals 'reused'",
        ),
        (
            """
- type: node_artifact
  node: only
""",
            "validation[0] node_artifact requires name",
        ),
        (
            """
- type: node_artifact
  node: only
  name: note
  exists: present
""",
            "validation[0] node_artifact exists must be a boolean",
        ),
        (
            """
- type: node_governance
  node: only
  equals: remote_cancelled
""",
            "validation[0] node_governance has unsupported equals 'remote_cancelled'",
        ),
        (
            """
- type: assertion
  source: node_output
  node: only
  path: result
""",
            "validation[0] assertion requires one assertion operator",
        ),
        (
            """
- type: assertion
  source: tool_invocation
  path: status
  equals: completed
""",
            "validation[0] assertion source 'tool_invocation' requires node",
        ),
        (
            """
- type: assertion
  source: shell
  path: status
  equals: completed
""",
            "validation[0] assertion has unsupported source 'shell'",
        ),
        (
            """
- type: assertion
  source: run
  path: status
  equals: completed
  contains: comp
""",
            "validation[0] assertion must use exactly one assertion operator",
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
