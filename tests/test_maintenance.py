import json
import sqlite3
from contextlib import closing
from pathlib import Path

from ai_infra import load_workflow, run_workflow, validate_stored_run
from ai_infra.maintenance import (
    apply_retention_cleanup,
    backup_run_store,
    inspect_run_store,
    preflight_restore_run_store,
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
    assert health["status"] == "healthy"
    assert health["checks"][0] == {
        "name": "state_dir",
        "status": "passed",
        "message": "state directory exists",
    }
    assert health["database"]["path"] == str(state_dir / "runs.sqlite")
    assert health["database"]["exists"] is True
    assert health["database"]["readable"] is True
    assert health["tables"] == {
        "runs": {
            "present": True,
            "rows": 1,
            "schema_ok": True,
            "missing_columns": [],
            "incompatible_columns": [],
        },
        "node_events": {
            "present": True,
            "rows": 2,
            "schema_ok": True,
            "missing_columns": [],
            "incompatible_columns": [],
        },
        "verifications": {
            "present": True,
            "rows": 1,
            "schema_ok": True,
            "missing_columns": [],
            "incompatible_columns": [],
        },
        "node_execution_reservations": {
            "present": True,
            "rows": 1,
            "schema_ok": True,
            "missing_columns": [],
            "incompatible_columns": [],
        },
    }
    assert health["artifacts"] == {
        "path": str(state_dir / "artifacts"),
        "exists": False,
        "files": 0,
        "bytes": 0,
        "run_directories": 0,
    }


def test_inspect_state_dir_reports_missing_state_dir_without_creating_it(tmp_path):
    state_dir = tmp_path / "missing-state"

    health = inspect_state_dir(state_dir)

    assert health["ok"] is False
    assert health["status"] == "missing_state_dir"
    assert health["state_dir"] == {"path": str(state_dir), "exists": False}
    assert health["database"]["exists"] is False
    assert health["checks"][0] == {
        "name": "state_dir",
        "status": "failed",
        "message": "state directory is missing",
    }
    assert state_dir.exists() is False


def test_inspect_state_dir_reports_missing_database_without_creating_it(tmp_path):
    health = inspect_state_dir(tmp_path)

    assert health["ok"] is False
    assert health["status"] == "missing_database"
    assert health["state_dir"] == {"path": str(tmp_path), "exists": True}
    assert health["database"]["exists"] is False
    assert health["tables"]["runs"] == {"present": False, "rows": 0}
    assert (tmp_path / "runs.sqlite").exists() is False


def test_inspect_state_dir_reports_corrupted_database_with_evidence(tmp_path):
    database = tmp_path / "runs.sqlite"
    database.write_bytes(b"this is not a sqlite database")

    health = inspect_state_dir(tmp_path)

    assert health["ok"] is False
    assert health["status"] == "database_unreadable"
    assert health["database"]["exists"] is True
    assert health["database"]["readable"] is False
    assert health["database"]["error"]["category"] == "sqlite_error"
    assert "not a database" in health["database"]["error"]["message"]
    assert health["checks"][-1]["name"] == "database_read"
    assert health["checks"][-1]["status"] == "failed"


def test_inspect_state_dir_reports_schema_drift_for_missing_columns(tmp_path):
    database = tmp_path / "runs.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                "create table runs (run_id text primary key, workflow_id text not null)"
            )
            connection.execute("create table node_events (id integer primary key autoincrement)")
            connection.execute("create table verifications (id integer primary key autoincrement)")
            connection.execute(
                "create table node_execution_reservations (id integer primary key autoincrement)"
            )

    health = inspect_state_dir(tmp_path)

    assert health["ok"] is False
    assert health["status"] == "schema_drift"
    assert health["tables"]["runs"]["present"] is True
    assert health["tables"]["runs"]["schema_ok"] is False
    assert "status" in health["tables"]["runs"]["missing_columns"]
    assert health["checks"][-1] == {
        "name": "schema",
        "status": "failed",
        "message": "run store schema drift detected",
    }


