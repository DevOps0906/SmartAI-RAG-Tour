"""여행 작업실 구조: 위젯 닫기는 이동 없음, 모달 제출은 작업실 교체, 내 여행 기록 패널(목록·더 보기·부분 로드·삭제)."""
import re

import pytest

from src.web import routes, threads as ts
from tests.test_plan import START, ask_stream
from tests.test_web import ask, client  # noqa: F401  (client 픽스처 재사용)

WS = {"HX-Request": "true", "HX-Current-URL": "http://testserver/planner?thread_id=old"}
DATA = {"destination": "tokyo", "start_date": START, "days": "3", "places": ["아사쿠사", "시부야"]}


@pytest.fixture(autouse=True)
def _clear_pending():
    routes.PENDING_TRIP.clear()
    yield
    routes.PENDING_TRIP.clear()


def make_trip(client, dest="tokyo", days="3", places=("아사쿠사",)):
    """POST /plan 후 스트림을 끝까지 돌려 체크포인트에 trip thread 를 만든다."""
    r = client.post("/plan", data={**DATA, "destination": dest, "days": days, "places": list(places)}, follow_redirects=False)
    tid = r.headers["location"].split("thread_id=")[1].split("&")[0]
    ask_stream(client, tid)
    return tid


def widget_html(page: str) -> str:
    return re.search(r'<section id="chat-widget".*?</section>', page, re.S).group(0)


def test_widget_has_no_link_to_planner(client):
    w = widget_html(client.get("/planner").text)
    assert "href=" not in w and 'data-action="close-chat"' in w and 'aria-label="새 대화"' not in w
    # 스트림 연결 요소와 thread 입력은 위젯 안에 있어도 display:none 으로 끊기지 않는다(EventSource 는 표시와 무관)
    assert 'id="chat-session"' in w


def test_post_plan_workspace_partial(client):
    r = client.post("/plan", data=DATA, headers=WS, follow_redirects=False)
    assert r.status_code == 200 and "HX-Redirect" not in r.headers
    url = r.headers["HX-Push-Url"]
    assert re.fullmatch(r"/planner\?thread_id=[0-9a-f]{32}", url)
    assert r.headers["HX-Retarget"] == "#board-root" and r.headers["HX-Reswap"] == "innerHTML"
    tid = url.split("thread_id=")[1].split("&")[0]
    body = r.text
    assert "<html" not in body and 'id="board-trip"' in body and "아사쿠사" in body             # 요약 바와 보드(스켈레톤)
    assert f"/chat/stream?thread_id={tid}" in body and 'hx-swap-oob="innerHTML"' in body       # 새 스트림 시작 마크업
    assert f'id="chat-session" hidden data-thread="{tid}"' in body and 'data-autostart="true"' in body
    assert tid in routes.PENDING and tid in routes.PENDING_TRIP
    bl = ask_stream(client, tid)                                                               # 스트림이 보드를 채운다
    assert "board-itinerary" in "\n".join(h for n, h in bl if n == "board")


def test_post_plan_plain_and_landing_still_redirect(client):
    plain = client.post("/plan", data=DATA, follow_redirects=False)
    assert plain.status_code == 303 and plain.headers["location"].startswith("/planner?thread_id=")
    landing = client.post("/plan", data=DATA, headers={"HX-Request": "true", "HX-Current-URL": "http://testserver/"})
    assert landing.headers["HX-Redirect"].startswith("/planner?thread_id=")


def test_post_plan_invalid_keeps_screen(client):
    r = client.post("/plan", data={**DATA, "days": "9"}, headers=WS)
    assert r.status_code == 400 and "5일차까지" in r.text and "HX-Push-Url" not in r.headers and not routes.PENDING_TRIP


def test_planner_without_thread_shows_latest_trip_or_empty(client):
    empty = client.get("/planner").text
    assert "새 여행 계획으로 시작해 보세요" in empty and 'data-empty="true"' in empty
    old = make_trip(client, "tokyo")
    new = make_trip(client, "paris", "2", ("에펠탑",))
    page = client.get("/planner").text
    assert f'id="chat-session" hidden data-thread="{new}"' in page and 'id="board-trip"' in page and "파리" in page
    # GNB 링크가 가리키는 같은 주소: HTMX 요청이면 부분 응답과 주소 교체 헤더
    r = client.get("/planner", headers={"HX-Request": "true"})
    assert "<html" not in r.text and r.headers["HX-Replace-Url"] == f"/planner?thread_id={new}" and old != new


