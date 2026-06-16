import hashlib
import json
from pathlib import Path

from ai_infra import (
    get_run,
    load_workflow,
    load_workflow_from_source,
    run_workflow,
    validate_run,
    validate_stored_run,
)
from ai_infra.config import Workflow, WorkflowNode, WorkflowValidation
from ai_infra.store import NodeEvent, RunStore, StoredRun
from ai_infra.tools import default_tool_registry


def _sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_run_workflow_persists_completed_run_and_node_events(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow_path = Path("examples/hello_workflow.yaml")
    workflow_source = workflow_path.read_text(encoding="utf-8")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.status == "completed"
    assert result.outputs["draft"] == "Draft a short note about ABH."
    assert result.outputs["review"] == "Review result: Draft a short note about ABH."

    saved = get_run(result.run_id, store=store)
    assert saved.run_id == result.run_id
    assert saved.status == "completed"
    assert [event.node_id for event in saved.events] == ["draft", "review"]
    assert saved.provenance is not None
    assert saved.provenance.workflow_source_path == str(workflow_path)
    assert saved.provenance.workflow_snapshot == workflow_source
    assert saved.provenance.workflow_sha256 == _sha256_text(workflow_source)
    assert saved.provenance.inputs_sha256 == _sha256_text(_canonical_json({"topic": "ABH"}))
    assert "python_version" in saved.provenance.environment


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


def test_provenance_snapshot_matches_loaded_workflow_when_source_changes_before_run(tmp_path):
    workflow_path = tmp_path / "loaded_then_changed.yaml"
    original_source = """
id: loaded-then-changed
name: Loaded Then Changed
version: "0.1"
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Original {topic}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: draft
""".strip()
    workflow_path.write_text(original_source, encoding="utf-8")
    workflow = load_workflow(workflow_path)
    workflow_path.write_text(
        """
id: loaded-then-changed
name: Loaded Then Changed
version: "0.1"
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Changed {topic}"
validations:
  - type: run_status
    equals: completed
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    assert result.outputs["draft"] == "Original ABH"
    saved = get_run(result.run_id, store=store)
    assert saved.provenance is not None
    assert saved.provenance.workflow_snapshot == original_source
    assert saved.provenance.workflow_sha256 == _sha256_text(original_source)


def test_source_only_workflow_persists_snapshot_and_verifies_from_snapshot(tmp_path):
    source = """
id: source-only
name: Source Only
version: "0.1"
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Source {topic}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: draft
""".strip()
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow_from_source(source)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    saved = get_run(result.run_id, store=store)
    assert saved.provenance is not None
    assert saved.provenance.workflow_source_path is None
    assert saved.provenance.workflow_snapshot == source
    assert saved.provenance.workflow_sha256 == _sha256_text(source)
    assert verification.status == "passed"
    assert verification.checks[0].type == "workflow_source_integrity"
    assert verification.checks[0].status == "passed"


def test_constructed_workflow_without_source_snapshot_still_has_reloadable_provenance(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = Workflow(
        id="constructed",
        name="Constructed",
        version="0.1",
        entrypoint="draft",
        nodes=[
            WorkflowNode(
                id="draft",
                type="template",
                template="Constructed {topic}",
            )
        ],
        edges=[],
        validations=[
            WorkflowValidation(type="run_status", config={"equals": "completed"}),
            WorkflowValidation(type="node_completed", config={"node": "draft"}),
        ],
    )

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    saved = get_run(result.run_id, store=store)
    assert saved.provenance is not None
    assert saved.provenance.workflow_source_path is None
    assert '"constructed"' in saved.provenance.workflow_snapshot
    assert verification.status == "passed"


def test_validate_stored_run_detects_workflow_source_drift_but_uses_snapshot(tmp_path):
    workflow_path = tmp_path / "drift_workflow.yaml"
    workflow_path.write_text(
        """
id: drift-workflow
name: Drift Workflow
version: "0.1"
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: draft
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)

    workflow_path.write_text(
        """
id: changed-workflow
name: Changed Workflow
version: "0.1"
entrypoint: other
nodes:
  other:
    type: template
    template: "Changed {topic}"
validations:
  - type: run_status
    equals: failed
""".strip(),
        encoding="utf-8",
    )

    verification = validate_stored_run(result.run_id, store=store)

    assert verification.status == "failed"
    checks = {check.type: check for check in verification.checks}
    assert checks["workflow_source_integrity"].status == "failed"
    assert "changed since run" in checks["workflow_source_integrity"].message
    assert checks["run_status"].status == "passed"
    assert checks["node_completed"].status == "passed"

    saved = get_run(result.run_id, store=store)
    assert saved.verifications[-1].checks[0].type == "workflow_source_integrity"


def test_run_workflow_retries_failed_node_and_persists_attempt_evidence(tmp_path):
    attempts = {"count": 0}

    def flaky_tool(args):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary outage")
        return f"ok:{args['value']}"

    default_tool_registry.register_python("flaky_once", flaky_tool)
    workflow_path = tmp_path / "retry_workflow.yaml"
    workflow_path.write_text(
        """
id: retry-workflow
entrypoint: flaky
nodes:
  flaky:
    type: tool
    policy:
      on_failure: halt
      max_attempts: 2
    tool:
      adapter: python
      name: flaky_once
      args:
        value: "{topic}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: flaky
  - type: node_attempts
    node: flaky
    equals: 2
  - type: node_policy_outcome
    node: flaky
    equals: retry_succeeded
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    assert result.status == "completed"
    assert result.outputs["flaky"]["result"] == "ok:ABH"
    saved = get_run(result.run_id, store=store)
    [failed_attempt, completed_attempt] = saved.events
    assert failed_attempt.node_id == "flaky"
    assert failed_attempt.status == "failed"
    assert failed_attempt.output["attempt"] == 1
    assert failed_attempt.output["max_attempts"] == 2
    assert failed_attempt.output["policy_outcome"] == "retrying"
    assert "temporary outage" in failed_attempt.output["error"]
    assert completed_attempt.status == "completed"
    assert completed_attempt.output["attempt"] == 2
    assert completed_attempt.output["attempts"] == 2
    assert completed_attempt.output["policy_outcome"] == "retry_succeeded"
    assert verification.status == "passed"


def test_run_workflow_records_retry_exhausted_and_halts_downstream_nodes(tmp_path):
    def always_fails(args):
        raise RuntimeError(f"permanent outage for {args['value']}")

    default_tool_registry.register_python("always_fails", always_fails)
    workflow_path = tmp_path / "retry_exhausted_workflow.yaml"
    workflow_path.write_text(
        """
id: retry-exhausted-workflow
entrypoint: flaky
nodes:
  flaky:
    type: tool
    next: downstream
    policy:
      on_failure: halt
      max_attempts: 2
    tool:
      adapter: python
      name: always_fails
      args:
        value: "{topic}"
  downstream:
    type: template
    template: "Should not execute {flaky.result}"
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: flaky
  - type: node_attempts
    node: flaky
    equals: 2
  - type: node_policy_outcome
    node: flaky
    equals: retry_exhausted
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    assert result.status == "failed"
    assert "downstream" not in result.outputs
    saved = get_run(result.run_id, store=store)
    assert [event.node_id for event in saved.events] == ["flaky", "flaky"]
    assert [event.output["attempt"] for event in saved.events] == [1, 2]
    assert saved.events[-1].output["policy_outcome"] == "retry_exhausted"
    assert verification.status == "passed"


def test_run_workflow_can_continue_after_retry_exhaustion_when_policy_allows(tmp_path):
    def always_fails(args):
        raise RuntimeError("non-blocking failure")

    default_tool_registry.register_python("non_blocking_failure", always_fails)
    workflow_path = tmp_path / "continue_workflow.yaml"
    workflow_path.write_text(
        """
id: continue-workflow
entrypoint: optional
nodes:
  optional:
    type: tool
    next: downstream
    policy:
      on_failure: continue
      max_attempts: 2
    tool:
      adapter: python
      name: non_blocking_failure
  downstream:
    type: template
    template: "Continued after {optional.error}"
validations:
  - type: run_status
    equals: completed
  - type: node_failed
    node: optional
  - type: node_completed
    node: downstream
  - type: node_policy_outcome
    node: optional
    equals: continued_after_failure
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    assert result.status == "completed"
    assert result.outputs["downstream"] == "Continued after non-blocking failure"
    saved = get_run(result.run_id, store=store)
    assert [event.node_id for event in saved.events] == ["optional", "optional", "downstream"]
    assert saved.events[-2].output["policy_outcome"] == "continued_after_failure"
    assert verification.status == "passed"


def test_run_workflow_persists_passing_output_contract_evidence(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow_path = tmp_path / "output_contract_workflow.yaml"
    workflow_path.write_text(
        """
id: output-contract-workflow
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
  - type: run_status
    equals: completed
  - type: node_completed
    node: python_echo
  - type: node_contract
    node: python_echo
    equals: passed
""".strip(),
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    assert result.status == "completed"
    assert result.outputs["python_echo"]["result"] == "ABH"
    saved = get_run(result.run_id, store=store)
    [event] = saved.events
    assert event.status == "completed"
    assert "contract" not in event.output
    assert event.metadata["contract"] == {
        "output": {
            "status": "passed",
            "type": "object",
            "required_fields": {
                "result": "string",
                "adapter": "string",
            },
            "missing_fields": [],
            "type_errors": [],
        }
    }
    checks = {check.type: check for check in verification.checks}
    assert checks["node_contract"].status == "passed"
    assert "contract status is 'passed'" in checks["node_contract"].message


def test_run_workflow_fails_node_when_output_contract_fails(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow_path = tmp_path / "output_contract_failure_workflow.yaml"
    workflow_path.write_text(
        """
id: output-contract-failure-workflow
entrypoint: python_echo
nodes:
  python_echo:
    type: tool
    contract:
      output:
        type: object
        required_fields:
          missing: string
          adapter: string
    tool:
      adapter: python
      name: echo
      args:
        value: "{topic}"
validations:
  - type: run_status
    equals: failed
  - type: node_failed
    node: python_echo
  - type: node_contract
    node: python_echo
    equals: failed
""".strip(),
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    assert result.status == "failed"
    saved = get_run(result.run_id, store=store)
    [event] = saved.events
    assert event.status == "failed"
    assert "contract" not in event.output
    assert event.metadata["contract"]["output"]["status"] == "failed"
    assert event.metadata["contract"]["output"]["missing_fields"] == ["missing"]
    assert event.output["error"] == "output contract failed for node 'python_echo': missing field 'missing'"
    checks = {check.type: check for check in verification.checks}
    assert checks["node_contract"].status == "passed"
    assert "contract status is 'failed'" in checks["node_contract"].message


def test_output_contract_evidence_does_not_overwrite_user_contract_field(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow_path = tmp_path / "user_contract_field_workflow.yaml"
    workflow_path.write_text(
        """
id: user-contract-field-workflow
entrypoint: producer
nodes:
  producer:
    type: tool
    next: downstream
    contract:
      output:
        type: object
        required_fields:
          result: object
          adapter: string
    tool:
      adapter: python
      name: echo
      args:
        value:
          contract: user-owned-contract
  downstream:
    type: template
    template: "Downstream sees {producer.result.contract}"
validations:
  - type: run_status
    equals: completed
  - type: node_contract
    node: producer
    equals: passed
""".strip(),
        encoding="utf-8",
    )
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    assert result.status == "completed"
    assert result.outputs["producer"]["result"]["contract"] == "user-owned-contract"
    assert result.outputs["downstream"] == "Downstream sees user-owned-contract"
    saved = get_run(result.run_id, store=store)
    producer_event = saved.events[0]
    assert producer_event.output["result"]["contract"] == "user-owned-contract"
    assert producer_event.metadata["contract"]["output"]["status"] == "passed"
    assert verification.status == "passed"


def test_node_contract_validation_uses_event_metadata_not_user_output_contract_field(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    store.save_run(
        StoredRun(
            run_id="run-user-contract-field",
            workflow_id="manual-contract-field",
            status="completed",
            inputs={},
            outputs={"producer": {"contract": "user-owned-contract"}},
        )
    )
    store.add_event(
        NodeEvent(
            run_id="run-user-contract-field",
            node_id="producer",
            status="completed",
            input={},
            output={"contract": "user-owned-contract"},
            metadata={
                "contract": {
                    "output": {
                        "status": "passed",
                        "type": "object",
                        "required_fields": {"contract": "string"},
                        "missing_fields": [],
                        "type_errors": [],
                    }
                }
            },
        )
    )
    workflow = Workflow(
        id="manual-contract-field",
        name="Manual Contract Field",
        version="0.1",
        entrypoint="producer",
        nodes=[WorkflowNode(id="producer", type="template", template="unused")],
        edges=[],
        validations=[
            WorkflowValidation(type="node_contract", config={"node": "producer", "equals": "passed"})
        ],
    )

    verification = validate_run("run-user-contract-field", workflow, store=store)

    assert verification.status == "passed"
