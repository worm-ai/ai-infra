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


@dataclass(frozen=True)
class VerificationCheck:
    type: str
    status: str
    message: str


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
    events: list[NodeEvent] = field(default_factory=list)
    verifications: list[StoredVerification] = field(default_factory=list)


class RunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

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
                    outputs_json text not null
                );
                create table if not exists node_events (
                    id integer primary key autoincrement,
                    run_id text not null,
                    node_id text not null,
                    status text not null,
                    input_json text not null,
                    output_json text not null
                );
                create table if not exists verifications (
                    id integer primary key autoincrement,
                    run_id text not null,
                    status text not null,
                    checks_json text not null
                );
                """
            )

    def save_run(self, run: StoredRun) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert or replace into runs (run_id, workflow_id, status, inputs_json, outputs_json)
                values (?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.workflow_id,
                    run.status,
                    json.dumps(run.inputs, ensure_ascii=False),
                    json.dumps(run.outputs, ensure_ascii=False),
                ),
            )

    def add_event(self, event: NodeEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into node_events (run_id, node_id, status, input_json, output_json)
                values (?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.node_id,
                    event.status,
                    json.dumps(event.input, ensure_ascii=False),
                    json.dumps(event.output, ensure_ascii=False),
                ),
            )

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
        return StoredRun(
            run_id=run_row["run_id"],
            workflow_id=run_row["workflow_id"],
            status=run_row["status"],
            inputs=json.loads(run_row["inputs_json"]),
            outputs=json.loads(run_row["outputs_json"]),
            events=events,
            verifications=verifications,
        )
