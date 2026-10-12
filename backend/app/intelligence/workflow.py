from collections.abc import Mapping

from langgraph.graph import END, START, StateGraph

from app.intelligence.contracts import Agent, AgentName, AgentState

ANALYSIS_STAGES = ("data_intelligence", "investigation", "growth_strategy", "experimentation")


def build_analysis_graph(agents: Mapping[AgentName, Agent]):
    """Inject shared agents; each run carries one tenant's verified context.

    This graph stops at experiment design. Execution and evaluation are separate
    approved jobs, to be wired when the approval persistence milestone ships.
    """
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
