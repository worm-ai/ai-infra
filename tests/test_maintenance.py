import json
from pathlib import Path

from ai_infra import load_workflow, run_workflow, validate_stored_run
from ai_infra.maintenance import (
    apply_retention_cleanup,
    inspect_run_store,
    plan_retention_cleanup,
)
from ai_infra import inspect_state_dir, list_run_summaries
from ai_infra.store import RunStore


def test_inspect_run_store_reports_health_counts_and_artifact_dir(tmp_path):
    state_dir = tmp_path / "state"
    store = RunStore(state_dir / "runs.sqlite")
    workflow = load_workflow(Path("examples/governance_workflow.yaml"))
    result = run_workflow(workflow, {"topic": "ABH"}, store=store)
    validate_stored_run(result.run_id, store=store)

    health = inspect_run_store(store)

    assert health["ok"] is True
    assert health["database"]["path"] == str(state_dir / "runs.sqlite")
    assert health["database"]["exists"] is True
    assert health["tables"] == {
        "runs": {"present": True, "rows": 1},
        "node_events": {"present": True, "rows": 2},
        "verifications": {"present": True, "rows": 1},
            "node_execution_reservations": {"present": True, "rows": 1},
    }
    assert health["artifacts"] == {
        "path": str(state_dir / "artifacts"),
        "exists": False,
        "files": 0,
        "bytes": 0,
        "run_directories": 0,
    }


def test_inspect_state_dir_reports_missing_database_without_creating_it(tmp_path):
    health = inspect_state_dir(tmp_path)

    assert health["database"]["exists"] is False
    assert health["tables"]["runs"] == {"present": False, "rows": 0}
    assert (tmp_path / "runs.sqlite").exists() is False


def test_list_run_summaries_filters_by_status_and_orders_newest_first(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    completed = run_workflow(load_workflow(Path("examples/hello_workflow.yaml")), {"topic": "ABH"}, store=store)
    failed = run_workflow(
        load_workflow(Path("examples/tool_failure_workflow.yaml")),
        {"topic": "ABH"},
        store=store,
    )

    all_runs = list_run_summaries(store)
    failed_runs = list_run_summaries(store, status="failed")

    assert [run["run_id"] for run in all_runs] == [failed.run_id, completed.run_id]
    assert all_runs[0]["workflow_id"] == "tool-failure-workflow"
    assert all_runs[0]["status"] == "failed"
    assert all_runs[0]["events"] == 1
    assert all_runs[0]["verifications"] == 0
    assert all_runs[1]["workflow_id"] == "hello-workflow"
    assert all_runs[1]["status"] == "completed"
    assert all_runs[1]["events"] == 2
    assert [run["run_id"] for run in failed_runs] == [failed.run_id]


def test_retention_cleanup_dry_run_keeps_newest_and_preserves_database(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    workflow = load_workflow(Path("examples/governance_workflow.yaml"))
    first = run_workflow(workflow, {"topic": "one"}, store=store)
    second = run_workflow(workflow, {"topic": "two"}, store=store)
    third = run_workflow(workflow, {"topic": "three"}, store=store)

    plan = plan_retention_cleanup(store, keep_last=1)

    assert plan["mode"] == "dry_run"
    assert [run["run_id"] for run in plan["kept_runs"]] == [third.run_id]
    assert [run["run_id"] for run in plan["delete_runs"]] == [second.run_id, first.run_id]
    assert plan["delete_row_counts"] == {
        "runs": 2,
        "node_events": 4,
        "verifications": 0,
        "node_execution_reservations": 2,
    }
    assert list_run_summaries(store)[-1]["run_id"] == first.run_id


def test_retention_cleanup_apply_deletes_run_rows_and_safe_stored_artifacts(tmp_path):
    state_dir = tmp_path / "state"
    store = RunStore(state_dir / "runs.sqlite")
    artifact_path = tmp_path / "original.txt"
    input_path = tmp_path / "artifact_input.json"
    input_path.write_text(
        json.dumps({"topic": "ABH", "artifact_path": artifact_path.as_posix()}),
        encoding="utf-8",
    )
    workflow = load_workflow(Path("examples/artifact_workflow.yaml"))
    first = run_workflow(workflow, {"topic": "one", "artifact_path": artifact_path.as_posix()}, store=store)
    stored_artifact = state_dir / "artifacts" / first.run_id / "write_note" / "note" / "original.txt"
    second = run_workflow(workflow, {"topic": "two", "artifact_path": artifact_path.as_posix()}, store=store)

    applied = apply_retention_cleanup(store, keep_last=1)

    assert applied["mode"] == "apply"
    assert [run["run_id"] for run in applied["deleted_runs"]] == [first.run_id]
    assert stored_artifact.exists() is False
    assert artifact_path.exists() is True
    assert [run["run_id"] for run in list_run_summaries(store)] == [second.run_id]
    assert inspect_run_store(store)["tables"]["runs"]["rows"] == 1


def test_retention_reports_orphan_artifact_files_without_deleting_by_default(tmp_path):
    state_dir = tmp_path / "state"
    store = RunStore(state_dir / "runs.sqlite")
    run_workflow(load_workflow(Path("examples/hello_workflow.yaml")), {"topic": "ABH"}, store=store)
    orphan = state_dir / "artifacts" / "run-missing" / "node" / "artifact" / "note.txt"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("orphan", encoding="utf-8")

    plan = plan_retention_cleanup(store, keep_last=10)

    assert plan["delete_runs"] == []
    assert plan["orphan_artifacts"] == [
        {
            "path": str(orphan),
            "size_bytes": len("orphan"),
            "reason": "run_not_found",
            "run_id": "run-missing",
        }
    ]
    assert orphan.exists() is True


def test_retention_reports_unreferenced_artifact_files_inside_known_run_directory(tmp_path):
    state_dir = tmp_path / "state"
    store = RunStore(state_dir / "runs.sqlite")
    result = run_workflow(load_workflow(Path("examples/hello_workflow.yaml")), {"topic": "ABH"}, store=store)
    orphan = state_dir / "artifacts" / result.run_id / "node" / "artifact" / "note.txt"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("unreferenced", encoding="utf-8")

    plan = plan_retention_cleanup(store, keep_last=10)

    assert plan["orphan_artifacts"] == [
        {
            "path": str(orphan),
            "size_bytes": len("unreferenced"),
            "reason": "artifact_not_referenced",
            "run_id": result.run_id,
        }
    ]
    assert orphan.exists() is True
