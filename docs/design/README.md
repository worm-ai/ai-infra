# Design

Application behavior, workflows, and user-facing design notes live here when they need to outlive one plan.

Use this layer for how the product experience should behave. Keep technical structure in `docs/architecture/`.

## MVP Design Direction

The MVP uses Python with a LangGraph-first execution strategy. YAML files declare workflows, agents, tools, nodes, edges, retry/timeout policy, and validation checks. A SQLite run store captures durable local evidence for CLI inspection and future API/UI layers.

The design should prefer small, testable modules:

- configuration loading and schema validation;
- workflow compilation;
- runtime execution;
- run/event persistence;
- CLI adapters;
- SDK facade.

## Stable Commitments

- YAML defines intended workflow structure.
- SQLite records observed runtime evidence.
- CLI and SDK share the same core implementation.
- LangGraph is the preferred execution backend, but project-owned domain models should prevent the public API from becoming a thin LangGraph script.
