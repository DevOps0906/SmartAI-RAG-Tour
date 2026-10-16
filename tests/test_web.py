"""웹 계층 검증(실제 그래프, MemorySaver, 키 없는 오프라인 환경). 실행: python -m pytest tests/test_web.py"""
import asyncio
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from src.graph import build_graph
from src.web import routes
from src.web.app import app
from src.web.sse import ERROR_MESSAGE, format_sse, graph_events

TOKYO = "도쿄 3박 4일 일정이랑 날씨 알려주고, 50만원이면 엔화로 얼마인지도 알려줘"


@pytest.fixture()
def client():
    cp = MemorySaver()
    app.state.checkpointer, app.state.graph = cp, build_graph(checkpointer=cp)
    routes.PENDING.clear()
    routes.RUNNING.clear()
    routes.USED_TOKENS.clear()
    with TestClient(app) as c:
        yield c
    app.state.checkpointer = app.state.graph = None


def blocks(body: str) -> list[tuple[str, str]]:
    out = []
    for b in body.strip().split("\n\n"):
        lines = b.split("\n")
        assert lines[0].startswith("event: ") and all(ln.startswith("data:") for ln in lines[1:]), b[:80]
        out.append((lines[0][7:], "\n".join(ln[5:].lstrip(" ") for ln in lines[1:])))
    return out


def ask(client, text, tid, debug=False):
    r = client.post("/chat", data={"message": text, "thread_id": tid, "debug": "1" if debug else ""})
    assert r.status_code == 200
    with client.stream("GET", f"/chat/stream?thread_id={tid}" + ("&debug=1" if debug else "")) as s:
        assert s.headers["content-type"].startswith("text/event-stream")
        return blocks("".join(s.iter_text()))


def dict_events(graph, text, tid):
    async def collect():
        cfg = {"configurable": {"thread_id": tid}, "recursion_limit": 25}
        return [e async for e in graph_events(graph, text, cfg)]
    return asyncio.run(collect())


def path_of(events):
    return [e["node"] for e in events if e["event"] == "node_end"]


# ---------------------------------------------------------------- 페이지

@pytest.mark.parametrize("path", ["/", "/planner", "/dev/components", "/threads"])
def test_pages_ok(client, path):
    r = client.get(path)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_index_new_thread_each_visit(client):
    pat = r'name="thread_id" value="([0-9a-f]{32})"'
    a = re.search(pat, client.get("/planner").text).group(1)
    b = re.search(pat, client.get("/planner").text).group(1)
    assert a != b
    html = client.get("/planner").text
    assert "도시를 알려 주시면 날씨를 보여드려요." in html and "새 여행 계획" in html
    assert "예시 데이터" not in html  # 목업 카드가 아니다
    assert client.get("/planner?thread_id=bad id!").status_code == 200


def test_static(client):
    assert client.get("/static/js/htmx.min.js").status_code == 200
    assert client.get("/static/css/app.css").status_code == 200


# ---------------------------------------------------------------- POST /chat

def test_chat_accepts_and_validates(client):
    r = client.post("/chat", data={"message": " 안녕 ", "thread_id": "t-x"})
    assert 'sse-connect="/chat/stream?thread_id=t-x&amp;p=' in r.text
    assert r.headers["HX-Trigger"] == "thread-updated" and routes.PENDING["t-x"] == "안녕"
    for msg in ("   ", "", "가" * 1001):
        bad = client.post("/chat", data={"message": msg, "thread_id": "t-y"})
        assert "1자 이상" in bad.text and "t-y" not in routes.PENDING
    assert "sse-connect" in client.post("/chat", data={"message": "가" * 1000, "thread_id": "t-y"}).text


def test_chat_rejects_concurrent_run(client):
    routes.RUNNING.add("t-busy")
    r = client.post("/chat", data={"message": "도쿄 날씨", "thread_id": "t-busy"})
    assert "이전 답변을 만드는 중이에요." in r.text and "t-busy" not in routes.PENDING


