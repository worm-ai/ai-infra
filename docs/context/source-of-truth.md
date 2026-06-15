# Source of Truth

Repository files are the truth surface, but no single file answers every question.

## Precedence

- Active attractor: long-term convergence target.
- Plan: scope, non-goals, exit criteria, and validation checklist for one slice.
- Code and tests: current implementation behavior.
- Verification records: commands that actually ran.
- Audit records: completion judgment for closure.
- Roadmap queue: future intent before a plan is materialized.

## Stable Commitments

- Repository files are the truth surface.
- Authority is chosen by question type, not recency alone.
- Verification is evidence; independent audit is the closure judgment.

## Allowed Variation

- New artifact families may be added when ABH gains durable evidence types.
- Conflict rules may become more specific as records mature.

## Drift / Leakage Signals

- A workflow treats verification pass as completion.
- A future queue item receives a concrete plan id before materialization.

## Correction Path

- Classify disagreements by question type.
- Update the owner doc or executable artifact that owns the question.
