from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-maintenance-") as temp:
        temp_root = Path(temp)
        state_dir = temp_root / "state"

        first = _run(
            "run",
            "examples/hello_workflow.yaml",
            "--input-file",
            "examples/hello_input.json",
            state_dir=state_dir,
        )
        first_payload = _assert_ok(first, "first run")
        first_run_id = first_payload["run"]["run_id"]

        second = _run(
            "run",
            "examples/tool_failure_workflow.yaml",
            "--input-file",
            "examples/tool_input.json",
            state_dir=state_dir,
        )
        second_payload = _assert_ok(second, "second run")
        second_run_id = second_payload["run"]["run_id"]

        orphan = state_dir / "artifacts" / "run-orphan" / "node" / "artifact" / "note.txt"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text("orphan evidence", encoding="utf-8")

        health = _run("store-health", state_dir=state_dir)
        health_payload = _assert_ok(health, "store-health")
        if health_payload["health"]["tables"]["runs"]["rows"] != 2:
            raise AssertionError(f"unexpected health payload: {health_payload!r}")

        failed_runs = _run("runs", "--status", "failed", state_dir=state_dir)
        failed_payload = _assert_ok(failed_runs, "runs --status failed")
        if [run["run_id"] for run in failed_payload["runs"]] != [second_run_id]:
            raise AssertionError(f"unexpected failed run list: {failed_payload!r}")

        dry_run = _run("cleanup", "--keep-last", "1", state_dir=state_dir)
        dry_payload = _assert_ok(dry_run, "cleanup dry-run")
        cleanup = dry_payload["cleanup"]
        if cleanup["mode"] != "dry_run":
            raise AssertionError(f"cleanup was not dry-run: {cleanup!r}")
        if [run["run_id"] for run in cleanup["delete_runs"]] != [first_run_id]:
            raise AssertionError(f"unexpected dry-run delete set: {cleanup!r}")
        if cleanup["orphan_artifacts"][0]["run_id"] != "run-orphan":
            raise AssertionError(f"orphan was not reported: {cleanup!r}")
        if not orphan.exists():
            raise AssertionError("dry-run deleted orphan artifact")

        apply = _run("cleanup", "--keep-last", "1", "--apply", state_dir=state_dir)
        apply_payload = _assert_ok(apply, "cleanup apply")
        applied = apply_payload["cleanup"]
        if applied["mode"] != "apply":
            raise AssertionError(f"cleanup was not apply: {applied!r}")
        if [run["run_id"] for run in applied["deleted_runs"]] != [first_run_id]:
            raise AssertionError(f"unexpected applied delete set: {applied!r}")

        deleted_status = _run("status", first_run_id, state_dir=state_dir)
        if deleted_status.returncode == 0:
            raise AssertionError("deleted run is still readable")
        kept_status = _run("status", second_run_id, state_dir=state_dir)
        _assert_ok(kept_status, "kept run status")
        if not orphan.exists():
            raise AssertionError("apply deleted orphan artifact without explicit orphan cleanup")

        print(
            json.dumps(
                {
                    "ok": True,
                    "kept_run_id": second_run_id,
                    "deleted_run_id": first_run_id,
                    "orphan_reported": True,
                },
                ensure_ascii=False,
            )
        )
        return 0


def _run(*args: str, state_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ai_infra.cli", "--state-dir", str(state_dir), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_ok(result: subprocess.CompletedProcess[str], label: str) -> dict:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{label} did not return JSON: {result.stdout!r}") from exc
    if result.returncode != 0 or not payload.get("ok"):
        raise AssertionError(
            f"{label} failed with code {result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return payload


if __name__ == "__main__":
    raise SystemExit(main())

