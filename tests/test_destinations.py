"""여행지 레지스트리, 선택 카드, 미지원 여행지 안내 (FR-09)."""
import re

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from src import destinations as dest
from src.config import get_settings
from src.graph import build_graph
from src.main import run_turn
from src.nodes.analyze import Analysis, analyze_input
from src.web import routes
from src.web.app import app
from tests.test_web import ask, dict_events

KEYS = ["tokyo", "paris", "bangkok", "newyork", "jeju"]


@pytest.fixture()
def client():
    cp = MemorySaver()
    app.state.checkpointer, app.state.graph = cp, build_graph(checkpointer=cp)
    routes.PENDING.clear()
    routes.RUNNING.clear()
    with TestClient(app) as c:
        yield c
    app.state.checkpointer = app.state.graph = None


def _board(html: str) -> str:
    m = re.search(r'<section id="board-destinations".*?</section>', html, re.S)
    assert m
    return m.group(0)


# ---------------------------------------------------------------- 레지스트리

def test_registry_supported_five():
    assert [d["key"] for d in dest.supported_destinations()] == KEYS
    for d in dest.supported_destinations():
        assert {"ko", "country", "currency", "intro", "guide", "enabled"} <= set(d)


def test_registry_disabled_or_missing_guide_excluded(monkeypatch, tmp_path):
    monkeypatch.setitem(dest.DESTINATIONS["paris"], "enabled", False)
    assert "paris" not in dest.supported_keys()
    assert dest.normalize_destination("파리 날씨") is None
    monkeypatch.setitem(dest.DESTINATIONS["paris"], "enabled", True)
    assert "paris" in dest.supported_keys()
    # 가이드 md 가 없으면 빠진다
    (tmp_path / "tokyo.txt").write_text("# x", encoding="utf-8")
    monkeypatch.setenv("GUIDES_DIR", str(tmp_path))
    get_settings.cache_clear()
    assert dest.supported_keys() == ["tokyo"]


def test_registry_new_entry_appears(monkeypatch, tmp_path):
    (tmp_path / "osaka.txt").write_text("# x", encoding="utf-8")
    monkeypatch.setenv("GUIDES_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setitem(dest.DESTINATIONS, "osaka", {
        "ko": "오사카", "country": "일본", "currency": "JPY", "lat": 0, "lon": 0,
        "intro": "x", "guide": "osaka.txt", "enabled": True, "aliases": ["오사카"]})
    assert dest.supported_keys() == ["osaka"]
    assert dest.find_unsupported("오사카 일정") == []   # 지원되면 미지원 사전에서 제외


@pytest.mark.parametrize("text,names", [
    ("런던 날씨 알려줘", ["런던"]), ("오사카 일정 짜줘", ["오사카"]), ("로마 맛집", ["로마"]),
    ("이탈리아 여행", ["이탈리아"]), ("싱가포르 환율", ["싱가포르"]), ("다낭 날씨", ["다낭"]),
    ("베트남 갈래", ["베트남"]), ("하와이 일정", ["하와이"]), ("시드니 날씨", ["시드니"]), ("호주 환율", ["호주"]),
    ("바르셀로나 추천", ["바르셀로나"]), ("스페인 일정", ["스페인"]), ("홍콩 날씨", ["홍콩"]),
    ("타이베이 일정", ["타이베이"]), ("대만 환율", ["대만"]), ("발리 휴양", ["발리"]), ("LA 날씨", ["LA"]),
    ("la 일정", ["LA"]), ("Osaka trip", ["오사카"]), ("도쿄랑 런던 날씨", ["런던"]),
    ("도쿄 날씨 알려줘", []), ("호주머니 사정은?", []), ("latest plan", []), ("세부 일정 짜줘", []),
])
def test_find_unsupported(text, names):
    assert dest.find_unsupported(text) == names


# ---------------------------------------------------------------- 그래프

def test_unsupported_only_routes_to_clarify(run):
    st, path = run("런던 날씨 알려줘")
    assert path == ["analyze_input", "clarify"]
    assert st["final_answer"] == "지금 요청하신 런던의 정보는 아직 존재하지 않습니다. 아래 여행지 중에서 선택해 주세요."
    assert st["clarify_reason"] == "unsupported_destination" and st["unsupported_destination"] == "런던"
    assert not st.get("weather")


def test_osaka_itinerary_unsupported(run):
    st, path = run("오사카 일정 짜줘")
    assert path == ["analyze_input", "clarify"] and "오사카" in st["final_answer"]


def test_unsupported_does_not_reuse_previous_destination(run, new_thread):
    tid = new_thread()
    run("도쿄 날씨 알려줘", tid)
    st, path = run("런던 날씨 알려줘", tid)
    assert path == ["analyze_input", "clarify"]
    assert st["entities"]["destination"] == "tokyo"      # 보드(목적지)는 바뀌지 않는다
    st, _ = run("환율은?", tid)
    assert st["exchange"]["target"] == "JPY" and not st.get("unsupported_destination")  # 턴마다 초기화


