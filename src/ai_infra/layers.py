from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReActAgent:
    layer = "react"


@dataclass(frozen=True)
class DagWorkflow:
    layer = "dag_workflow"


@dataclass(frozen=True)
class PlanExecAgent:
    layer = "planexec"


@dataclass(frozen=True)
class SuperAgent:
    layer = "super_agent"
