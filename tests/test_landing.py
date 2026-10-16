"""랜딩(GET /), 공통 GNB, /search, courses(), 로컬 저장 사양(서버 JSON + PlanStore 코드) 검증."""
import json
import re

from src.courses import courses, slides
from src.destinations import supported_keys
from src.rag.guide import guide_places
from tests.test_plan import START, ask_stream, post_plan
from tests.test_web import ask, client  # noqa: F401  (client 픽스처 재사용)


def test_landing_is_root_with_hero_cards_gnb_modal(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert html.count('aria-roledescription="slide"') == 5
    for n in range(1, 6):
        assert f'aria-label="{n} / 5"' in html
    assert 'aria-roledescription="carousel"' in html and 'aria-label="이전 슬라이드"' in html and 'aria-label="다음 슬라이드"' in html
    assert html.count("data-dot=") == 5 and "번째 슬라이드로 이동" in html
    assert "이 여행지로 계획하기" in html and "인기 코스 보기" in html
    assert 'id="popular"' in html and "지금 인기 있는 코스" in html and "가이드에 담긴 명소로 바로 계획을 만들어 보세요." in html
    assert 'id="gnb"' in html and '<dialog id="plan-modal"' in html
    assert "여행지 둘러보기" in html and "이렇게 계획해요" in html and "2026년 기준 참고용" in html
    assert 'id="chat-fab"' not in html          # 챗봇 위젯은 /planner 에만 있다
    assert "<svg" in html


def test_planner_ok_and_legacy_redirect(client):
    assert client.get("/planner").status_code == 200
    r = client.get("/?thread_id=x", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308) and r.headers["location"] == "/planner?thread_id=x"
    r = client.get("/?thread_id=abc&debug=1", follow_redirects=False)
    assert r.headers["location"] == "/planner?thread_id=abc&debug=1"
    assert client.get("/?thread_id=x").url.path == "/planner"          # 따라가면 작업실


def test_gnb_logo_on_both_pages(client):
    for path in ("/", "/planner"):
        html = client.get(path).text
        assert re.search(r'<a href="/"[^>]*aria-label="스마트 여행 비서 첫 화면"', html), path
        assert "스마트 여행 비서" in html and 'data-action="open-gnb"' in html and 'id="gnb-panel"' in html
        assert 'href="/#popular"' in html and 'href="/planner' in html and 'data-action="toggle-theme"' in html
        assert html.count('data-action="new-plan"') >= 2
        assert 'role="search"' in html and "떠나고 싶은 여행지를 검색하세요" in html
        for key in supported_keys():
            assert f'data-plan-dest="{key}"' in html
        assert '<dialog id="plan-modal"' in html


def test_planner_keeps_sidebar_toggles_and_links(client):
    html = client.get("/planner").text
    assert 'data-action="open-menu"' in html and 'aria-label="내 여행 기록"' in html and 'id="history"' in html
    assert 'data-action="toggle-sidebar"' not in html          # lg 이상에서는 항상 보인다
    assert 'href="/planner"' in html and 'href="/?thread_id' not in html


def test_search_supported_and_unsupported(client):
    ok = client.get("/search", params={"q": "도쿄"}).text
    assert "data-search-open" in ok and 'data-plan-dest="tokyo"' in ok
    assert 'data-plan-dest="newyork"' in client.get("/search", params={"q": "NYC"}).text
    assert 'data-plan-dest="jeju"' in client.get("/search", params={"q": "제주도"}).text
    bad = client.get("/search", params={"q": "런던"}).text
    assert "아직 준비 중인 여행지예요" in bad and "도쿄" in bad and "data-search-open" not in bad
    assert "아직 준비 중인 여행지예요" in client.get("/search", params={"q": "아무데나xyz"}).text
    assert "data-search-open" not in client.get("/search", params={"q": "  "}).text
    assert "<script>" not in client.get("/search", params={"q": "<script>"}).text


def test_courses_supported_only_and_from_guide():
    items = courses()
    assert 8 <= len(items) <= 10
    ok = set(supported_keys())
    for c in items:
        assert c["dest"] in ok and 1 <= c["days"] <= 5
        names = {p["name"] for p in guide_places(c["dest"])}
        assert c["places"] and set(c["places"]) <= names
        assert re.fullmatch(r"\[.+\] .+ \d일", c["title"]) and c["cost_label"].startswith("약 ") and c["cost_label"].endswith("만원~")
        assert c["image"] is None and c["tags"]
    assert {c["dest"] for c in items} == ok
    assert {s["dest"] for s in slides()} == ok and len(slides()) == 5
    assert all(len(s["headline_lines"]) == 2 and len(s["tags"]) == 3 for s in slides())


def test_courses_skip_disabled_destination(monkeypatch):
    from src import destinations
    monkeypatch.setitem(destinations.DESTINATIONS["paris"], "enabled", False)
    assert "paris" not in {c["dest"] for c in courses()}


def test_course_cards_have_plan_attrs(client):
    html = client.get("/").text
    cards = re.findall(r'<button type="button" data-plan-dest="(\w+)" data-plan-days="(\d)" data-plan-places="([^"]+)"', html)
    assert len(cards) == len(courses())
    for dest, days, places in cards:
        assert 1 <= int(days) <= 5 and places
    assert "1인 예상 경비 " in html and "참고용" in html


def test_post_plan_from_landing_goes_to_planner(client):
    r = post_plan(client)
    assert r.headers["HX-Redirect"].startswith("/planner?thread_id=")
    plain = client.post("/plan", data={"destination": "tokyo", "start_date": START, "days": "2"}, follow_redirects=False)
    assert plain.status_code == 303 and plain.headers["location"].startswith("/planner?thread_id=")
    page = client.get(plain.headers["location"]).text
    assert 'data-autostart="true"' in page


# ------------------------------------------------------------ 로컬 저장 사양

def _tid_of(r):
    return r.headers["HX-Redirect"].split("thread_id=")[1].split("&")[0]


def test_plan_json_shape_and_no_secrets(client):
    tid = _tid_of(post_plan(client, places=["아사쿠사", "시부야"], days="3"))
    ask_stream(client, tid)
    r = client.get(f"/plan/{tid}.json")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    d = r.json()
    assert set(d) == {"thread_id", "saved_at", "updated_at", "trip", "itinerary", "forecast", "exchange", "details", "summary"}
    assert d["thread_id"] == tid and d["saved_at"] and d["updated_at"]
    assert set(d["trip"]) == {"destination", "destination_ko", "country", "currency", "start_date", "end_date", "days", "nights", "places", "places_auto"}
    assert d["trip"]["destination"] == "tokyo" and d["trip"]["country"] == "일본" and d["trip"]["currency"] == "JPY"
    assert d["itinerary"] and set(d["itinerary"][0]) == {"day", "date", "title", "items"}
    assert d["forecast"] and set(d["forecast"][0]) == {"date", "tmin", "tmax", "condition", "pop", "source", "note"}
    assert re.fullmatch(r"도쿄 \d+/\d+~\d+/\d+ · 2박3일", d["summary"])
    raw = json.dumps(d, ensure_ascii=False).lower()
    assert "errors" not in d and "api_key" not in raw and "appid" not in raw and "sk-" not in raw


def test_plan_json_404(client):
    assert client.get("/plan/no-such-thread.json").status_code == 404
    assert client.get("/plan/bad id!.json").status_code == 404
    ask(client, "도쿄 날씨 알려줘", "t-noplan")          # 계획(trip) 없는 대화도 404
    assert client.get("/plan/t-noplan.json").status_code == 404


def test_offline_view_renders_and_rejects_bad(client):
    plan = {"trip": {"destination": "tokyo", "destination_ko": "도쿄", "start_date": START, "end_date": START, "days": 1,
                     "places": ["<b>아사쿠사</b>"], "places_auto": False},
            "itinerary": [{"day": 1, "date": START, "title": "아사쿠사 산책", "items": ["센소지"]}],
            "forecast": [{"date": START, "tmin": 12, "tmax": 20, "condition": "맑음", "pop": 10, "source": "mock", "note": ""}],
            "exchange": None, "details": [{"title": "맛집", "body": "라멘집", "section": "맛집", "day": 1}]}
    r = client.post("/plan/offline", json=plan)
    assert r.status_code == 200
    assert "저장된 계획(오프라인 사본)" in r.text and "센소지" in r.text and "라멘집" in r.text
    assert "계획 수정" not in r.text and "이 기기에서 삭제" in r.text and "<b>아사쿠사</b>" not in r.text
    assert client.post("/plan/offline", json={"x": 1}).status_code == 400
    assert client.post("/plan/offline", content="not json").status_code == 400


def test_planstore_code_and_delete_dialog_present(client):
    js = client.get("/static/js/app.js").text
    assert "var PlanStore" in js and "smart-travel:plans" in js and "window.PlanStore" in js
    assert "MAX = 20" in js and "JSON.parse" in js and js.count("try {") >= 4 and "alert(" not in js
    assert "/plan/offline" in js and "restoreOffline" in js and "savePlan" in js
    for html in (client.get("/").text, client.get("/planner").text):
        assert '<dialog id="delete-modal"' in html and 'data-action="confirm-delete"' in html
    landing = client.get("/").text
    assert 'id="my-plans"' in landing and "내 여행 계획" in landing
    assert "PlanStore.list" in client.get("/static/js/landing.js").text


def test_trip_bar_has_delete_button(client):
    tid = _tid_of(post_plan(client))
    page = client.get(f"/planner?thread_id={tid}").text
    assert 'data-action="delete-local-plan"' in page and "이 기기에서 삭제" in page and f'id="chat-session" hidden data-thread="{tid}"' in page
