from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .artifacts import event_artifacts
from .store import RunStore


RUN_STORE_TABLES = [
    "runs",
    "node_events",
    "verifications",
    "node_execution_reservations",
]

RUN_STORE_SCHEMA = {
    "runs": {
        "run_id": {"type": "text", "primary_key": True},
        "workflow_id": {"type": "text", "not_null": True},
        "status": {"type": "text", "not_null": True},
        "inputs_json": {"type": "text", "not_null": True},
        "outputs_json": {"type": "text", "not_null": True},
        "workflow_source_path": {"type": "text"},
        "workflow_snapshot": {"type": "text"},
        "workflow_sha256": {"type": "text"},
        "inputs_sha256": {"type": "text"},
        "git_commit": {"type": "text"},
        "environment_json": {"type": "text"},
    },
    "node_events": {
        "id": {"type": "integer", "primary_key": True, "autoincrement": True},
        "run_id": {"type": "text", "not_null": True},
        "node_id": {"type": "text", "not_null": True},
        "status": {"type": "text", "not_null": True},
        "input_json": {"type": "text", "not_null": True},
        "output_json": {"type": "text", "not_null": True},
        "metadata_json": {"type": "text"},
    },
    "verifications": {
        "id": {"type": "integer", "primary_key": True, "autoincrement": True},
        "run_id": {"type": "text", "not_null": True},
        "status": {"type": "text", "not_null": True},
        "checks_json": {"type": "text", "not_null": True},
    },
    "node_execution_reservations": {
        "id": {"type": "integer", "primary_key": True, "autoincrement": True},
        "run_id": {"type": "text", "not_null": True},
        "node_id": {"type": "text", "not_null": True},
    },
}


def inspect_run_store(store: RunStore, *, timeout_seconds: float = 1.0) -> dict[str, Any]:
    return _inspect_database_path(
        state_dir=store.state_dir,
        database_path=store.path,
        artifact_dir=store.state_dir / "artifacts",
        timeout_seconds=timeout_seconds,
    )


def inspect_state_dir(state_dir: str | Path, *, timeout_seconds: float = 1.0) -> dict[str, Any]:
    root = Path(state_dir)
    return _inspect_database_path(
        state_dir=root,
        database_path=root / "runs.sqlite",
        artifact_dir=root / "artifacts",
        timeout_seconds=timeout_seconds,
    )


def backup_run_store(
    state_dir: str | Path,
    backup_path: str | Path,
    *,
    timeout_seconds: float = 1.0,
) -> dict[str, Any]:
    root = Path(state_dir)
    source_path = root / "runs.sqlite"
    target_path = Path(backup_path)
    source_health = inspect_state_dir(root, timeout_seconds=timeout_seconds)
    if _same_path(source_path, target_path):
        return {
            "ok": False,
            "status": "backup_target_conflict",
            "source": _file_summary(source_path),
            "backup": _file_summary(target_path),
            "health": source_health,
            "error": {
                "category": "same_file",
                "message": "backup target must not be the live run store database",
            },
        }
    if not source_health["ok"]:
        return {
            "ok": False,
            "status": "source_unhealthy",
            "source": _file_summary(source_path),
            "backup": _file_summary(target_path),
            "health": source_health,
        }

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_target_path = _temporary_backup_path(target_path)
    try:
        _backup_sqlite_database(source_path, temporary_target_path, timeout_seconds=timeout_seconds)
        os.replace(temporary_target_path, target_path)
    except (OSError, sqlite3.Error) as exc:
        _remove_file_if_exists(temporary_target_path)
        return {
            "ok": False,
            "status": "backup_failed",
            "source": _file_summary(source_path),
            "backup": _file_summary(target_path),
            "health": source_health,
            "error": _backup_error_payload(exc),
        }

    backup_health = _inspect_database_path(
        state_dir=target_path.parent,
        database_path=target_path,
        artifact_dir=target_path.parent / "artifacts",
        timeout_seconds=timeout_seconds,
    )
    status = "backed_up" if backup_health["ok"] else "backup_verify_failed"
    return {
        "ok": backup_health["ok"],
        "status": status,
        "source": _file_summary(source_path),
        "backup": _file_summary(target_path),
        "health": backup_health,
    }


