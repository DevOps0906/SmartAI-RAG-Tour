"""T-16 ~ T-21 통합 + 14.4 E2E 시나리오 S1~S10 (LLM none, 키/네트워크 불필요)."""
from types import SimpleNamespace

import httpx

from src.config import get_settings

A, R, W, X, C, F = ("analyze_input", "rag_search", "weather_tool", "exchange_tool", "clarify", "generate_answer")


def test_t16_single_weather(run):
    st, path = run("방콕 날씨 어때?")
    assert path == [A, W, F]
    assert st["weather"]["city"] == "bangkok" and st["weather"]["source"] == "mock"
    assert "방콕" in st["final_answer"] and "참고용" in st["final_answer"]


def test_t17_multi_flow(run):
    st, path = run("도쿄 날씨랑 환율 알려주고 일정도 짜줘")
    assert path == [A, R, W, X, F]
    assert st["pending_intents"] == []
    assert st["rag_docs"] and st["weather"]["ok"] and st["exchange"]["ok"]
    assert "도쿄" in st["final_answer"]


def test_t18_clarify_then_followup(run):
    st, path = run("날씨 알려줘")
    assert path == [A, C] and "어느 여행지" in st["final_answer"] and st["weather"] is None
    st, path = run("방콕 날씨 알려줘")
    assert st["weather"]["city"] == "bangkok"


def test_t19_followup_reuses_destination(run):
    run("파리 날씨 알려줘")
    st, path = run("환율은?")
    assert path == [A, X, F] and st["exchange"]["target"] == "EUR"


def test_t20_rag_failure_isolated(run, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("index corrupted")
    monkeypatch.setattr("src.nodes.rag_node.search_guides", boom)
    st, path = run("도쿄 날씨랑 환율 알려주고 일정도 짜줘")
    assert path == [A, R, W, X, F] and st["rag_docs"] == []
    assert st["weather"]["ok"] and st["exchange"]["ok"]
    assert any(e.startswith("rag_search") for e in st["errors"])
    assert "가져오지 못했" in st["final_answer"]


def test_t21_max_steps_guard(run, monkeypatch):
    monkeypatch.setenv("MAX_STEPS", "1")
    get_settings.cache_clear()
    st, path = run("도쿄 날씨랑 환율 알려주고 일정도 짜줘")
    assert path == [A, R, F]                       # 가드로 탈출
    assert st["pending_intents"] == ["weather", "exchange"] and st["final_answer"]


def test_every_work_node_pops_its_task_on_failure(run, monkeypatch):
    # 도구가 예외를 던져도 큐가 전진해 종료한다
    def boom(*a, **k):
        raise RuntimeError("tool down")
    broken = SimpleNamespace(invoke=boom)
    monkeypatch.setattr("src.nodes.weather_node.get_weather", broken)
    monkeypatch.setattr("src.nodes.exchange_node.convert_currency", broken)
    st, path = run("도쿄 날씨랑 환율 알려줘")
    assert path == [A, W, X, F] and st["weather"] is None and st["exchange"] is None
    assert st["pending_intents"] == []


# ---- 14.4 E2E 시나리오 ----
def test_s1_recommend(run):
    st, path = run("여름에 휴양하기 좋은 곳 추천해줘")
    assert path == [A, R, F] and st["rag_docs"] and st["final_answer"]


def test_s2_weather(run):
    st, path = run("방콕 날씨 어때?")
    assert path == [A, W, F] and "°C" in st["final_answer"]


def test_s3_exchange(run):
    st, path = run("파리 100만원이면 몇 유로야?")
    assert path == [A, X, F]
    assert st["exchange"]["target"] == "EUR" and "EUR" in st["final_answer"]
    assert "100만원 기준" not in st["final_answer"]          # 금액을 말했으므로 가정 문구 없음


def test_s4_itinerary(run):
    st, path = run("제주 2박3일 일정 짜줘")
    assert path == [A, R, W, F] and st["entities"]["days"] == 3
    assert all(d["city"] == "jeju" for d in st["rag_docs"])
    assert "환전" not in st["final_answer"]


def test_s5_multi(run):
    st, path = run("도쿄 날씨랑 환율 알려주고 일정도 짜줘")
    assert path == [A, R, W, X, F]
    fa = st["final_answer"]
    assert "날씨" in fa and "환율" in fa and ".txt#" not in fa  # 본문에는 파일 표기 없음
    assert any(d["source"] == "tokyo.txt" for d in st["rag_docs"])  # 근거는 State(출처 칩/CLI 출처 줄)로
    assert "100만원 기준" in fa                              # 금액 미지정 -> 가정 명시


def test_s6_s7_clarify_then_city_only(run):
    st, path = run("날씨 알려줘")
    assert path == [A, C]
    st, path = run("뉴욕")        # 설계상 한계: 이전 의도 복원 없이 새 질의(recommend)로 처리
    assert path == [A, R, F] and st["rag_docs"] and all(d["city"] == "newyork" for d in st["rag_docs"])


def test_s8_jeju_exchange_not_needed(run):
    st, path = run("제주 환율 알려줘")
    assert path == [A, X, F] and st["exchange"]["rate"] == 1.0
    assert "환전이 필요 없" in st["final_answer"]


def test_s9_unknown(run):
    st, path = run("오늘 점심 뭐 먹지")
    assert path == [A, F] and st["intent"] == "unknown" and "여행 관련" in st["final_answer"]


def test_s10_network_blocked(run, monkeypatch):
    monkeypatch.setenv("WEATHER_MODE", "auto")
    monkeypatch.setenv("EXCHANGE_MODE", "auto")
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-secret-key")
    get_settings.cache_clear()

    def down(*a, **k):
        raise httpx.ConnectError("network blocked")
    monkeypatch.setattr("src.tools.weather.httpx.get", down)
    monkeypatch.setattr("src.tools.exchange.httpx.get", down)
    st, path = run("도쿄 날씨랑 환율 알려주고 일정도 짜줘")
    assert path == [A, R, W, X, F]
    assert st["weather"]["source"] == "mock" and st["weather"]["fallback_reason"] == "ConnectError"
    assert st["exchange"]["source"] == "mock" and st["exchange"]["fallback_reason"] == "ConnectError"
    assert "참고용" in st["final_answer"] and "dummy-secret-key" not in str(st)


def test_foreign_currency_amount_flow(run):
    st, path = run("환율 100달러")
    assert path == [A, X, F]
    assert (st["exchange"]["base"], st["exchange"]["target"]) == ("USD", "KRW")


def test_vague_recommend_clarifies(run):
    st, path = run("어디 갈까?")
    assert path == [A, C] and "취향" in st["final_answer"]
