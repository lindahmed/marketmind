from collections.abc import Mapping
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.intelligence.contracts import Agent, AgentName, AgentState

ANALYSIS_STAGES = ("data_intelligence", "investigation", "growth_strategy", "experimentation")


class GrowthExperimentState(TypedDict, total=False):
    context: Any
    investigation: Any
    recommendation: Any
    approval: Any
    approval_verified: bool
    design_request: Any
    overview: dict
    strategy_output: dict
    experiment_design: dict


def build_analysis_graph(agents: Mapping[AgentName, Agent]):
    """Generic sequential agent graph; business strategy uses the gated graph below."""
    missing = set(ANALYSIS_STAGES) - agents.keys()
    if missing:
        raise ValueError(f"Missing agents: {', '.join(sorted(missing))}")
    graph = StateGraph(AgentState)
    previous = START
    for name in ANALYSIS_STAGES:
        graph.add_node(name, agents[name])
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    return graph.compile()


def build_growth_experiment_graph(investigation_agent, strategy_agent, design_agent):
    """Connect saved investigation evidence to shared strategy and design agents.

    With no design request, this graph only produces recommendations. Design
    runs cross a separate persisted-owner-approval gate before calling the
    deterministic design agent. The graph never executes an experiment.
    """
    graph = StateGraph(GrowthExperimentState)

    def validate_investigation(state):
        context, run = state["context"], state["investigation"]
        investigation_agent.require_workspace_run(context, run)
        return {}

    def strategy(state):
        context, run = state["context"], state["investigation"]
        if state.get("design_request") is None:
            return {"strategy_output": strategy_agent.recommend(context, run)}
        strategy_agent.validate_saved_recommendation(context, run, state["recommendation"])
        return {}

    def route_after_strategy(state):
        return "human_approval" if state.get("design_request") is not None else END

    def persisted_owner_approval(state):
        approval = state.get("approval")
        recommendation = state["recommendation"]
        if (not state.get("approval_verified") or approval is None
                or approval.workspace_id != state["context"].workspace_id
                or approval.recommendation_id != recommendation.id
                or approval.recommendation_version != recommendation.version
                or recommendation.status != "approved"):
            raise PermissionError("The exact recommendation version requires persisted owner approval")
        return {}

    def design(state):
        return {"experiment_design": design_agent.design(
            state["context"], state["recommendation"], state["approval"],
            state["overview"], state["design_request"],
        )}

    graph.add_node("investigation", validate_investigation)
    graph.add_node("growth_strategy", strategy)
    graph.add_node("human_approval", persisted_owner_approval)
    graph.add_node("experimentation", design)
    graph.add_edge(START, "investigation")
    graph.add_edge("investigation", "growth_strategy")
    graph.add_conditional_edges("growth_strategy", route_after_strategy,
                                {"human_approval": "human_approval", END: END})
    graph.add_edge("human_approval", "experimentation")
    graph.add_edge("experimentation", END)
    return graph.compile()
