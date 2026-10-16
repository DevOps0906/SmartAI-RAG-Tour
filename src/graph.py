"""StateGraph 를 직접 조립한다. 고수준 prebuilt 에이전트 API 는 쓰지 않는다. (NFR-01)

사용 API: StateGraph, add_node, add_edge, add_conditional_edges 만.
"""
from langgraph.graph import END, START, StateGraph

from src.nodes.analyze import analyze_input
from src.nodes.clarify import clarify
from src.nodes.exchange_node import exchange_tool
from src.nodes.plan_node import plan_itinerary
from src.nodes.rag_node import rag_search
from src.nodes.respond import generate_answer
from src.nodes.router import route_by_intent
from src.nodes.weather_node import weather_tool
from src.state import TravelState

ROUTE_MAP = {
    "rag_search": "rag_search",
    "weather_tool": "weather_tool",
    "exchange_tool": "exchange_tool",
    "plan_itinerary": "plan_itinerary",
    "clarify": "clarify",
    "generate_answer": "generate_answer",
}


def build_graph(checkpointer=None):
    g = StateGraph(TravelState)

    # 노드
    g.add_node("analyze_input", analyze_input)
    g.add_node("rag_search", rag_search)
    g.add_node("weather_tool", weather_tool)
    g.add_node("exchange_tool", exchange_tool)
    g.add_node("plan_itinerary", plan_itinerary)
    g.add_node("clarify", clarify)
    g.add_node("generate_answer", generate_answer)

    # 일반 에지
    g.add_edge(START, "analyze_input")
    g.add_edge("clarify", END)
    g.add_edge("generate_answer", END)

    # 조건부 에지: 분석 직후 및 모든 작업 노드 직후 동일 라우터로 합류
    for src in ("analyze_input", "rag_search", "weather_tool", "exchange_tool", "plan_itinerary"):
        g.add_conditional_edges(src, route_by_intent, ROUTE_MAP)

    return g.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    # 그래프 도식을 mermaid 텍스트로 출력 (문서/발표용)
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(build_graph().get_graph().draw_mermaid())