def test_stream_without_pending_errors(client):
    ev = [n for n, _ in blocks(client.get("/chat/stream?thread_id=none").text)]
    assert ev == ["error", "done"]


# ---------------------------------------------------------------- 이벤트 사전 층

def test_format_sse_multiline():
    assert format_sse("answer", "a\nb") == "event: answer\ndata: a\ndata: b\n\n"


def test_graph_events_tokyo_multi(graph, new_thread):
    evs = dict_events(graph, TOKYO, new_thread())
    assert evs[0] == {"event": "node_start", "node": "analyze_input", "label": "질문 분석"}
    assert path_of(evs) == ["analyze_input", "rag_search", "weather_tool", "exchange_tool", "generate_answer"]
    assert [e["node"] for e in evs if e["event"] == "node_start"] == path_of(evs)  # node_start/node_end 쌍
    for e in evs:
        if e["event"] == "node_end":
            assert isinstance(e["ms"], int) and e["status"] in {"success", "fallback", "error"}
    by = {e["node"]: e["status"] for e in evs if e["event"] == "node_end"}
    assert by["weather_tool"] == "fallback" and by["exchange_tool"] == "fallback"
    cards = [e["card"] for e in evs if e["event"] == "board"]
    assert {"header", "guide", "itinerary", "weather", "exchange"} <= set(cards)
    kinds = [e["event"] for e in evs]
    assert kinds.index("answer") < kinds.index("done") == len(kinds) - 1
    ans = next(e for e in evs if e["event"] == "answer")
    assert ans["text"] and not ans["clarify"] and ans["sources"]


def test_graph_events_clarify_keeps_board(graph, new_thread):
    evs = dict_events(graph, "어디 갈까?", new_thread())
    assert path_of(evs) == ["analyze_input", "clarify"]
    assert "board" not in [e["event"] for e in evs]
    ans = next(e for e in evs if e["event"] == "answer")
    assert ans["clarify"] and ans["sources"] == []


def test_graph_events_error_is_event(new_thread):
    class Boom:
        def stream(self, *a, **k):
            raise RuntimeError("secret detail")

    evs = dict_events(Boom(), "도쿄 날씨", new_thread())
    assert [e["event"] for e in evs][-2:] == ["error", "done"]
    assert evs[-2]["message"] == ERROR_MESSAGE and "secret" not in str(evs)


# ---------------------------------------------------------------- SSE 와이어

def test_stream_tokyo_full(client):
    bl = ask(client, TOKYO, "t-tokyo", debug=True)
    names = [n for n, _ in bl]
    assert names[0] == "node_start" and names[-1] == "done"
    assert {"node_start", "node_end", "board", "answer", "done"} <= set(names)
    assert names.index("answer") < names.index("done")
    body = "\n".join(h for _, h in bl)
    for node in ["analyze_input", "rag_search", "weather_tool", "exchange_tool", "generate_answer"]:
        assert node in body
    boards = "\n".join(h for n, h in bl if n == "board")
    for card in ("board-weather", "board-exchange", "board-guide", "board-itinerary", 'id="page-title"'):
        assert card in boards
    assert "board-fresh" in boards and "hx-swap-oob" in boards and "도쿄 · JPY" in boards
    assert "1일차" in boards  # 일정 카드
    assert "도쿄 가이드" in dict(bl)["answer"] and ".txt" not in dict(bl)["answer"]
    assert ".txt" not in boards


def test_stream_clarify(client):
    bl = ask(client, "어디 갈까?", "t-clar")
    names = [n for n, _ in bl]
    assert "board" not in names and names[-2:] == ["answer", "done"]
    assert "rag_search" not in "".join(h for _, h in bl)


# ---------------------------------------------------------------- 대화 기억 / 사이드바

def test_second_turn_keeps_destination(client):
    ask(client, "도쿄 날씨 알려줘", "t-mem")
    bl = ask(client, "환율은?", "t-mem")
    boards = "\n".join(h for n, h in bl if n == "board")
    assert "JPY" in boards and "board-exchange" in boards
    assert 'id="board-weather"' not in boards  # 날씨 카드는 유지(갱신 안 함)


