from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-store-reliability-") as temp:
        temp_root = Path(temp)
        state_dir = temp_root / "state"

        missing_state = _run("store-health", state_dir=temp_root / "missing-state")
        missing_state_payload = _assert_ok(missing_state, "missing state health")
        _assert_health_status(missing_state_payload, "missing_state_dir")

        state_dir.mkdir()
        missing_database = _run("store-health", state_dir=state_dir)
        missing_database_payload = _assert_ok(missing_database, "missing database health")
        _assert_health_status(missing_database_payload, "missing_database")
        if (state_dir / "runs.sqlite").exists():
            raise AssertionError("store-health created a missing database")

        first = _run(
            "run",
            "examples/hello_workflow.yaml",
            "--input-file",
            "examples/hello_input.json",
            state_dir=state_dir,
        )
        first_payload = _assert_ok(first, "workflow run")
        run_id = first_payload["run"]["run_id"]

        verify = _run("verify", run_id, state_dir=state_dir)
        _assert_ok(verify, "run verification")

        healthy = _run("store-health", state_dir=state_dir)
        healthy_payload = _assert_ok(healthy, "healthy store")
        _assert_health_status(healthy_payload, "healthy")
        if healthy_payload["health"]["tables"]["runs"]["rows"] != 1:
            raise AssertionError(f"unexpected healthy row counts: {healthy_payload!r}")

        locked_payload = _locked_health_payload(state_dir)
        _assert_health_status(locked_payload, "database_locked")

        backup_path = temp_root / "backups" / "runs.sqlite"
        backup = _run("store-backup", "--output", str(backup_path), state_dir=state_dir)
        backup_payload = _assert_ok(backup, "store backup")
        if backup_payload["backup"]["status"] != "backed_up":
            raise AssertionError(f"backup did not pass: {backup_payload!r}")

        preflight = _run(
            "store-restore-preflight",
            str(backup_path),
            "--restore-state-dir",
            str(temp_root / "restore"),
            state_dir=state_dir,
        )
        preflight_payload = _assert_ok(preflight, "restore preflight")
        if preflight_payload["restore_preflight"]["status"] != "restore_preflight_passed":
            raise AssertionError(f"restore preflight did not pass: {preflight_payload!r}")
        if (temp_root / "restore").exists():
            raise AssertionError("restore preflight created the restore target")

        target_conflict = _run(
            "store-backup",
            "--output",
            str(state_dir / "runs.sqlite"),
            state_dir=state_dir,
        )
        target_conflict_payload = _assert_failed(target_conflict, "source target backup conflict")
        if target_conflict_payload["backup"]["status"] != "backup_target_conflict":
            raise AssertionError(f"source target backup conflict was not rejected: {target_conflict_payload!r}")
        post_conflict_health = _run("store-health", state_dir=state_dir)
        _assert_health_status(_assert_ok(post_conflict_health, "post conflict health"), "healthy")

        drift_state = temp_root / "schema-drift"
        drift_state.mkdir()
        _write_schema_drift_database(drift_state / "runs.sqlite")
        drift = _run("store-health", state_dir=drift_state)
        drift_payload = _assert_ok(drift, "schema drift health")
        _assert_health_status(drift_payload, "schema_drift")

        corrupt_state = temp_root / "corrupt"
        corrupt_state.mkdir()
        (corrupt_state / "runs.sqlite").write_bytes(b"not sqlite")
        corrupt = _run("store-health", state_dir=corrupt_state)
        corrupt_payload = _assert_ok(corrupt, "corrupt health")
        _assert_health_status(corrupt_payload, "database_unreadable")

        bad_backup = temp_root / "bad-backup.sqlite"
        bad_backup.write_bytes(b"not sqlite")
        failed_preflight = _run(
            "store-restore-preflight",
            str(bad_backup),
            "--restore-state-dir",
            str(temp_root / "bad-restore"),
            state_dir=state_dir,
        )
        failed_preflight_payload = _assert_failed(failed_preflight, "bad restore preflight")
        if failed_preflight_payload["restore_preflight"]["status"] != "restore_preflight_failed":
            raise AssertionError(f"bad restore preflight did not fail as expected: {failed_preflight_payload!r}")

        print(
            json.dumps(
                {
                    "ok": True,
                    "run_id": run_id,
                    "backup_path": str(backup_path),
                    "covered_statuses": [
                        "missing_state_dir",
                        "missing_database",
                        "healthy",
                        "database_locked",
                        "schema_drift",
                        "database_unreadable",
                        "restore_preflight_failed",
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0


def _write_schema_drift_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute("create table runs (run_id text primary key, workflow_id text not null)")
            connection.execute("create table node_events (id integer primary key autoincrement)")
            connection.execute("create table verifications (id integer primary key autoincrement)")
            connection.execute("create table node_execution_reservations (id integer primary key autoincrement)")


def _locked_health_payload(state_dir: Path) -> dict:
    script = (
        "import os, sqlite3, sys, time; "
        "connection = sqlite3.connect(sys.argv[1]); "
        "connection.execute('begin exclusive'); "
        "Path = __import__('pathlib').Path; "
        "Path(sys.argv[2]).write_text('locked', encoding='utf-8'); "
        "time.sleep(5); "
        "connection.rollback(); "
        "connection.close()"
    )
    ready_path = state_dir / "lock-ready.txt"
    locker = subprocess.Popen(
        [sys.executable, "-c", script, str(state_dir / "runs.sqlite"), str(ready_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_file(ready_path)
        locked = _run("store-health", state_dir=state_dir)
        return _assert_ok(locked, "locked health")
    finally:
        locker.terminate()
        try:
            locker.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            locker.kill()
            locker.communicate(timeout=5)


def _wait_for_file(path: Path) -> None:
    for _ in range(100):
        if path.exists():
            return
        if os.name == "nt":
            import time

            time.sleep(0.05)
        else:
            import time

            time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _run(*args: str, state_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_ok(result: subprocess.CompletedProcess[str], label: str) -> dict:
    payload = _json_payload(result, label)
    if result.returncode != 0 or not payload.get("ok"):
        raise AssertionError(
            f"{label} failed with code {result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return payload


def _assert_failed(result: subprocess.CompletedProcess[str], label: str) -> dict:
    payload = _json_payload(result, label)
    if result.returncode == 0 or payload.get("ok"):
        raise AssertionError(
            f"{label} unexpectedly passed with code {result.returncode}: stdout={result.stdout!r}"
        )
    return payload


def _json_payload(result: subprocess.CompletedProcess[str], label: str) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{label} did not return JSON: {result.stdout!r}") from exc


def _assert_health_status(payload: dict, status: str) -> None:
    actual = payload["health"]["status"]
    if actual != status:
        raise AssertionError(f"expected health status {status!r}, got {actual!r}: {payload!r}")


if __name__ == "__main__":
    raise SystemExit(main())
