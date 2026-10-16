"""route_by_intent - 조건부 에지 함수 (FR-06). State 만 읽는 순수 함수."""
from src.config import get_settings
from src.state import TravelState

TASK_TO_NODE = {"rag": "rag_search", "weather": "weather_tool", "exchange": "exchange_tool",
                "plan": "plan_itinerary"}


def route_by_intent(state: TravelState) -> str:
    """우선순위: clarify > step 가드 > 큐의 첫 유효 task > generate_answer."""
    if state.get("needs_clarification"):
        return "clarify"
    if state.get("step_count", 0) >= get_settings().max_steps:
        return "generate_answer"
    for task in state.get("pending_intents", []):
        if task in TASK_TO_NODE:
            return TASK_TO_NODE[task]
    return "generate_answer"
