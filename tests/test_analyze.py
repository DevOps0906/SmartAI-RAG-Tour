"""T-02 ~ T-06 analyze_input (LLM_PROVIDER=none -> 규칙 기반)."""
import pytest

from src.nodes.analyze import analyze_input, build_pending_intents


@pytest.mark.parametrize("text,intent,tasks", [
    ("파리 맛집 추천", "recommend", ["rag"]),
    ("방콕 날씨 어때?", "weather", ["weather"]),
    ("파리 100만원이면 몇 유로야?", "exchange", ["exchange"]),
    ("제주 2박3일 일정 짜줘", "itinerary", ["rag", "weather"]),
    ("오늘 점심 뭐 먹지", "unknown", []),
])
def test_single_intents(text, intent, tasks):
    out = analyze_input({"user_input": text})
    assert out["intent"] == intent
    assert out["pending_intents"] == tasks
    assert out["step_count"] == 0


def test_multi_intent_queue():
    out = analyze_input({"user_input": "도쿄 날씨랑 환율 알려주고 일정도 짜줘"})
    assert out["intent"] == "multi"
    assert out["pending_intents"] == ["rag", "weather", "exchange"]
    assert out["entities"]["destination"] == "tokyo"


def test_multi_with_nights_and_amount():
    out = analyze_input({"user_input": "도쿄 3박4일 일정이랑 날씨, 50만원 환전 얼마야?"})
    e = out["entities"]
    assert out["pending_intents"] == ["rag", "weather", "exchange"]
    assert e["days"] == 4 and e["amount"] == 500_000 and e["amount_currency"] == "KRW"  # '3박'의 3 을 금액으로 오인 금지


def test_missing_destination_requires_clarify():
    out = analyze_input({"user_input": "날씨 알려줘"})
    assert out["needs_clarification"] is True and "어느 여행지" in out["clarify_question"]


def test_vague_recommend_asks_preference():
    out = analyze_input({"user_input": "어디 갈까?"})
    assert out["needs_clarification"] is True and "취향" in out["clarify_question"]


def test_recommend_with_interest_does_not_clarify():
    out = analyze_input({"user_input": "여름에 휴양하기 좋은 곳 추천해줘"})
    assert out["needs_clarification"] is False
    assert out["pending_intents"] == ["rag"] and "휴양" in out["entities"]["interests"]


def test_amount_man_won():
    out = analyze_input({"user_input": "파리 100만원 환전하면 얼마야?"})
    assert out["entities"]["amount"] == 1_000_000 and out["entities"]["currency"] == "EUR"
    assert out["entities"]["amount_assumed"] is False


def test_amount_default_is_flagged():
    e = analyze_input({"user_input": "도쿄 환율 알려줘"})["entities"]
    assert e["amount"] == 1_000_000 and e["amount_assumed"] is True


def test_foreign_amount_and_currency_hint_destination():
    e = analyze_input({"user_input": "환율 100달러"})["entities"]
    assert e["amount"] == 100 and e["amount_currency"] == "USD" and e["destination"] == "newyork"


@pytest.mark.parametrize("text,key,ko,cur", [
    ("Tokyo 날씨", "tokyo", "도쿄", "JPY"), ("NYC 날씨", "newyork", "뉴욕", "USD"),
    ("제주도 날씨", "jeju", "제주", "KRW"), ("방콕 날씨", "bangkok", "방콕", "THB"),
])
def test_destination_aliases(text, key, ko, cur):
    e = analyze_input({"user_input": text})["entities"]
    assert (e["destination"], e["destination_ko"], e["currency"]) == (key, ko, cur)


def test_days_and_month():
    e = analyze_input({"user_input": "7월에 방콕 2박 3일 일정"})["entities"]
    assert e["days"] == 3 and e["travel_date"].endswith("-07-15")


def test_explicit_date():
    assert analyze_input({"user_input": "2026-12-24 파리 날씨"})["entities"]["travel_date"] == "2026-12-24"


def test_llm_unavailable_falls_back_and_records_error():
    out = analyze_input({"user_input": "방콕 날씨"})
    assert any("규칙 기반" in e and "LLMUnavailable" in e for e in out["errors"])


def test_previous_destination_reused_only_when_needed():
    prev = {"destination": "paris", "destination_ko": "파리", "currency": "EUR"}
    assert analyze_input({"user_input": "환율은?", "entities": prev})["entities"]["destination"] == "paris"
    # 목적지가 필요 없는 새 추천 질의는 이전 도시로 필터링하지 않는다
    assert analyze_input({"user_input": "휴양 맛집 추천", "entities": prev})["entities"]["destination"] is None


def test_build_tasks():
    assert build_pending_intents("itinerary", []) == ["rag", "weather"]
    assert build_pending_intents("multi", ["exchange", "weather"]) == ["weather", "exchange"]
    assert build_pending_intents("unknown", []) == []
