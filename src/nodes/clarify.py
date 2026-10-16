"""clarify - 누락 정보 되묻기 (FR-08) + 미지원 여행지 안내 (FR-09). 질문을 답변으로 쓰고 END."""
from langchain_core.messages import AIMessage

from src.destinations import unsupported_message
from src.state import TravelState


def clarify(state: TravelState) -> dict:
    if state.get("clarify_reason") == "unsupported_destination" and state.get("unsupported_destination"):
        q = unsupported_message(state["unsupported_destination"])
    else:
        q = state.get("clarify_question") or "조금 더 자세히 알려주실 수 있을까요?"
    return {"final_answer": q, "messages": [AIMessage(content=q)], "needs_clarification": False}
