# Project Context

`ai-infra` is a Python Agentic Infra project. It uses Attractor Before Harness to keep AI-assisted work evidence-first and convergent.

The current active attractor is `docs/architecture/attractors/industrial-agent-orchestration.md`. The project should converge toward a local CLI + SDK orchestration kernel for industrial Agent collaboration, with DAG Workflow as the production-first path and ReAct, PlanExec, and Super-Agent as progressively higher layers.

## Operating Model

- Start from the active attractor.
- Create or update an ABH plan before implementation.
- Write tests before production code for new behavior.
- Verify with recorded commands.
- Close only after independent audit.

## Stable Commitments

- AI Infra is attractor-first, evidence-first, and local-first.
- Plans bind to the active attractor before running.
- Independent audit remains the closure decision layer.
- DAG Workflow is the MVP production axis; higher Agent layers must not weaken workflow observability, failure handling, or governance.

## Allowed Variation

- Current-stage wording may advance as plans close.
- Agent interfaces may expand if command contracts stay explicit.
- MCP, A2A, API, UI, and distributed runtime support may be introduced after the local CLI + SDK kernel proves the core model.

## Drift / Leakage Signals

- AI Infra is described as a demo-only Agent toy instead of an industrial orchestration kernel.
- Work bypasses plan, verification, or independent audit.
- Super-Agent or PlanExec features are prioritized before the DAG Workflow runner is executable, observable, and verified.

## Correction Path

- Update this file when project scope, stage, or operating model changes.
- Route scope expansions through roadmap materialization and audit.
