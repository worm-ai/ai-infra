from ai_infra.layers import DagWorkflow, PlanExecAgent, ReActAgent, SuperAgent
from ai_infra import DagWorkflow as SdkDagWorkflow
from ai_infra import PlanExecAgent as SdkPlanExecAgent
from ai_infra import ReActAgent as SdkReActAgent
from ai_infra import SuperAgent as SdkSuperAgent


def test_layer_skeletons_expose_progressive_order():
    assert ReActAgent.layer == "react"
    assert DagWorkflow.layer == "dag_workflow"
    assert PlanExecAgent.layer == "planexec"
    assert SuperAgent.layer == "super_agent"

    assert [layer.layer for layer in [ReActAgent(), DagWorkflow(), PlanExecAgent(), SuperAgent()]] == [
        "react",
        "dag_workflow",
        "planexec",
        "super_agent",
    ]


def test_layer_skeletons_are_exposed_from_sdk_root():
    assert SdkReActAgent is ReActAgent
    assert SdkDagWorkflow is DagWorkflow
    assert SdkPlanExecAgent is PlanExecAgent
    assert SdkSuperAgent is SuperAgent
