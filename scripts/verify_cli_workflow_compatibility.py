from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ai-infra-workflow-compatibility-") as temp:
        temp_root = Path(temp)
        state_dir = temp_root / "state"
        bundle_dir = temp_root / "bundles"
        input_path = temp_root / "input.json"
        input_path.write_text(json.dumps({"topic": "ABH"}), encoding="utf-8")

        supported = _write_workflow(
            temp_root / "supported.yaml",
            """
id: compatibility-supported
schema_version: "1"
features:
  - template_nodes
  - edge_list
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
validations:
  - type: run_status
    equals: completed
""",
        )
        deprecated = _write_workflow(
            temp_root / "deprecated.yaml",
            """
id: compatibility-deprecated
schema_version: "1"
features:
  - legacy_llm_node
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
validations:
  - type: run_status
    equals: completed
""",
        )
        unsupported = _write_workflow(
            temp_root / "unsupported.yaml",
            """
id: compatibility-unsupported
schema_version: "1"
features:
  - distributed_a2a
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
""",
        )
        future = _write_workflow(
            temp_root / "future.yaml",
            """
id: compatibility-future
schema_version: "99"
entrypoint: draft
nodes:
  draft:
    type: template
    template: "Draft {topic}"
""",
        )

        supported_validate = _run_cli(state_dir, "validate", str(supported))
        _assert(
            supported_validate["compatibility"]["status"] == "supported",
            "supported workflow validate should expose supported compatibility",
        )
        _assert(
            supported_validate["compatibility"]["schema_version"]["declared"] == "1",
            "supported workflow validate should expose schema version",
        )

        deprecated_validate = _run_cli(state_dir, "validate", str(deprecated))
        _assert(
            deprecated_validate["compatibility"]["status"] == "deprecated",
            "deprecated workflow validate should warn without failing",
        )
        _assert(
            deprecated_validate["compatibility"]["diagnostics"][0]["category"] == "deprecated_feature",
            "deprecated workflow validate should include migration diagnostic",
        )

        unsupported_validate = _run_cli(
            state_dir,
            "validate",
            str(unsupported),
            expected_codes=(2,),
            allow_failure=True,
        )
        _assert(
            unsupported_validate["compatibility"]["failure_category"] == "unsupported_feature",
            "unsupported workflow should fail with deterministic category",
        )

        future_validate = _run_cli(
            state_dir,
            "validate",
            str(future),
            expected_codes=(2,),
            allow_failure=True,
        )
        _assert(
            future_validate["compatibility"]["failure_category"] == "future_schema",
            "future workflow should fail with deterministic category",
        )

        run = _run_cli(state_dir, "run", str(deprecated), "--input-file", str(input_path))["run"]
        run_id = str(run["run_id"])
        _assert(run["status"] == "completed", "deprecated compatibility should not fail execution")

        report = _run_cli(state_dir, "report", run_id)["report"]
        _assert(
            report["compatibility"]["status"] == "deprecated",
            "report should carry accepted compatibility evidence",
        )

        verification = _run_cli(state_dir, "verify", run_id)["verification"]
        _assert(verification["status"] == "passed", "deprecated compatibility should not fail verification")
        _assert(
            verification["compatibility"]["status"] == "deprecated",
            "verification should carry accepted compatibility evidence",
        )

        bundle = _run_cli(state_dir, "export-bundle", run_id, "--output-dir", str(bundle_dir))["bundle"]
        with zipfile.ZipFile(str(bundle["path"])) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            bundle_report = json.loads(archive.read("report.json"))
        _assert(
            manifest["compatibility_summary"]["status"] == "deprecated",
            "bundle manifest should carry compatibility summary",
        )
        _assert(
            bundle_report["compatibility"]["status"] == "deprecated",
            "bundle report should carry compatibility evidence",
        )

        payload = {
            "ok": True,
            "run_id": run_id,
            "compatibility": {
                "supported": supported_validate["compatibility"]["status"],
                "deprecated": deprecated_validate["compatibility"]["status"],
                "unsupported": unsupported_validate["compatibility"]["failure_category"],
                "future": future_validate["compatibility"]["failure_category"],
                "report": report["compatibility"]["status"],
                "verify": verification["compatibility"]["status"],
                "bundle": manifest["compatibility_summary"]["status"],
            },
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0


def _write_workflow(path: Path, content: str) -> Path:
    path.write_text(content.strip(), encoding="utf-8")
    return path


def _run_cli(
    state_dir: Path,
    *args: str,
    expected_codes: tuple[int, ...] = (0,),
    allow_failure: bool = False,
) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_infra.cli",
            "--state-dir",
            str(state_dir),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode not in expected_codes:
        raise RuntimeError(
            f"command failed with code {result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    payload = json.loads(result.stdout)
    if payload.get("ok") is False and not allow_failure:
        raise RuntimeError(result.stdout)
    return payload


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
