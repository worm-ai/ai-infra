from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-artifacts-") as temp:
        temp_root = Path(temp)
        state_dir = temp_root / "state"
        artifact_path = temp_root / "artifacts" / "note.txt"
        input_path = temp_root / "artifact_input.json"
        input_path.write_text(
            json.dumps({"topic": "ABH", "artifact_path": artifact_path.as_posix()}),
            encoding="utf-8",
        )
        bundles_dir = temp_root / "bundles"

        validate = _run("validate", "examples/artifact_workflow.yaml", state_dir=state_dir)
        _assert_ok(validate, "validate")

        run = _run(
            "run",
            "examples/artifact_workflow.yaml",
            "--input-file",
            str(input_path),
            state_dir=state_dir,
        )
        run_payload = _assert_ok(run, "run")
        run_id = run_payload["run"]["run_id"]
        if run_payload["run"]["status"] != "completed":
            raise AssertionError(f"expected completed run, got {run_payload['run']['status']!r}")

        report = _run("report", run_id, state_dir=state_dir)
        report_payload = _assert_ok(report, "report")
        artifact_summary = report_payload["report"]["summary"].get("artifacts")
        if artifact_summary != {"declared": 1, "present": 1, "missing": 0}:
            raise AssertionError(f"unexpected artifact summary: {artifact_summary!r}")

        verify = _run("verify", run_id, state_dir=state_dir)
        verify_payload = _assert_ok(verify, "verify")
        checks = {check["type"]: check for check in verify_payload["verification"]["checks"]}
        if checks["node_artifact"]["status"] != "passed":
            raise AssertionError(f"artifact verification failed: {checks['node_artifact']!r}")

        export = _run("export-bundle", run_id, "--output-dir", str(bundles_dir), state_dir=state_dir)
        export_payload = _assert_ok(export, "export-bundle")
        bundle_path = Path(export_payload["bundle"]["path"])
        if not bundle_path.exists():
            raise AssertionError(f"bundle was not created: {bundle_path}")
        with zipfile.ZipFile(bundle_path) as archive:
            names = set(archive.namelist())
            expected = {
                "manifest.json",
                "report.json",
                "workflow_snapshot.yaml",
                "inputs.json",
                "events.json",
                "artifacts/write_note/note/note.txt",
            }
            missing = expected - names
            if missing:
                raise AssertionError(f"bundle missing files: {sorted(missing)}")

        print(json.dumps({"ok": True, "run_id": run_id, "bundle": str(bundle_path)}, ensure_ascii=False))
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