def test_mixed_supported_and_unsupported(run):
    st, path = run("도쿄랑 런던 날씨")
    assert path == ["analyze_input", "weather_tool", "generate_answer"]
    assert st["entities"]["destination"] == "tokyo"
    last = st["final_answer"].strip().splitlines()[-1]
    assert last.startswith("참고: 런던의 정보는 아직 존재하지 않습니다.")


def test_llm_destination_not_in_registry_is_unsupported(monkeypatch):
    from src.nodes import analyze as an
    monkeypatch.setattr(an, "_llm_analyze", lambda text, prev: Analysis(intent="weather", destination="리옹"))
    out = analyze_input({"user_input": "리옹 날씨", "entities": {}})
    assert out["needs_clarification"] and out["clarify_reason"] == "unsupported_destination"
    assert out["unsupported_destination"] == "리옹"
    # 지원 도시를 LLM 이 정상 추출하면 영향 없음
    monkeypatch.setattr(an, "_llm_analyze", lambda text, prev: Analysis(intent="weather", destination="도쿄"))
    out = analyze_input({"user_input": "도쿄 날씨", "entities": {}})
    assert not out["needs_clarification"] and out["unsupported_destination"] is None


def test_cli_output_lists_choices(graph):
    out = run_turn(graph, "런던 날씨 알려줘", "cli-1")
    assert "런던의 정보는 아직 존재하지 않습니다" in out
    assert "선택 가능: 도쿄(일본), 파리(프랑스), 방콕(태국), 뉴욕(미국), 제주(대한민국)" in out


def test_cli_source_line_keeps_filenames(graph):
    out = run_turn(graph, "도쿄 맛집 추천해줘", "cli-2")
    assert "출처:" in out and ".txt" in out


# ---------------------------------------------------------------- 웹

def test_board_has_no_destination_section_but_modal_has_five_radio_cards(client):
    html = client.get("/").text
    assert 'id="board-destinations"' not in html and "여행지 선택</h2>" not in html
    m = re.search(r'<dialog id="plan-modal".*?</dialog>', html, re.S)
    assert m
    modal = m.group(0)
    assert modal.count('type="radio" name="destination"') == 5 and "data-ask=" not in modal
    assert ".txt" not in html


def test_header_event_no_longer_renders_destination_section(client):
    bl = ask(client, "도쿄 날씨, 환율, 일정 알려줘", "t-sel")
    header = [h for n, h in bl if n == "board" and 'id="page-title"' in h]
    assert header and all("board-destinations" not in h for h in header)
    page = client.get("/?thread_id=t-sel").text
    assert ".txt" not in page and "board-destinations" not in page
    assert ".txt" not in "".join(h for n, h in bl if n == "board")


def test_stream_unsupported_has_notice_cards_and_no_board(client):
    bl = ask(client, "런던 날씨 알려줘", "t-un")
    names = [n for n, _ in bl]
    assert "board" not in names and names[-2:] == ["answer", "done"]
    ans = dict(bl)["answer"]
    assert "지금 요청하신 런던의 정보는 아직 존재하지 않습니다. 아래 여행지 중에서 선택해 주세요." in ans
    assert ans.count("data-ask=") == 5 and "aria-pressed" not in ans and ".txt" not in ans
    nodes = [e["node"] for e in dict_events(app.state.graph, "오사카 일정 짜줘", "t-un2") if e["event"] == "node_end"]
    assert nodes == ["analyze_input", "clarify"]
    # 복원 시에도 말풍선 아래 카드
    page = client.get("/?thread_id=t-un").text
    assert "아직 존재하지 않습니다" in page and page.count("data-ask=") == 5   # 말풍선 5 (보드의 여행지 선택 섹션은 없다)
    assert page.count('aria-pressed="true"') == 0


def test_supported_answer_has_no_cards(client):
    assert "data-ask=" not in dict(ask(client, "도쿄 날씨 알려줘", "t-ok"))["answer"]


def test_source_chip_uses_city_label_not_filename(client):
    ans = dict(ask(client, "파리 맛집 추천해줘", "t-chip"))["answer"]
    assert "파리 가이드" in ans and ".txt" not in ans and "title=" not in ans


def test_guide_and_itinerary_cards_have_no_md(client):
    bl = ask(client, "도쿄 3박 4일 일정 짜줘", "t-md")
    for n, h in bl:
        assert ".txt" not in h, n
    page = client.get("/?thread_id=t-md").text
    assert "board-guide" in page and "1일차" in page and ".txt" not in page
