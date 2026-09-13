"""LangGraph definition for the agentic execution path.

The HTTP API currently calls the synchronous compatibility runner; this graph is the
production orchestration definition for workers that support LangGraph checkpoints.
"""
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from .agents import analyze, evaluate, plan

class WorkflowState(TypedDict, total=False):
    query: str
    user_id: str
    state: object

def build_workflow():
    graph=StateGraph(WorkflowState)
    def analyze_node(data):
        from .agents import AgentState
        return {"state": analyze(AgentState(query=data["query"], user_id=data["user_id"]))}
    def plan_node(data): return {"state": plan(data["state"])}
    graph.add_node("query_analyzer", analyze_node)
    graph.add_node("planner", plan_node)
    graph.add_edge(START,"query_analyzer")
    graph.add_edge("query_analyzer","planner")
    graph.add_edge("planner",END)
    return graph.compile()
