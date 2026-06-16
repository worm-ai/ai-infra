from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NodeEvent:
    run_id: str
    node_id: str
    status: str
    input: dict[str, Any]
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationCheck:
    type: str
    status: str
    message: str


@dataclass(frozen=True)
class RunProvenance:
    workflow_source_path: str | None
    workflow_snapshot: str
    workflow_sha256: str
    inputs_sha256: str
    git_commit: str | None
    environment: dict[str, Any]


@dataclass(frozen=True)
class StoredVerification:
    id: int
    run_id: str
    status: str
    checks: list[VerificationCheck]


@dataclass(frozen=True)
class StoredRun:
    run_id: str
    workflow_id: str
    status: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    workflow_source_path: str | None = None
    provenance: RunProvenance | None = None
    events: list[NodeEvent] = field(default_factory=list)
    verifications: list[StoredVerification] = field(default_factory=list)


class RunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def state_dir(self) -> Path:
        return self.path.parent

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                create table if not exists runs (
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
                create table if not exists node_events (
                    id integer primary key autoincrement,
                    run_id text not null,
                    node_id text not null,
                    status text not null,
                    input_json text not null,
                    output_json text not null,
                    metadata_json text
                );
                create table if not exists verifications (
                    id integer primary key autoincrement,
                    run_id text not null,
                    status text not null,
                    checks_json text not null
                );
                create table if not exists node_execution_reservations (
                    id integer primary key autoincrement,
                    run_id text not null,
                    node_id text not null
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("pragma table_info(runs)").fetchall()
            }
            if "workflow_source_path" not in columns:
                connection.execute("alter table runs add column workflow_source_path text")
            if "workflow_snapshot" not in columns:
                connection.execute("alter table runs add column workflow_snapshot text")
            if "workflow_sha256" not in columns:
                connection.execute("alter table runs add column workflow_sha256 text")
            if "inputs_sha256" not in columns:
                connection.execute("alter table runs add column inputs_sha256 text")
            if "git_commit" not in columns:
                connection.execute("alter table runs add column git_commit text")
            if "environment_json" not in columns:
                connection.execute("alter table runs add column environment_json text")
            event_columns = {
                row["name"]
                for row in connection.execute("pragma table_info(node_events)").fetchall()
            }
            if "metadata_json" not in event_columns:
                connection.execute("alter table node_events add column metadata_json text")

    def save_run(self, run: StoredRun) -> None:
        provenance = run.provenance
        workflow_source_path = (
            provenance.workflow_source_path if provenance is not None else run.workflow_source_path
        )
        with self._connect() as connection:
            connection.execute(
                """
                insert or replace into runs (
                    run_id,
                    workflow_id,
                    status,
                    inputs_json,
                    outputs_json,
                    workflow_source_path,
                    workflow_snapshot,
                    workflow_sha256,
                    inputs_sha256,
                    git_commit,
                    environment_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.workflow_id,
                    run.status,
                    json.dumps(run.inputs, ensure_ascii=False),
                    json.dumps(run.outputs, ensure_ascii=False),
                    workflow_source_path,
                    provenance.workflow_snapshot if provenance is not None else None,
                    provenance.workflow_sha256 if provenance is not None else None,
                    provenance.inputs_sha256 if provenance is not None else None,
                    provenance.git_commit if provenance is not None else None,
                    json.dumps(provenance.environment, ensure_ascii=False)
                    if provenance is not None
                    else None,
                ),
            )

    def add_event(self, event: NodeEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into node_events (run_id, node_id, status, input_json, output_json, metadata_json)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.node_id,
                    event.status,
                    json.dumps(event.input, ensure_ascii=False),
                    json.dumps(event.output, ensure_ascii=False),
                    json.dumps(event.metadata, ensure_ascii=False),
                ),
            )

    def replace_events(self, run_id: str, events: list[NodeEvent]) -> None:
        with self._connect() as connection:
            connection.execute("delete from node_events where run_id = ?", (run_id,))
            for event in events:
                connection.execute(
                    """
                    insert into node_events (run_id, node_id, status, input_json, output_json, metadata_json)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.run_id,
                        event.node_id,
                        event.status,
                        json.dumps(event.input, ensure_ascii=False),
                        json.dumps(event.output, ensure_ascii=False),
                        json.dumps(event.metadata, ensure_ascii=False),
                    ),
                )

    def count_node_executions(self, run_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                select count(*) as count
                from node_execution_reservations
                where run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def reserve_node_execution(
        self,
        run_id: str,
        node_id: str,
        max_node_executions: int,
    ) -> tuple[bool, int]:
        with self._connect() as connection:
            connection.execute("begin immediate")
            row = connection.execute(
                """
                select count(*) as count
                from node_execution_reservations
                where run_id = ?
                """,
                (run_id,),
            ).fetchone()
            executions_used = int(row["count"]) if row is not None else 0
            if executions_used >= max_node_executions:
                return False, executions_used
            connection.execute(
                """
                insert into node_execution_reservations (run_id, node_id)
                values (?, ?)
                """,
                (run_id, node_id),
            )
            return True, executions_used + 1

    def add_verification(self, run_id: str, status: str, checks: list[VerificationCheck]) -> StoredVerification:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into verifications (run_id, status, checks_json)
                values (?, ?, ?)
                """,
                (
                    run_id,
                    status,
                    json.dumps([check.__dict__ for check in checks], ensure_ascii=False),
                ),
            )
            verification_id = int(cursor.lastrowid)
        return StoredVerification(id=verification_id, run_id=run_id, status=status, checks=checks)

    def table_row_counts(self, tables: list[str]) -> dict[str, int | None]:
        counts: dict[str, int | None] = {}
        with self._connect() as connection:
            existing_tables = {
                row["name"]
                for row in connection.execute(
                    "select name from sqlite_master where type = 'table'"
                ).fetchall()
            }
            for table in tables:
                if table not in existing_tables:
                    counts[table] = None
                    continue
                row = connection.execute(f"select count(*) as count from {table}").fetchone()
                counts[table] = int(row["count"]) if row is not None else 0
        return counts

    def list_run_summaries(self, status: str | None = None) -> list[dict[str, Any]]:
        where_clause = ""
        params: tuple[str, ...] = ()
        if status is not None:
            where_clause = "where r.status = ?"
            params = (status,)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                select
                    r.rowid as sort_id,
                    r.run_id,
                    r.workflow_id,
                    r.status,
                    r.workflow_source_path,
                    r.workflow_sha256,
                    r.inputs_sha256,
                    r.git_commit,
                    (
                        select count(*)
                        from node_events e
                        where e.run_id = r.run_id
                    ) as events,
                    (
                        select count(*)
                        from verifications v
                        where v.run_id = r.run_id
                    ) as verifications,
                    (
                        select count(*)
                        from node_execution_reservations n
                        where n.run_id = r.run_id
                    ) as node_execution_reservations
                from runs r
                {where_clause}
                order by r.rowid desc
                """,
                params,
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "workflow_id": row["workflow_id"],
                "status": row["status"],
                "workflow_source_path": row["workflow_source_path"],
                "workflow_sha256": row["workflow_sha256"],
                "inputs_sha256": row["inputs_sha256"],
                "git_commit": row["git_commit"],
                "events": int(row["events"]),
                "verifications": int(row["verifications"]),
                "node_execution_reservations": int(row["node_execution_reservations"]),
            }
            for row in rows
        ]

    def related_row_counts(self, run_ids: list[str]) -> dict[str, int]:
        if not run_ids:
            return {
                "runs": 0,
                "node_events": 0,
                "verifications": 0,
                "node_execution_reservations": 0,
            }
        placeholders = ",".join("?" for _ in run_ids)
        params = tuple(run_ids)
        with self._connect() as connection:
            return {
                "runs": _count_related_rows(connection, "runs", placeholders, params),
                "node_events": _count_related_rows(connection, "node_events", placeholders, params),
                "verifications": _count_related_rows(connection, "verifications", placeholders, params),
                "node_execution_reservations": _count_related_rows(
                    connection,
                    "node_execution_reservations",
                    placeholders,
                    params,
                ),
            }

    def delete_runs(self, run_ids: list[str]) -> dict[str, int]:
        counts = self.related_row_counts(run_ids)
        if not run_ids:
            return counts
        placeholders = ",".join("?" for _ in run_ids)
        params = tuple(run_ids)
        with self._connect() as connection:
            connection.execute(
                f"delete from node_execution_reservations where run_id in ({placeholders})",
                params,
            )
            connection.execute(
                f"delete from verifications where run_id in ({placeholders})",
                params,
            )
            connection.execute(
                f"delete from node_events where run_id in ({placeholders})",
                params,
            )
            connection.execute(
                f"delete from runs where run_id in ({placeholders})",
                params,
            )
        return counts

    def get_run(self, run_id: str) -> StoredRun:
        with self._connect() as connection:
            run_row = connection.execute("select * from runs where run_id = ?", (run_id,)).fetchone()
            if run_row is None:
                raise KeyError(f"run {run_id!r} not found")
            event_rows = connection.execute(
                "select * from node_events where run_id = ? order by id",
                (run_id,),
            ).fetchall()
            verification_rows = connection.execute(
                "select * from verifications where run_id = ? order by id",
                (run_id,),
            ).fetchall()

        events = [
            NodeEvent(
                run_id=row["run_id"],
                node_id=row["node_id"],
                status=row["status"],
                input=json.loads(row["input_json"]),
                output=json.loads(row["output_json"]),
                metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            )
            for row in event_rows
        ]
        verifications = [
            StoredVerification(
                id=int(row["id"]),
                run_id=row["run_id"],
                status=row["status"],
                checks=[
                    VerificationCheck(
                        type=item["type"],
                        status=item["status"],
                        message=item["message"],
                    )
                    for item in json.loads(row["checks_json"])
                ],
            )
            for row in verification_rows
        ]
        provenance = _run_provenance_from_row(run_row)
        return StoredRun(
            run_id=run_row["run_id"],
            workflow_id=run_row["workflow_id"],
            status=run_row["status"],
            inputs=json.loads(run_row["inputs_json"]),
            outputs=json.loads(run_row["outputs_json"]),
            workflow_source_path=run_row["workflow_source_path"],
            provenance=provenance,
            events=events,
            verifications=verifications,
        )


def _count_related_rows(
    connection: sqlite3.Connection,
    table: str,
    placeholders: str,
    params: tuple[str, ...],
) -> int:
    row = connection.execute(
        f"select count(*) as count from {table} where run_id in ({placeholders})",
        params,
    ).fetchone()
    return int(row["count"]) if row is not None else 0


def _run_provenance_from_row(row: sqlite3.Row) -> RunProvenance | None:
    workflow_snapshot = row["workflow_snapshot"]
    workflow_sha256 = row["workflow_sha256"]
    inputs_sha256 = row["inputs_sha256"]
    if not workflow_snapshot or not workflow_sha256 or not inputs_sha256:
        return None
    environment_json = row["environment_json"]
    return RunProvenance(
        workflow_source_path=row["workflow_source_path"],
        workflow_snapshot=workflow_snapshot,
        workflow_sha256=workflow_sha256,
        inputs_sha256=inputs_sha256,
        git_commit=row["git_commit"],
        environment=json.loads(environment_json) if environment_json else {},
    )