def test_history_panel_groups_and_order(client):
    ask(client, "도쿄 날씨 알려줘", "t-chat")
    a = make_trip(client, "tokyo")
    b = make_trip(client, "paris", "4", ("에펠탑", "루브르"))
    html = client.get(f"/threads?thread_id={b}").text
    m = re.search(r"파리 \d+/\d+~\d+/\d+ · 3박4일", html)
    assert m and re.search(r"도쿄 \d+/\d+~\d+/\d+ · 2박3일", html)
    assert m.start() < html.index("도쿄 ") and html.index("에펠탑") < html.index("루브르")    # 최근 순, 장소 칩
    assert html.index("여행 계획") < html.index("파리") < html.index(">대화<") < html.index("도쿄 날씨 알려줘")
    assert html.count('aria-current="page"') == 1 and f'data-thread-id="{b}"' in html
    assert f'hx-get="/planner?thread_id={a}"' in html and 'hx-push-url="true"' in html and "기록에서 삭제" in html
    assert 'data-server-ids="' in html and a in html.split('data-server-ids="')[1].split('"')[0]


def test_history_pagination_over_30(client):
    from langchain_core.messages import HumanMessage
    cp = client.app.state.checkpointer
    g = client.app.state.graph
    for i in range(35):   # 체크포인트만 직접 만든다(그래프 실행 없이)
        g.update_state({"configurable": {"thread_id": f"t-bulk-{i:02d}"}}, {"messages": [HumanMessage(content=f"질문 {i}")]}, as_node="generate_answer")
    assert len(ts.history_rows(cp)) == 35
    html = client.get("/threads").text
    assert html.count('data-kind="chat"') == ts.PAGE_SIZE and 'id="history-more"' in html and "더 보기 (5개)" in html
    more = client.get(f"/threads?offset={ts.PAGE_SIZE}").text
    assert more.count('data-kind="chat"') == 5 and 'id="history-more"' not in more and "<ul" not in more


def test_planner_partial_loads_history_item(client):
    ask(client, "도쿄 날씨 알려줘", "t-part")
    tid = make_trip(client, "jeju", "2", ("성산일출봉",))
    r = client.get(f"/planner?thread_id={tid}", headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<html" not in r.text and r.headers["Vary"] == "HX-Request" and "HX-Replace-Url" not in r.headers
    assert "성산일출봉" in r.text and f'data-thread="{tid}"' in r.text and 'id="page-title"' in r.text and 'hx-swap-oob="innerHTML"' in r.text
    chat = client.get("/planner?thread_id=t-part", headers={"HX-Request": "true"}).text
    assert "도쿄 날씨 알려줘" in chat and 'id="board-trip"' not in chat
    full = client.get(f"/planner?thread_id={tid}", headers={"HX-Request": "true", "HX-History-Restore-Request": "true"})
    assert "<html" in full.text                                           # 히스토리 복원 요청은 전체 페이지


def test_delete_thread(client):
    tid = make_trip(client)
    keep = make_trip(client, "paris", "2", ("에펠탑",))
    assert tid in client.get("/threads").text
    r = client.delete(f"/threads/{tid}")
    assert r.status_code == 200 and r.json() == {"deleted": tid}
    html = client.get("/threads").text
    assert tid not in html and keep in html
    assert client.delete(f"/threads/{tid}").status_code == 404
    assert client.delete("/threads/no-such-thread").status_code == 404
    routes.RUNNING.add(keep)
    assert client.delete(f"/threads/{keep}").status_code == 409


def test_offline_workspace_partial(client):
    plan = {"trip": {"destination": "tokyo", "destination_ko": "도쿄", "start_date": START, "end_date": START, "days": 1,
                     "places": ["아사쿠사"]}, "itinerary": [], "forecast": [], "exchange": None, "details": []}
    r = client.post("/plan/offline?workspace=1&thread_id=t-local", json=plan)
    assert r.status_code == 200 and 'data-thread="t-local"' in r.text and 'data-offline="true"' in r.text
    assert "이 기기에 저장된 사본" in r.text and 'id="page-title"' in r.text


def test_history_scripts_and_markup(client):
    js = client.get("/static/js/app.js").text
    for key in ("popstate", "historyCacheMiss", "renderLocal", "markCurrent", "/threads/", "DELETE", "syncSession"):
        assert key in js
    page = client.get("/planner").text
    assert 'id="board-root"' in page and 'id="history-local-tpl"' in page and "이 기기에 저장된 사본" in page
    assert 'id="delete-modal-note"' in page
