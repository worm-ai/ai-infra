import hashlib
import json
from pathlib import Path
import shlex

from ai_infra import (
    get_run,
    load_workflow,
    load_workflow_from_source,
    resume_workflow,
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


def test_run_workflow_persists_artifact_evidence_in_event_metadata(tmp_path):
    artifact_path = tmp_path / "artifacts" / "note.txt"
    workflow_path = tmp_path / "artifact_workflow.yaml"
    workflow_path.write_text(
        f"""
id: artifact-workflow
entrypoint: write_note
nodes:
  write_note:
    type: tool
    artifacts:
      - name: note
        path: "{artifact_path.as_posix()}"
        content_type: text/plain
    tool:
      adapter: shell
      command: >-
        python -c "from pathlib import Path; import sys; path=Path(sys.argv[1]); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(sys.argv[2], encoding='utf-8'); print(path)" {shlex.quote(artifact_path.as_posix())} "{{topic}} evidence"
validations:
  - type: run_status
    equals: completed
  - type: node_artifact
    node: write_note
    name: note
    exists: true
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    verification = validate_stored_run(result.run_id, store=store)

    assert result.status == "completed"
    saved = get_run(result.run_id, store=store)
    [event] = saved.events
    assert "artifacts" not in event.output
    assert event.metadata["artifacts"] == [
        {
            "name": "note",
            "path": artifact_path.as_posix(),
            "stored_path": (tmp_path / "artifacts" / result.run_id / "write_note" / "note" / "note.txt").as_posix(),
            "content_type": "text/plain",
            "exists": True,
            "size_bytes": len("ABH evidence"),
            "sha256": hashlib.sha256(b"ABH evidence").hexdigest(),
        }
    ]
    assert Path(event.metadata["artifacts"][0]["stored_path"]).read_text(encoding="utf-8") == "ABH evidence"
    checks = {check.type: check for check in verification.checks}
    assert checks["node_artifact"].status == "passed"
    assert "artifact 'note' exists with sha256" in checks["node_artifact"].message


def test_node_artifact_validation_uses_stored_copy_when_original_is_removed(tmp_path):
    artifact_path = tmp_path / "source.txt"
    workflow_path = tmp_path / "stored_artifact_workflow.yaml"
    workflow_path.write_text(
        f"""
id: stored-artifact-workflow
entrypoint: writer
nodes:
  writer:
    type: tool
    artifacts:
      - name: note
        path: "{artifact_path.as_posix()}"
        content_type: text/plain
    tool:
      adapter: shell
      command: >-
        python -c "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('stable copy', encoding='utf-8')" {artifact_path.as_posix()}
validations:
  - type: run_status
    equals: completed
  - type: node_artifact
    node: writer
    name: note
    exists: true
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)
    result = run_workflow(workflow, {}, store=store)
    artifact_path.unlink()

    verification = validate_stored_run(result.run_id, store=store)

    assert verification.status == "passed"
    checks = {check.type: check for check in verification.checks}
    assert checks["node_artifact"].status == "passed"


def test_node_artifact_validation_detects_hash_mismatch_from_persisted_evidence(tmp_path):
    artifact_path = tmp_path / "mutable.txt"
    artifact_path.write_text("original", encoding="utf-8")
    store = RunStore(tmp_path / "runs.sqlite")
    store.save_run(
        StoredRun(
            run_id="run-artifact-hash",
            workflow_id="manual-artifact",
            status="completed",
            inputs={},
            outputs={"writer": {"result": "ok"}},
        )
    )
    store.add_event(
        NodeEvent(
            run_id="run-artifact-hash",
            node_id="writer",
            status="completed",
            input={},
            output={"result": "ok"},
            metadata={
                "artifacts": [
                    {
                        "name": "note",
                        "path": artifact_path.as_posix(),
                        "content_type": "text/plain",
                        "exists": True,
                        "size_bytes": len("original"),
                        "sha256": hashlib.sha256(b"original").hexdigest(),
                    }
                ]
            },
        )
    )
    artifact_path.write_text("changed", encoding="utf-8")
    workflow = Workflow(
        id="manual-artifact",
        name="Manual Artifact",
        version="0.1",
        entrypoint="writer",
        nodes=[WorkflowNode(id="writer", type="template", template="unused")],
        edges=[],
        validations=[
            WorkflowValidation(
                type="node_artifact",
                config={"node": "writer", "name": "note", "exists": True},
            )
        ],
    )

    verification = validate_run("run-artifact-hash", workflow, store=store)

    assert verification.status == "failed"
    [check] = verification.checks
    assert check.type == "node_artifact"
    assert check.status == "failed"
    assert "sha256 changed" in check.message


def test_resume_workflow_skips_completed_nodes_and_reruns_failed_nodes(tmp_path):
    calls = {"prepare": 0, "flaky": 0}

    def prepare(args):
        calls["prepare"] += 1
        return f"prepared:{args['value']}"

    def flaky(args):
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise RuntimeError("temporary resume failure")
        return f"finished:{args['value']}"

    default_tool_registry.register_python("resume_prepare", prepare)
    default_tool_registry.register_python("resume_flaky", flaky)
    workflow_path = tmp_path / "resume_workflow.yaml"
    workflow_path.write_text(
        """
id: resume-workflow
entrypoint: prepare
nodes:
  prepare:
    type: tool
    next: flaky
    tool:
      adapter: python
      name: resume_prepare
      args:
        value: "{topic}"
  flaky:
    type: tool
    next: downstream
    tool:
      adapter: python
      name: resume_flaky
      args:
        value: "{prepare.result}"
  downstream:
    type: template
    template: "Done {flaky.result}"
validations:
  - type: run_status
    equals: completed
  - type: node_completed
    node: flaky
  - type: node_resume_action
    node: prepare
    equals: skipped
  - type: node_resume_action
    node: flaky
    equals: rerun
  - type: node_resume_action
    node: downstream
    equals: run
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    first = run_workflow(workflow, {"topic": "ABH"}, store=store)
    resumed = resume_workflow(first.run_id, workflow, store=store)
    verification = validate_stored_run(first.run_id, store=store)

    assert first.status == "failed"
    assert resumed.run_id == first.run_id
    assert resumed.status == "completed"
    assert calls == {"prepare": 1, "flaky": 2}
    assert resumed.outputs["prepare"]["result"] == "prepared:ABH"
    assert resumed.outputs["flaky"]["result"] == "finished:prepared:ABH"
    assert resumed.outputs["downstream"] == "Done finished:prepared:ABH"
    saved = get_run(first.run_id, store=store)
    assert [event.node_id for event in saved.events] == [
        "prepare",
        "flaky",
        "prepare",
        "flaky",
        "downstream",
    ]
    assert saved.events[2].status == "skipped"
    assert saved.events[2].metadata["resume"]["action"] == "skipped"
    assert saved.events[3].status == "completed"
    assert saved.events[3].metadata["resume"]["action"] == "rerun"
    assert saved.events[4].metadata["resume"]["action"] == "run"
    assert verification.status == "passed"


def test_resume_workflow_skipped_events_do_not_count_as_node_attempts(tmp_path):
    calls = {"prepare": 0, "flaky": 0}

    def prepare(args):
        calls["prepare"] += 1
        return f"prepared:{args['value']}"

    def flaky(args):
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise RuntimeError("temporary attempt failure")
        return f"finished:{args['value']}"

    default_tool_registry.register_python("resume_attempt_prepare", prepare)
    default_tool_registry.register_python("resume_attempt_flaky", flaky)
    workflow_path = tmp_path / "resume_attempts.yaml"
    workflow_path.write_text(
        """
id: resume-attempts
entrypoint: prepare
nodes:
  prepare:
    type: tool
    next: flaky
    tool:
      adapter: python
      name: resume_attempt_prepare
      args:
        value: "{topic}"
  flaky:
    type: tool
    tool:
      adapter: python
      name: resume_attempt_flaky
      args:
        value: "{prepare.result}"
validations:
  - type: run_status
    equals: completed
  - type: node_attempts
    node: prepare
    equals: 1
  - type: node_attempts
    node: flaky
    equals: 2
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    first = run_workflow(workflow, {"topic": "ABH"}, store=store)
    resume_workflow(first.run_id, workflow, store=store)
    verification = validate_stored_run(first.run_id, store=store)

    checks = {check.message for check in verification.checks}
    assert verification.status == "passed"
    assert "node 'prepare' attempts is 1, expected 1" in checks
    assert "node 'flaky' attempts is 2, expected 2" in checks


def test_resume_workflow_reruns_descendants_of_failed_continue_nodes(tmp_path):
    calls = {"optional": 0}

    def optional(args):
        calls["optional"] += 1
        if calls["optional"] == 1:
            raise RuntimeError("optional outage")
        return "recovered"

    default_tool_registry.register_python("resume_continue_optional", optional)
    workflow_path = tmp_path / "resume_continue_descendant.yaml"
    workflow_path.write_text(
        """
id: resume-continue-descendant
entrypoint: optional
nodes:
  optional:
    type: tool
    next: downstream
    policy:
      on_failure: continue
    tool:
      adapter: python
      name: resume_continue_optional
  downstream:
    type: template
    template: "Downstream saw {optional.node_status}"
validations:
  - type: run_status
    equals: completed
  - type: node_resume_action
    node: optional
    equals: rerun
  - type: node_resume_action
    node: downstream
    equals: rerun
  - type: node_attempts
    node: downstream
    equals: 2
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(workflow_path)

    first = run_workflow(workflow, {}, store=store)
    resumed = resume_workflow(first.run_id, workflow, store=store)
    verification = validate_stored_run(first.run_id, store=store)

    assert first.status == "completed"
    assert first.outputs["downstream"] == "Downstream saw failed"
    assert resumed.status == "completed"
    assert resumed.outputs["downstream"] == "Downstream saw completed"
    assert verification.status == "passed"


def test_resume_workflow_rejects_changed_workflow_source(tmp_path):
    def fail(args):
        raise RuntimeError("first run failure")

    default_tool_registry.register_python("resume_source_fail", fail)
    workflow_path = tmp_path / "resume_drift.yaml"
    workflow_path.write_text(
        """
id: resume-drift
entrypoint: start
nodes:
  start:
    type: tool
    tool:
      adapter: python
      name: resume_source_fail
validations:
  - type: run_status
    equals: failed
""".strip(),
        encoding="utf-8",
    )
    store = RunStore(tmp_path / "runs.sqlite")
    original = load_workflow(workflow_path)
    result = run_workflow(original, {}, store=store)
    workflow_path.write_text(
        """
id: resume-drift
entrypoint: start
nodes:
  start:
    type: template
    template: "changed"
validations:
  - type: run_status
    equals: completed
""".strip(),
        encoding="utf-8",
    )
    changed = load_workflow(workflow_path)

    try:
        resume_workflow(result.run_id, changed, store=store)
    except RuntimeError as exc:
        assert "workflow source changed since run" in str(exc)
    else:
        raise AssertionError("resume_workflow should reject workflow source drift")