def test_inspect_state_dir_reports_schema_drift_for_missing_compatibility_columns(tmp_path):
    database = tmp_path / "runs.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.executescript(
                """
                create table runs (
                    run_id text primary key,
                    workflow_id text not null,
                    status text not null,
                    inputs_json text not null,
                    outputs_json text not null,
                    workflow_source_path text,
                    workflow_snapshot text,
                    workflow_sha256 text,
                    inputs_sha256 text,
                    git_commit text,
                    environment_json text
                );
                create table node_events (
                    id integer primary key autoincrement,
                    run_id text not null,
                    node_id text not null,
                    status text not null,
                    input_json text not null,
                    output_json text not null,
                    metadata_json text
                );
                create table verifications (
                    id integer primary key autoincrement,
                    run_id text not null,
                    status text not null,
                    checks_json text not null
                );
                create table node_execution_reservations (
                    id integer primary key autoincrement,
                    run_id text not null,
                    node_id text not null
                );
                """
            )

    health = inspect_state_dir(tmp_path)

    assert health["ok"] is False
    assert health["status"] == "schema_drift"
    assert "compatibility_json" in health["tables"]["runs"]["missing_columns"]
    assert "compatibility_json" in health["tables"]["verifications"]["missing_columns"]


def test_inspect_state_dir_reports_schema_drift_for_incompatible_column_constraints(tmp_path):
    database = tmp_path / "runs.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.executescript(
                """
                create table runs (
                    run_id text,
                    workflow_id text,
                    status text,
                    inputs_json text,
                    outputs_json text,
                    workflow_source_path text,
                    workflow_snapshot text,
                    workflow_sha256 text,
                    inputs_sha256 text,
                    git_commit text,
                    environment_json text
                );
                create table node_events (
                    id integer,
                    run_id text,
                    node_id text,
                    status text,
                    input_json text,
                    output_json text,
                    metadata_json text
                );
                create table verifications (
                    id integer,
                    run_id text,
                    status text,
                    checks_json text
                );
                create table node_execution_reservations (
                    id integer,
                    run_id text,
                    node_id text
                );
                """
            )

    health = inspect_state_dir(tmp_path)

    assert health["ok"] is False
    assert health["status"] == "schema_drift"
    assert health["tables"]["runs"]["schema_ok"] is False
    assert {
        "column": "run_id",
        "expected": {"primary_key": True},
        "actual": {"primary_key": False},
    } in health["tables"]["runs"]["incompatible_columns"]
    assert {
        "column": "workflow_id",
        "expected": {"not_null": True},
        "actual": {"not_null": False},
    } in health["tables"]["runs"]["incompatible_columns"]


def test_inspect_state_dir_reports_schema_drift_for_missing_autoincrement(tmp_path):
    database = tmp_path / "runs.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.executescript(
                """
                create table runs (
                    run_id text primary key,
                    workflow_id text not null,
                    status text not null,
                    inputs_json text not null,
                    outputs_json text not null,
                    workflow_source_path text,
                    workflow_snapshot text,
                    workflow_sha256 text,
                    inputs_sha256 text,
                    git_commit text,
                    environment_json text
                );
                create table node_events (
                    id integer primary key,
                    run_id text not null,
                    node_id text not null,
                    status text not null,
                    input_json text not null,
                    output_json text not null,
                    metadata_json text
                );
                create table verifications (
                    id integer primary key,
                    run_id text not null,
                    status text not null,
                    checks_json text not null
                );
                create table node_execution_reservations (
                    id integer primary key,
                    run_id text not null,
                    node_id text not null
                );
                """
            )

    health = inspect_state_dir(tmp_path)

    assert health["ok"] is False
    assert health["status"] == "schema_drift"
    assert {
        "column": "id",
        "expected": {"autoincrement": True},
        "actual": {"autoincrement": False},
    } in health["tables"]["node_events"]["incompatible_columns"]


def test_inspect_state_dir_releases_readonly_database_handle(tmp_path):
    database = tmp_path / "runs.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                "create table runs (run_id text primary key, workflow_id text not null)"
            )

    inspect_state_dir(tmp_path)

    database.unlink()
    assert database.exists() is False


def test_inspect_state_dir_reports_locked_database_without_hanging(tmp_path):
    RunStore(tmp_path / "runs.sqlite")
    connection = sqlite3.connect(tmp_path / "runs.sqlite")
    try:
        connection.execute("begin exclusive")

        health = inspect_state_dir(tmp_path, timeout_seconds=0.0)

        assert health["ok"] is False
        assert health["status"] == "database_locked"
        assert health["database"]["readable"] is False
        assert health["database"]["error"]["category"] == "database_locked"
        assert "locked" in health["database"]["error"]["message"]
    finally:
        connection.rollback()
        connection.close()