def test_threads_sidebar_and_restore(client):
    assert "아직 계획한 여행이 없어요" in client.get("/threads").text
    ask(client, "도쿄 날씨 알려줘", "t-a")
    ask(client, "제주 2박 3일 일정 짜줘", "t-b")
    html = client.get("/threads?thread_id=t-b").text
    assert "도쿄 날씨 알려줘" in html and "제주 2박 3일 일정 짜줘" in html
    assert html.index("제주") < html.index("도쿄")  # 최근 순
    assert 'href="/planner?thread_id=t-a"' in html and 'aria-current="page"' in html
    # 복원: 대화와 보드
    page = client.get("/planner?thread_id=t-a").text
    assert "도쿄 날씨 알려줘" in page and "도쿄 · JPY" in page and "맑음" in page
    ask(client, "환율은?", "t-a")
    page = client.get("/planner?thread_id=t-a").text
    assert "환율은?" in page and "맑음" in page and "JPY" in page  # 이전 턴의 날씨 카드도 복원


def test_sqlite_checkpointer_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_CHECKPOINT", "sqlite")
    monkeypatch.setenv("WEB_DB_PATH", str(tmp_path / "t.sqlite"))
    from src.config import get_settings
    get_settings.cache_clear()
    from src.web import threads as ts
    from src.web.runtime import make_checkpointer
    cp = make_checkpointer()
    try:
        g = build_graph(checkpointer=cp)
        dict_events(g, "도쿄 날씨 알려줘", "t-sql")
        rows = ts.list_threads(cp)
        assert [r["thread_id"] for r in rows] == ["t-sql"] and rows[0]["title"] == "도쿄 날씨 알려줘"
        assert ts.restore(g, "t-sql")["state"]["weather"]
    finally:
        cp.conn.close()
    assert sqlite3.connect(tmp_path / "t.sqlite").execute("select count(*) from checkpoints").fetchone()[0] > 0


def test_rel_time():
    from src.web.threads import rel_time
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)

    def f(**k):
        return rel_time((now - timedelta(**k)).isoformat(), now)

    assert (f(seconds=5), f(minutes=3), f(hours=2), f(days=1), f(days=4)) == ("방금", "3분 전", "2시간 전", "어제", "4일 전")


def test_error_cards_have_action():
    from src.web.app import templates
    ctx = routes.board_context({"weather": {"ok": False}, "exchange": {"ok": False}, "entities": {}})
    for name, action in (("weather", 'data-action="retry"'), ("exchange", 'data-action="focus-input"')):
        html = templates.env.get_template(f"partials/card_{name}.html").render(loading=False, oob=True, fresh=True, **ctx)
        assert action in html and "board-fresh" in html and 'role="alert"' in html


# ---------------------------------------------------------------- 9단계 마무리 보정

def test_board_empty_notice_cleared_on_first_board(client):
    bl = ask(client, "도쿄 날씨 알려줘", "t-empty")
    boards = [h for n, h in bl if n == "board"]
    assert 'id="board-empty" hx-swap-oob="delete"' in boards[0]
    assert sum('board-empty' in h for h in boards) == 1  # 한 번만
    assert 'id="board-empty"' in client.get("/planner").text   # 새 대화에는 안내문이 있다


def test_guide_card_cleaned_and_city_on_restore(client):
    ask(client, "도쿄 3박 4일 여행 알려줘", "t-g")
    page = client.get("/planner?thread_id=t-g").text
    assert "**" not in page and "[도쿄 ·" not in page
    assert "도쿄 추천 요약" in page
    # 엔티티에 도시가 없어도 가이드 문서의 도시명으로 부제를 채운다
    docs = [{"content": "[파리 · 음식] - **바게트**: 맛있다.", "city": "paris", "section": "음식", "source": "paris.txt", "score": 0.1}]
    assert routes.board_context({"entities": {}, "rag_docs": docs})["guide_city"] == "파리"


