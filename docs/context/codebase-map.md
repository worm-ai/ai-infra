# Codebase Map

- `.abh/` stores machine-readable ABH state.
- `docs/` stores human-readable mirrors and owner docs.
- `docs/architecture/attractors/` stores attractor documents.
- `docs/plans/`, `docs/audits/`, and `docs/memory/` store control records.
- `docs/Agent与Workflow区别-四层Agent协同编排引擎.md` is the seed architecture essay and evidence for the active attractor.

## MVP Code Areas

- `pyproject.toml` defines the Python package, `ai-infra` CLI entrypoint, runtime dependencies, and test dependencies.
- `src/ai_infra/config.py` loads and validates YAML workflow definitions.
- `src/ai_infra/langgraph_runner.py` compiles workflow definitions into a LangGraph-backed DAG runner.
- `src/ai_infra/runtime.py` exposes SDK runtime functions for executing, inspecting, and verifying runs.
- `src/ai_infra/store.py` persists runs, node events, and verification evidence in SQLite.
- `src/ai_infra/cli.py` adapts the shared SDK/runtime to the local CLI.
- `src/ai_infra/layers.py` preserves ReAct, DAG Workflow, PlanExec, and Super-Agent layer boundaries.
- `tests/` contains behavior tests for workflow config, LangGraph execution, SQLite persistence, CLI lifecycle, and layer skeletons.
- `examples/` contains runnable YAML workflow examples and JSON input.
- `.ai-infra/` contains local runtime state such as SQLite run records when the CLI is used.

## Stable Commitments

- `.abh/` stores machine-readable ABH state.
- `docs/` stores Markdown mirrors and owner docs.
- The active attractor owns the architecture direction for code areas introduced by future plans.

## Allowed Variation

- New modules and tests may be added by audited plans.
- Module descriptions may change as responsibilities move.

## Drift / Leakage Signals

- CLI and MCP behavior diverge from shared command contracts.
- Seeded docs drift from current owner-doc guidance.

## Correction Path

- Update this map when module ownership changes.
- Update seeded and current owner docs in the same audited slice.
