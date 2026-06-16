from __future__ import annotations

import sqlite3
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


def inspect_run_store(store: RunStore) -> dict[str, Any]:
    row_counts = store.table_row_counts(RUN_STORE_TABLES)
    artifacts = _artifact_dir_summary(store.state_dir / "artifacts")
    return _health_payload(
        database_path=store.path,
        row_counts=row_counts,
        artifacts=artifacts,
    )


def inspect_state_dir(state_dir: str | Path) -> dict[str, Any]:
    root = Path(state_dir)
    database_path = root / "runs.sqlite"
    if not database_path.exists():
        row_counts: dict[str, int | None] = {table: None for table in RUN_STORE_TABLES}
    else:
        row_counts = _readonly_table_row_counts(database_path)
    artifacts = _artifact_dir_summary(root / "artifacts")
    return _health_payload(
        database_path=database_path,
        row_counts=row_counts,
        artifacts=artifacts,
    )


def _health_payload(
    *,
    database_path: Path,
    row_counts: dict[str, int | None],
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    tables = {
        table: {
            "present": row_counts[table] is not None,
            "rows": row_counts[table] if row_counts[table] is not None else 0,
        }
        for table in RUN_STORE_TABLES
    }
    return {
        "ok": all(table["present"] for table in tables.values()),
        "database": {
            "path": str(database_path),
            "exists": database_path.exists(),
            "size_bytes": database_path.stat().st_size if database_path.exists() else 0,
        },
        "tables": tables,
        "artifacts": artifacts,
    }


def list_run_summaries(store: RunStore, status: str | None = None) -> list[dict[str, Any]]:
    return store.list_run_summaries(status=status)


def _readonly_table_row_counts(database_path: Path) -> dict[str, int | None]:
    uri = f"file:{database_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        existing_tables = {
            row["name"]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }
        counts: dict[str, int | None] = {}
        for table in RUN_STORE_TABLES:
            if table not in existing_tables:
                counts[table] = None
                continue
            row = connection.execute(f"select count(*) as count from {table}").fetchone()
            counts[table] = int(row["count"]) if row is not None else 0
    return counts


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