def test_exchange_card_kst_stamp_and_mock(client):
    from src.web.fmt import kst_stamp
    assert kst_stamp("Fri, 16 Oct 2026 00:02:31 +0000") == "2026-10-16 09:02"
    assert kst_stamp("2026-10-16T20:00:00+00:00") == "2026-10-17 05:00"
    assert kst_stamp("엉터리") == "" and kst_stamp(None) == ""
    tpl = app.state.templates.get_template("partials/card_exchange.html")
    x = {"ok": True, "source": "live", "base": "KRW", "target": "JPY", "rate": 0.1, "amount": 1000,
         "converted": 100, "rate_date": "Fri, 16 Oct 2026 00:02:31 +0000"}
    html = tpl.render(s={"exchange": x}, loading=False, oob=False, fresh=False)
    assert "2026-10-16 09:02" in html and "+0000" not in html
    html = tpl.render(s={"exchange": {**x, "rate_date": "???"}}, loading=False, oob=False, fresh=False)
    assert "기준" not in html
    html = tpl.render(s={"exchange": {**x, "source": "mock", "rate_date": None}}, loading=False, oob=False, fresh=False)
    assert "고정 환율" in html and "기준" not in html


def test_chat_widget_markup_no_tabs(client):
    html = client.get("/planner").text
    # 하단 탭 바와 고정 AI 패널 칼럼은 없다
    assert 'role="tablist"' not in html and "data-tab-target" not in html and 'id="ai-panel"' not in html
    # 플로팅 버튼
    assert 'id="chat-fab"' in html and 'aria-label="AI 여행 비서 열기"' in html
    assert 'aria-expanded="false"' in html and 'aria-controls="chat-widget"' in html
    assert "새 답변" in html  # 알림 점의 sr-only 텍스트
    # 대화창
    assert 'id="chat-widget"' in html and 'role="dialog"' in html and 'aria-label="AI 여행 비서"' in html
    assert "대기 중" in html and 'data-action="close-chat"' in html
    # 빈 대화 인사 + 예시 칩 4개
    assert "안녕하세요! 여행지, 날씨, 환율, 일정을 물어보세요." in html
    assert html.count("data-fill=") >= len(routes.EXAMPLES)
    for ex in routes.EXAMPLES:
        assert f'data-fill="{ex}"' in html
    assert "새 여행 계획" in html and 'id="board-weather"' in html  # 보드는 메인에 그대로


def test_chat_pair_has_bubble_and_typing(client):
    r = client.post("/chat", data={"message": "도쿄 날씨", "thread_id": "t-ty"})
    assert "data-typing" in r.text and "typing-dot" in r.text and "답변 작성 중" in r.text
    assert 'data-time' in r.text and "data-user-msg" in r.text


def test_restored_thread_has_no_greeting(client):
    ask(client, "도쿄 날씨 알려줘", "t-gr")
    page = client.get("/planner?thread_id=t-gr").text
    assert "안녕하세요! 여행지" not in page and 'data-empty="false"' in page and "data-intro-chips" not in page


def test_templates_have_no_hex_gradient_shadow():
    from pathlib import Path
    for p in Path("src/web/templates").rglob("*.html"):
        t = p.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}(?![^<]*</style>)", re.sub(r'href="#[^"]*"', "", t)), p
        assert "gradient" not in t and not re.search(r"shadow(-|)", t), p


def test_title_sync_script_present(client):
    assert "page-title" in client.get("/static/js/app.js").text
    assert 'id="page-title"' in client.get("/planner").text


# ---------------------------------------------------------------- 목적지 전환 (회귀)

