"""T-07 라우터 우선순위: clarify > step 가드 > 큐 > 응답."""
from src.nodes.router import route_by_intent


def test_clarify_has_priority():
    assert route_by_intent({"needs_clarification": True, "pending_intents": ["rag"]}) == "clarify"


def test_queue_order():
    assert route_by_intent({"pending_intents": ["weather", "exchange"]}) == "weather_tool"
    assert route_by_intent({"pending_intents": ["rag"]}) == "rag_search"
    assert route_by_intent({"pending_intents": ["exchange"]}) == "exchange_tool"


def test_empty_queue_goes_to_response():
    assert route_by_intent({"pending_intents": []}) == "generate_answer"
    assert route_by_intent({}) == "generate_answer"


def test_step_guard():
    assert route_by_intent({"pending_intents": ["rag"], "step_count": 99}) == "generate_answer"


def test_clarify_beats_step_guard():
    assert route_by_intent({"needs_clarification": True, "step_count": 99}) == "clarify"


def test_unknown_task_skipped():
    assert route_by_intent({"pending_intents": ["bogus", "weather"]}) == "weather_tool"
