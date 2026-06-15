from ai_infra.layers import DagWorkflow, PlanExecAgent, ReActAgent, SuperAgent


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
