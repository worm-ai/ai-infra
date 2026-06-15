# Codebase Map

- `.abh/` stores machine-readable ABH state.
- `docs/` stores human-readable mirrors and owner docs.
- `docs/architecture/attractors/` stores attractor documents.
- `docs/plans/`, `docs/audits/`, and `docs/memory/` store control records.
- `docs/Agent与Workflow区别-四层Agent协同编排引擎.md` is the seed architecture essay and evidence for the active attractor.

## Planned MVP Areas

- `pyproject.toml` will define the Python package, CLI entrypoint, and test dependencies.
- `src/ai_infra/` will contain the SDK and CLI implementation.
- `tests/` will contain behavior tests written before production code.
- `examples/` will contain runnable YAML workflow examples.
- `.ai-infra/` will contain local runtime state such as SQLite run records when the CLI is used.

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