def test_backup_run_store_copies_database_and_preflight_validates_backup(tmp_path):
    state_dir = tmp_path / "state"
    store = RunStore(state_dir / "runs.sqlite")
    result = run_workflow(load_workflow(Path("examples/hello_workflow.yaml")), {"topic": "ABH"}, store=store)
    validate_stored_run(result.run_id, store=store)
    backup_path = tmp_path / "backups" / "runs-backup.sqlite"

    backup = backup_run_store(state_dir, backup_path)
    preflight = preflight_restore_run_store(backup_path, restore_state_dir=tmp_path / "restore")

    assert backup["ok"] is True
    assert backup["status"] == "backed_up"
    assert backup["source"]["path"] == str(state_dir / "runs.sqlite")
    assert backup["backup"]["path"] == str(backup_path)
    assert isinstance(backup["backup"]["sha256"], str)
    assert backup["backup"]["sha256"]
    assert backup["health"]["status"] == "healthy"
    assert backup["health"]["tables"]["runs"]["rows"] == 1
    assert backup["health"]["tables"]["verifications"]["rows"] == 1
    assert backup_path.exists() is True
    assert preflight["ok"] is True
    assert preflight["status"] == "restore_preflight_passed"
    assert preflight["backup"]["path"] == str(backup_path)
    assert preflight["restore_target"] == {
        "state_dir": str(tmp_path / "restore"),
        "database_path": str(tmp_path / "restore" / "runs.sqlite"),
        "would_overwrite": False,
    }
    assert preflight["health"]["tables"]["runs"]["rows"] == 1
    assert preflight["health"]["tables"]["verifications"]["rows"] == 1


def test_backup_run_store_uses_sqlite_backup_api_for_consistent_snapshot(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    store = RunStore(state_dir / "runs.sqlite")
    run_workflow(load_workflow(Path("examples/hello_workflow.yaml")), {"topic": "ABH"}, store=store)
    backup_path = tmp_path / "backups" / "runs-backup.sqlite"

    def fail_copy2(*args, **kwargs):
        raise AssertionError("backup_run_store should not use file-level copy2 for SQLite backups")

    monkeypatch.setattr("ai_infra.maintenance.shutil.copy2", fail_copy2)

    backup = backup_run_store(state_dir, backup_path)

    assert backup["ok"] is True
    assert backup["status"] == "backed_up"
    assert backup["health"]["status"] == "healthy"
    assert backup["health"]["tables"]["runs"]["rows"] == 1


def test_backup_run_store_rejects_source_database_as_backup_target(tmp_path):
    state_dir = tmp_path / "state"
    store = RunStore(state_dir / "runs.sqlite")
    run_workflow(load_workflow(Path("examples/hello_workflow.yaml")), {"topic": "ABH"}, store=store)

    backup = backup_run_store(state_dir, state_dir / "runs.sqlite")

    assert backup["ok"] is False
    assert backup["status"] == "backup_target_conflict"
    assert backup["error"] == {
        "category": "same_file",
        "message": "backup target must not be the live run store database",
    }
    assert inspect_state_dir(state_dir)["status"] == "healthy"
    assert inspect_state_dir(state_dir)["tables"]["runs"]["rows"] == 1


def test_backup_run_store_preserves_existing_backup_when_new_backup_fails(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    store = RunStore(state_dir / "runs.sqlite")
    run_workflow(load_workflow(Path("examples/hello_workflow.yaml")), {"topic": "ABH"}, store=store)
    backup_path = tmp_path / "backups" / "runs-backup.sqlite"
    backup_path.parent.mkdir(parents=True)
    backup_path.write_text("existing backup", encoding="utf-8")

    def fail_backup(*args, **kwargs):
        raise sqlite3.OperationalError("database is busy")

    monkeypatch.setattr("ai_infra.maintenance._backup_sqlite_database", fail_backup)

    backup = backup_run_store(state_dir, backup_path)

    assert backup["ok"] is False
    assert backup["status"] == "backup_failed"
    assert backup["error"]["category"] == "database_locked"
    assert backup_path.read_text(encoding="utf-8") == "existing backup"


def test_preflight_restore_rejects_corrupted_backup_without_creating_restore_target(tmp_path):
    backup_path = tmp_path / "runs-backup.sqlite"
    backup_path.write_bytes(b"not sqlite")
    restore_state_dir = tmp_path / "restore"

    preflight = preflight_restore_run_store(backup_path, restore_state_dir=restore_state_dir)

    assert preflight["ok"] is False
    assert preflight["status"] == "restore_preflight_failed"
    assert preflight["health"]["status"] == "database_unreadable"
    assert restore_state_dir.exists() is False


def test_sqlite_error_payload_classifies_busy_as_database_locked():
    from ai_infra.maintenance import _sqlite_error_payload

    payload = _sqlite_error_payload(sqlite3.OperationalError("database is busy"))

    assert payload == {
        "category": "database_locked",
        "message": "database is busy",
    }


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