def preflight_restore_run_store(
    backup_path: str | Path,
    *,
    restore_state_dir: str | Path,
    timeout_seconds: float = 1.0,
) -> dict[str, Any]:
    source = Path(backup_path)
    restore_root = Path(restore_state_dir)
    restore_database_path = restore_root / "runs.sqlite"
    health = _inspect_database_path(
        state_dir=source.parent,
        database_path=source,
        artifact_dir=source.parent / "artifacts",
        timeout_seconds=timeout_seconds,
    )
    ok = bool(health["ok"])
    return {
        "ok": ok,
        "status": "restore_preflight_passed" if ok else "restore_preflight_failed",
        "backup": _file_summary(source),
        "restore_target": {
            "state_dir": str(restore_root),
            "database_path": str(restore_database_path),
            "would_overwrite": restore_database_path.exists(),
        },
        "health": health,
    }


def list_run_summaries(store: RunStore, status: str | None = None) -> list[dict[str, Any]]:
    return store.list_run_summaries(status=status)


def _inspect_database_path(
    *,
    state_dir: Path,
    database_path: Path,
    artifact_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    artifacts = _artifact_dir_summary(artifact_dir)
    state_dir_exists = state_dir.exists()
    base = {
        "state_dir": {"path": str(state_dir), "exists": state_dir_exists},
        "database": {
            "path": str(database_path),
            "exists": database_path.exists(),
            "size_bytes": database_path.stat().st_size if database_path.exists() else 0,
            "readable": False,
        },
        "tables": _missing_tables_payload(),
        "artifacts": artifacts,
        "checks": [],
    }

    if not state_dir_exists:
        checks = [
            {
                "name": "state_dir",
                "status": "failed",
                "message": "state directory is missing",
            }
        ]
        return {**base, "ok": False, "status": "missing_state_dir", "checks": checks}

    checks = [
        {
            "name": "state_dir",
            "status": "passed",
            "message": "state directory exists",
        }
    ]
    if not database_path.exists():
        checks.append(
            {
                "name": "database",
                "status": "failed",
                "message": "run store database is missing",
            }
        )
        return {**base, "ok": False, "status": "missing_database", "checks": checks}

    try:
        tables = _readonly_table_report(database_path, timeout_seconds=timeout_seconds)
    except sqlite3.Error as exc:
        error = _sqlite_error_payload(exc)
        checks.append(
            {
                "name": "database_read",
                "status": "failed",
                "message": error["message"],
            }
        )
        status = "database_locked" if error["category"] == "database_locked" else "database_unreadable"
        return {
            **base,
            "ok": False,
            "status": status,
            "database": {**base["database"], "readable": False, "error": error},
            "checks": checks,
        }

    checks.append(
        {
            "name": "database_read",
            "status": "passed",
            "message": "run store database is readable",
        }
    )
    schema_ok = all(table["present"] and table.get("schema_ok") for table in tables.values())
    checks.append(
        {
            "name": "schema",
            "status": "passed" if schema_ok else "failed",
            "message": "run store schema is compatible"
            if schema_ok
            else "run store schema drift detected",
        }
    )
    return {
        **base,
        "ok": schema_ok,
        "status": "healthy" if schema_ok else "schema_drift",
        "database": {**base["database"], "readable": True},
        "tables": tables,
        "checks": checks,
    }


def _missing_tables_payload() -> dict[str, dict[str, int | bool]]:
    return {
        table: {"present": False, "rows": 0}
        for table in RUN_STORE_TABLES
    }


def _readonly_table_report(database_path: Path, *, timeout_seconds: float) -> dict[str, dict[str, Any]]:
    uri = f"file:{database_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=timeout_seconds)) as connection:
        connection.row_factory = sqlite3.Row
        existing_tables = {
            row["name"]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }
        tables: dict[str, dict[str, Any]] = {}
        for table in RUN_STORE_TABLES:
            if table not in existing_tables:
                tables[table] = {"present": False, "rows": 0}
                continue
            columns = {
                row["name"]
                for row in connection.execute(f"pragma table_info({table})").fetchall()
            }
            expected_schema = RUN_STORE_SCHEMA[table]
            missing_columns = [
                column
                for column in expected_schema
                if column not in columns
            ]
            create_sql = _table_create_sql(connection, table)
            incompatible_columns = _incompatible_columns(
                table_info=connection.execute(f"pragma table_info({table})").fetchall(),
                expected_schema=expected_schema,
                create_sql=create_sql,
            )
            row = connection.execute(f"select count(*) as count from {table}").fetchone()
            tables[table] = {
                "present": True,
                "rows": int(row["count"]) if row is not None else 0,
                "schema_ok": not missing_columns and not incompatible_columns,
                "missing_columns": missing_columns,
                "incompatible_columns": incompatible_columns,
            }
    return tables


def _sqlite_error_payload(exc: sqlite3.Error) -> dict[str, str]:
    message = str(exc)
    normalized_message = message.lower()
    return {
        "category": "database_locked"
        if "locked" in normalized_message or "busy" in normalized_message
        else "sqlite_error",
        "message": message,
    }


def _backup_error_payload(exc: OSError | sqlite3.Error) -> dict[str, str]:
    if isinstance(exc, sqlite3.Error):
        return _sqlite_error_payload(exc)
    return {"category": "filesystem_error", "message": str(exc)}


def _backup_sqlite_database(
    source_path: Path,
    target_path: Path,
    *,
    timeout_seconds: float,
) -> None:
    source_uri = f"file:{source_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=timeout_seconds)) as source:
        with closing(sqlite3.connect(target_path, timeout=timeout_seconds)) as target:
            source.backup(target)


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve() == second.resolve()
    except OSError:
        return first.absolute() == second.absolute()


def _temporary_backup_path(target_path: Path) -> Path:
    return target_path.with_name(f".{target_path.name}.tmp")


def _remove_file_if_exists(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        return


def _incompatible_columns(
    *,
    table_info: list[sqlite3.Row],
    expected_schema: dict[str, dict[str, bool | str]],
    create_sql: str,
) -> list[dict[str, Any]]:
    actual_by_name = {str(row["name"]): row for row in table_info}
    normalized_create_sql = create_sql.lower()
    incompatible: list[dict[str, Any]] = []
    for column, expected in expected_schema.items():
        row = actual_by_name.get(column)
        if row is None:
            continue
        actual_type = str(row["type"] or "").lower()
        expected_type = str(expected.get("type", "")).lower()
        if expected_type and actual_type != expected_type:
            incompatible.append(
                {
                    "column": column,
                    "expected": {"type": expected_type},
                    "actual": {"type": actual_type},
                }
            )
        expected_not_null = bool(expected.get("not_null", False))
        actual_not_null = bool(row["notnull"])
        if expected_not_null and not actual_not_null:
            incompatible.append(
                {
                    "column": column,
                    "expected": {"not_null": True},
                    "actual": {"not_null": False},
                }
            )
        expected_primary_key = bool(expected.get("primary_key", False))
        actual_primary_key = bool(row["pk"])
        if expected_primary_key and not actual_primary_key:
            incompatible.append(
                {
                    "column": column,
                    "expected": {"primary_key": True},
                    "actual": {"primary_key": False},
                }
            )
        expected_autoincrement = bool(expected.get("autoincrement", False))
        if expected_autoincrement and "autoincrement" not in normalized_create_sql:
            incompatible.append(
                {
                    "column": column,
                    "expected": {"autoincrement": True},
                    "actual": {"autoincrement": False},
                }
            )
    return incompatible


def _table_create_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "select sql from sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone()
    return str(row["sql"] if row is not None and row["sql"] is not None else "")


def _file_summary(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists and path.is_file() else 0,
        "sha256": _file_sha256(path) if exists and path.is_file() else None,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plan_retention_cleanup(
    store: RunStore,
    *,
    keep_last: int,
    status: str | None = None,
) -> dict[str, Any]:
    if keep_last < 0:
        raise ValueError("keep_last must be >= 0")
    candidates = list_run_summaries(store, status=status)
    kept_runs = candidates[:keep_last]
    delete_runs = candidates[keep_last:]
    delete_run_ids = [run["run_id"] for run in delete_runs]
    artifacts_to_delete, skipped_artifacts = _managed_artifacts_for_runs(store, delete_run_ids)
    return {
        "mode": "dry_run",
        "keep_last": keep_last,
        "status": status,
        "kept_runs": kept_runs,
        "delete_runs": delete_runs,
        "delete_row_counts": store.related_row_counts(delete_run_ids),
        "artifacts_to_delete": artifacts_to_delete,
        "skipped_artifacts": skipped_artifacts,
        "orphan_artifacts": _orphan_artifacts(store),
    }


def apply_retention_cleanup(
    store: RunStore,
    *,
    keep_last: int,
    status: str | None = None,
) -> dict[str, Any]:
    plan = plan_retention_cleanup(store, keep_last=keep_last, status=status)
    deleted_files = _delete_artifact_files(plan["artifacts_to_delete"])
    delete_run_ids = [run["run_id"] for run in plan["delete_runs"]]
    deleted_row_counts = store.delete_runs(delete_run_ids)
    return {
        "mode": "apply",
        "keep_last": keep_last,
        "status": status,
        "kept_runs": plan["kept_runs"],
        "deleted_runs": plan["delete_runs"],
        "deleted_row_counts": deleted_row_counts,
        "deleted_artifacts": deleted_files,
        "skipped_artifacts": plan["skipped_artifacts"],
        "orphan_artifacts": _orphan_artifacts(store),
    }


def _artifact_dir_summary(artifact_dir: Path) -> dict[str, Any]:
    files = [
        path
        for path in artifact_dir.rglob("*")
        if path.is_file()
    ] if artifact_dir.exists() else []
    run_directories = [
        path
        for path in artifact_dir.iterdir()
        if path.is_dir()
    ] if artifact_dir.exists() else []
    return {
        "path": str(artifact_dir),
        "exists": artifact_dir.exists(),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "run_directories": len(run_directories),
    }


def _managed_artifacts_for_runs(
    store: RunStore,
    run_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    managed_root = (store.state_dir / "artifacts").resolve()
    artifacts: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for run_id in run_ids:
        try:
            run = store.get_run(run_id)
        except KeyError:
            continue
        for event in run.events:
            for artifact in event_artifacts(event):
                stored_path = artifact.get("stored_path")
                if not isinstance(stored_path, str) or not stored_path:
                    continue
                path = Path(stored_path)
                if not _is_managed_artifact_path(path, managed_root, run_id):
                    skipped.append(
                        {
                            "run_id": run_id,
                            "node_id": event.node_id,
                            "name": artifact.get("name"),
                            "path": str(path),
                            "reason": "outside_managed_artifacts",
                        }
                    )
                    continue
                artifacts.append(
                    {
                        "run_id": run_id,
                        "node_id": event.node_id,
                        "name": artifact.get("name"),
                        "path": str(path),
                        "exists": path.exists() and path.is_file(),
                        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
                    }
                )
    return artifacts, skipped


def _orphan_artifacts(store: RunStore) -> list[dict[str, Any]]:
    artifact_root = store.state_dir / "artifacts"
    if not artifact_root.exists():
        return []
    known_runs = list_run_summaries(store)
    known_run_ids = {run["run_id"] for run in known_runs}
    referenced_paths = _referenced_artifact_paths(store, known_runs)
    orphans: list[dict[str, Any]] = []
    for path in sorted(artifact_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(artifact_root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        run_id = relative.parts[0]
        if run_id in known_run_ids:
            if path.resolve() in referenced_paths:
                continue
            orphans.append(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "reason": "artifact_not_referenced",
                    "run_id": run_id,
                }
            )
            continue
        orphans.append(
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "reason": "run_not_found",
                "run_id": run_id,
            }
        )
    return orphans


def _referenced_artifact_paths(store: RunStore, runs: list[dict[str, Any]]) -> set[Path]:
    paths: set[Path] = set()
    for run_summary in runs:
        run_id = run_summary["run_id"]
        if not isinstance(run_id, str):
            continue
        try:
            run = store.get_run(run_id)
        except KeyError:
            continue
        for event in run.events:
            for artifact in event_artifacts(event):
                stored_path = artifact.get("stored_path")
                if isinstance(stored_path, str) and stored_path:
                    paths.add(Path(stored_path).resolve())
    return paths


def _delete_artifact_files(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deleted: list[dict[str, Any]] = []
    for artifact in artifacts:
        path = Path(str(artifact["path"]))
        run_id = str(artifact.get("run_id", ""))
        managed_root = path.parents[3] if len(path.parents) >= 4 else path.parent
        if path.exists() and path.is_file():
            size_bytes = path.stat().st_size
            path.unlink()
            _remove_empty_parents(path.parent, stop_at=managed_root / run_id)
            deleted.append({**artifact, "deleted": True, "size_bytes": size_bytes})
        else:
            deleted.append({**artifact, "deleted": False, "size_bytes": 0})
    return deleted


def _is_managed_artifact_path(path: Path, managed_root: Path, run_id: str) -> bool:
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(managed_root)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] == run_id


def _remove_empty_parents(path: Path, *, stop_at: Path) -> None:
    stop = stop_at.resolve()
    current = path.resolve()
    while current.exists():
        try:
            current.relative_to(stop)
        except ValueError:
            return
        try:
            current.rmdir()
        except OSError:
            return
        if current == stop:
            return
        current = current.parent
