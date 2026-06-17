from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-release-install-") as temp:
        temp_root = Path(temp)
        dist_dir = temp_root / "dist"
        venv_dir = temp_root / "venv"
        smoke_dir = temp_root / "smoke"
        state_dir = smoke_dir / "state"
        bundle_dir = smoke_dir / "bundles"
        smoke_dir.mkdir()

        _run([_uv(), "build", "--out-dir", str(dist_dir)], cwd=ROOT)
        wheel = _single_artifact(dist_dir, "*.whl")
        sdist = _single_artifact(dist_dir, "*.tar.gz")
        package_checks = _inspect_artifacts(wheel, sdist)

        _run([sys.executable, "-m", "venv", str(venv_dir)], cwd=ROOT)
        python = _venv_python(venv_dir)
        _run([str(python), "-m", "pip", "install", str(wheel)], cwd=smoke_dir)
        cli = _venv_script(venv_dir, "ai-infra")

        packaged_examples = _packaged_examples(python, smoke_dir)
        workflow = Path(str(packaged_examples["workflow"]))
        inputs = Path(str(packaged_examples["inputs"]))

        version_payload = _run_cli(cli, smoke_dir, state_dir, "--version")
        validate_payload = _run_cli(cli, smoke_dir, state_dir, "validate", str(workflow))
        run_payload = _run_cli(cli, smoke_dir, state_dir, "run", str(workflow), "--input-file", str(inputs))
        run_id = str(run_payload["run"]["run_id"])
        report_payload = _run_cli(cli, smoke_dir, state_dir, "report", run_id)
        verify_payload = _run_cli(cli, smoke_dir, state_dir, "verify", run_id)
        bundle_payload = _run_cli(cli, smoke_dir, state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))
        bundle_path = str(bundle_payload["bundle"]["path"])
        verify_bundle_payload = _run_cli(cli, smoke_dir, smoke_dir / "detached-state", "verify-bundle", bundle_path)
        sdk_payload = _run_sdk_import(python, smoke_dir)

        _assert(version_payload["package"] == "ai-infra", "version payload should identify package")
        _assert(validate_payload["ok"] is True, "installed validate should pass")
        _assert(
            validate_payload["compatibility"]["status"] == "supported",
            "installed validate should expose workflow compatibility",
        )
        _assert(run_payload["run"]["status"] == "completed", "installed run should complete")
        _assert(report_payload["report"]["status"] == "completed", "installed report should show completion")
        _assert(
            report_payload["report"]["compatibility"]["schema_version"]["declared"] == "1",
            "installed report should include compatibility evidence",
        )
        _assert(verify_payload["verification"]["status"] == "passed", "installed verify should pass")
        _assert(
            verify_payload["verification"]["compatibility"]["status"] == "supported",
            "installed verify should include compatibility evidence",
        )
        _assert(verify_bundle_payload["verification"]["status"] == "passed", "installed verify-bundle should pass")
        _assert(sdk_payload["version"] == version_payload["version"], "SDK version should match CLI version")
        _assert(sdk_payload["has_default_store"] is True, "SDK should export default_store")

        payload = {
            "ok": True,
            "artifacts": {
                "wheel": str(wheel),
                "sdist": str(sdist),
                "checks": package_checks,
            },
            "package": version_payload,
            "run_id": run_id,
            "commands": {
                "version": version_payload["version"],
                "validate": validate_payload["ok"],
                "compatibility": validate_payload["compatibility"]["status"],
                "run": run_payload["run"]["status"],
                "report": report_payload["report"]["status"],
                "verify": verify_payload["verification"]["status"],
                "export_bundle": bundle_path,
                "verify_bundle": verify_bundle_payload["verification"]["status"],
                "sdk_import": sdk_payload,
                "packaged_examples": packaged_examples,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0


def _run_cli(cli: Path, cwd: Path, state_dir: Path, *args: str) -> dict[str, Any]:
    result = _run([str(cli), "--state-dir", str(state_dir), *args], cwd=cwd)
    return _json_payload(result.stdout, args)


def _run_sdk_import(python: Path, cwd: Path) -> dict[str, Any]:
    script = (
        "import json, ai_infra; "
        "print(json.dumps({"
        "'version': ai_infra.__version__, "
        "'has_default_store': callable(ai_infra.default_store), "
        "'exports_load_workflow': 'load_workflow' in ai_infra.__all__"
        "}, sort_keys=True))"
    )
    result = _run([str(python), "-c", script], cwd=cwd)
    return _json_payload(result.stdout, ("sdk-import",))


def _packaged_examples(python: Path, cwd: Path) -> dict[str, Any]:
    script = (
        "import json; "
        "from importlib import resources; "
        "examples = resources.files('ai_infra').joinpath('examples'); "
        "workflow = examples.joinpath('release_smoke_workflow.yaml'); "
        "inputs = examples.joinpath('release_smoke_input.json'); "
        "print(json.dumps({"
        "'workflow': str(workflow), "
        "'inputs': str(inputs), "
        "'workflow_exists': workflow.is_file(), "
        "'inputs_exists': inputs.is_file()"
        "}, sort_keys=True))"
    )
    payload = _json_payload(_run([str(python), "-c", script], cwd=cwd).stdout, ("packaged-examples",))
    _assert(payload["workflow_exists"] is True, "installed package should include release smoke workflow")
    _assert(payload["inputs_exists"] is True, "installed package should include release smoke input")
    return payload


def _run(command: list[str], cwd: Path, *, attempts: int = 2) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        paths = [path for path in existing_pythonpath.split(os.pathsep) if Path(path).resolve() != (ROOT / "src")]
        if paths:
            env["PYTHONPATH"] = os.pathsep.join(paths)
        else:
            env.pop("PYTHONPATH", None)
    failures: list[subprocess.CompletedProcess[str]] = []
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return result
        failures.append(result)
        if attempt < attempts:
            time.sleep(0.5)
    result = failures[-1]
    if result.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(command)}\n"
            f"attempts={attempts}\n"
            f"cwd={cwd}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    raise AssertionError("unreachable command execution state")


def _json_payload(stdout: str, label: tuple[str, ...]) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{' '.join(label)} did not emit JSON: {stdout!r}") from exc
    if payload.get("ok") is False:
        raise AssertionError(f"{' '.join(label)} returned ok=false: {payload!r}")
    return payload


def _single_artifact(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    _assert(len(matches) == 1, f"expected exactly one {pattern} artifact in {dist_dir}, found {matches}")
    return matches[0]


def _inspect_artifacts(wheel: Path, sdist: Path) -> dict[str, Any]:
    with zipfile.ZipFile(wheel) as wheel_archive:
        wheel_names = set(wheel_archive.namelist())
        entry_points_name = next(name for name in wheel_names if name.endswith(".dist-info/entry_points.txt"))
        metadata_name = next(name for name in wheel_names if name.endswith(".dist-info/METADATA"))
        entry_points = wheel_archive.read(entry_points_name).decode("utf-8")
        metadata = wheel_archive.read(metadata_name).decode("utf-8")

    _assert("ai_infra/cli.py" in wheel_names, "wheel should include CLI module")
    _assert("ai_infra/examples/release_smoke_workflow.yaml" in wheel_names, "wheel should include smoke workflow")
    _assert("ai_infra/examples/release_smoke_input.json" in wheel_names, "wheel should include smoke input")
    _assert("ai-infra = ai_infra.cli:main" in entry_points, "wheel should expose ai-infra entrypoint")
    _assert("Description-Content-Type: text/markdown" in metadata, "wheel should include README metadata")

    with tarfile.open(sdist) as sdist_archive:
        sdist_names = set(sdist_archive.getnames())

    _assert(any(name.endswith("/README.md") for name in sdist_names), "sdist should include README.md")
    _assert(any(name.endswith("/pyproject.toml") for name in sdist_names), "sdist should include pyproject.toml")
    _assert(
        any(name.endswith("/src/ai_infra/examples/release_smoke_workflow.yaml") for name in sdist_names),
        "sdist should include smoke workflow",
    )
    _assert(
        any(name.endswith("/src/ai_infra/examples/release_smoke_input.json") for name in sdist_names),
        "sdist should include smoke input",
    )
    return {
        "wheel_cli_module": True,
        "wheel_smoke_examples": True,
        "wheel_entrypoint": True,
        "wheel_readme_metadata": True,
        "sdist_readme": True,
        "sdist_pyproject": True,
        "sdist_smoke_examples": True,
    }


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_script(venv_dir: Path, name: str) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def _uv() -> str:
    executable = os.environ.get("UV")
    if executable:
        return executable
    return "uv"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
