"""T-01 State 키/타입, messages 리듀서 누적."""
from typing import get_type_hints

from src.state import TravelState


def test_state_keys():
    hints = get_type_hints(TravelState, include_extras=True)
    for k in ("messages", "user_input", "intent", "entities", "pending_intents", "needs_clarification",
              "clarify_question", "step_count", "rag_docs", "weather", "exchange", "errors", "final_answer"):
        assert k in hints


def test_messages_accumulate_across_turns(run):
    st1, _ = run("방콕 날씨 알려줘", "acc")
    n1 = len(st1["messages"])
    st2, _ = run("파리 날씨 알려줘", "acc")
    assert n1 == 2                       # Human + AI
    assert len(st2["messages"]) == 4     # 누적