def test_switch_city_updates_itinerary_and_clears_old_cards(client):
    ask(client, "도쿄 3박4일 일정이랑 날씨, 50만원 환전 얼마야?", "t-sw")
    bl = ask(client, "파리 4박5일 일정 짜줘", "t-sw")
    boards = "\n".join(h for n, h in bl if n == "board")
    assert "파리 · EUR" in boards
    assert "5일차" in boards and ".txt" not in boards  # 파리 일정 카드가 채워짐(파일명 비표시)
    # 환율은 이번 턴에 묻지 않았으므로 도쿄(JPY) 값 대신 빈 상태로 초기화된다
    exch = [h for n, h in bl if n == "board" and 'id="board-exchange"' in h][-1]
    assert "JPY" not in exch
    # 복원도 이전 도시 결과를 보드에 섞지 않는다 (대화 기록 속 도쿄 답변은 그대로 남는 게 맞다)
    from src.web.threads import restore
    st = restore(app.state.graph, "t-sw")["state"]
    assert {d["city"] for d in st["rag_docs"]} == {"paris"}
    assert not st.get("exchange")


def test_itinerary_doc_guaranteed_for_each_city():
    from src.nodes.rag_node import rag_search
    for city, ko in [("tokyo", "도쿄"), ("paris", "파리"), ("bangkok", "방콕"), ("newyork", "뉴욕"), ("jeju", "제주")]:
        out = rag_search({"user_input": f"{ko} 4박5일 일정 짜줘", "pending_intents": ["rag"],
                          "entities": {"destination": city, "days": 5}})
        assert any(d["section"] == "일정 예시" and d["city"] == city for d in out["rag_docs"]), city


@pytest.mark.parametrize("city,ko,n", [("tokyo", "도쿄", 4), ("paris", "파리", 5), ("bangkok", "방콕", 5),
                                        ("newyork", "뉴욕", 6), ("jeju", "제주", 3)])
def test_itinerary_days_parsed_for_every_city(city, ko, n):
    from src.rag.retriever import itinerary_docs
    from src.web.routes import board_context
    ctx = board_context({"rag_docs": itinerary_docs(city), "entities": {"destination": city, "destination_ko": ko}})
    assert [d["label"] for d in ctx["itin_days"]] == [f"{i}일차" for i in range(1, n + 1)], city
    assert len(ctx["itin_docs"]) == 1  # 출처 칩 중복 없음


def test_fallback_answer_has_no_file_markers():
    from src.nodes.respond import render_fallback
    from src.rag.retriever import itinerary_docs
    text = render_fallback({"intent": "itinerary", "entities": {"destination_ko": "파리"},
                            "rag_docs": itinerary_docs("paris"),
                            "weather": {"source": "mock", "condition": "비", "temp_c": 13, "humidity": 80, "advice": ""}})
    assert ".txt#" not in text and "[paris" not in text and "mock" not in text
    assert "일정 예시:" in text and "날씨(예시 데이터·참고용)" in text


def _stream_url(html: str) -> str:
    return re.search(r'sse-connect="([^"]+)"', html).group(1).replace("&amp;", "&")


def test_stream_works_on_another_instance_via_token(client):
    """서버리스: POST /chat 과 GET /chat/stream 을 다른 인스턴스가 받아도(메모리 PENDING 없음) p= 토큰으로 실행된다."""
    url = _stream_url(client.post("/chat", data={"message": "도쿄 날씨 알려줘", "thread_id": "t-inst"}).text)
    routes.PENDING.clear()
    with client.stream("GET", url) as s:
        names = [n for n, _ in blocks("".join(s.iter_text()))]
    assert "answer" in names and "error" not in names
    with client.stream("GET", url) as s:   # SSE 재연결로 같은 토큰이 다시 와도 두 번 실행하지 않는다
        assert "error" in [n for n, _ in blocks("".join(s.iter_text()))]


def test_stream_token_rejects_tampering_and_other_thread(client):
    from src.web import pending
    tok = pending.encode("t-a", "안녕")
    assert pending.decode(tok, "t-a") == ("안녕", None)
    assert pending.decode(tok, "t-b") is None                 # 다른 대화에 재사용 불가
    body, sig = tok.rsplit(".", 1)
    forged = pending.encode("t-a", "다른 말").rsplit(".", 1)[0] + "." + sig
    assert pending.decode(forged, "t-a") is None              # 서명 불일치
    assert pending.decode("garbage", "t-a") is None and pending.decode("", "t-a") is None
