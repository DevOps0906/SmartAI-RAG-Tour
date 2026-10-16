"""여행 계획(trip): /places, /plan 검증, plan 흐름, 기간 예보, 상세 요청, 보드, debug. 키/네트워크 없음."""
import re
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src import trip as trip_mod
from src.config import get_settings
from src.main import build_input, format_plan
from src.tools import weather as wx
from src.web import routes
from tests.test_web import ask, client, dict_events  # noqa: F401  (client 픽스처 재사용)

A, R, W, X, P, F = ("analyze_input", "rag_search", "weather_tool", "exchange_tool", "plan_itinerary", "generate_answer")
@pytest.fixture(autouse=True)
def _clear_pending():
    routes.PENDING_TRIP.clear()
    yield
    routes.PENDING_TRIP.clear()


TODAY = date.today()
START = (TODAY + timedelta(days=1)).isoformat()


def mk_trip(dest="tokyo", days=4, places=("아사쿠사", "시부야"), start=START):
    return trip_mod.build_trip(dest, start, days, list(places))


def run_plan(graph, trip, tid="t-plan"):
    cfg = {"configurable": {"thread_id": tid}, "recursion_limit": 25}
    path = []
    for upd in graph.stream(build_input(trip_mod.summary_text(trip), trip=trip), cfg, stream_mode="updates"):
        path.extend(upd.keys())
    return graph.get_state(cfg).values, path


# ---------------------------------------------------------------- /places

def test_places_chips(client):
    r = client.get("/places?city=tokyo")
    assert r.status_code == 200
    for name in ("아사쿠사", "시부야", "신주쿠", "하라주쿠"):
        assert f'value="{name}"' in r.text
    assert 'type="checkbox" name="places"' in r.text and ".txt" not in r.text
    paris = client.get("/places?city=paris").text      # '### 이름' 형식 가이드
    assert 'value="에펠탑"' in paris and 'value="기타"' not in paris
    sel = client.get("/places?city=tokyo&selected=시부야&selected=롯폰기").text
    assert re.search(r'value="시부야"[^>]*checked', sel) and re.search(r'value="롯폰기"[^>]*checked', sel)
    assert "먼저 골라" in client.get("/places").text
    assert "지원하지 않는" in client.get("/places?city=london").text


# ---------------------------------------------------------------- /plan 검증

def post_plan(client, **kw):
    data = {"destination": "tokyo", "start_date": START, "days": "3", "places": ["아사쿠사"], "places_text": ""}
    data.update(kw)
    return client.post("/plan", data=data, headers={"HX-Request": "true", "HX-Current-URL": "http://testserver/"}, follow_redirects=False)


def test_plan_ok_redirects_with_new_thread(client):
    r = post_plan(client, places=["아사쿠사", "시부야"], places_text="롯폰기, 시부야")
    assert r.status_code == 200 and re.fullmatch(r"/planner\?thread_id=[0-9a-f]{32}&p=[\w.-]+", r.headers["HX-Redirect"])
    tid = r.headers["HX-Redirect"].split("thread_id=")[1].split("&")[0]
    trip = routes.PENDING_TRIP[tid]
    assert trip["places"] == ["아사쿠사", "시부야", "롯폰기"] and trip["days"] == 3 and trip["nights"] == 2
    assert trip["end_date"] == (TODAY + timedelta(days=3)).isoformat()      # end_date 는 서버 계산값
    assert "3일차" not in routes.PENDING[tid] and "도쿄" in routes.PENDING[tid] and "2박3일" in routes.PENDING[tid]
    plain = client.post("/plan", data={"destination": "tokyo", "start_date": START, "days": "1"}, follow_redirects=False)
    assert plain.status_code == 303 and plain.headers["location"].startswith("/planner?thread_id=")


@pytest.mark.parametrize("days,ok", [("1", True), ("5", True), ("0", False), ("6", False), ("x", False)])
def test_plan_days_boundary(client, days, ok):
    r = post_plan(client, days=days)
    assert (r.status_code == 200) is ok and (ok or r.status_code == 400)


@pytest.mark.parametrize("kw,msg", [
    ({"destination": "london"}, "지원하지 않는 여행지"),
    ({"destination": ""}, "지원하지 않는 여행지"),
    ({"start_date": "2026/10/20"}, "YYYY-MM-DD"),
    ({"start_date": (TODAY - timedelta(days=1)).isoformat()}, "오늘 이후"),
    ({"days": "6"}, "5일차까지"),
    ({"places": [f"장소{i}" for i in range(11)]}, "최대 10곳"),
    ({"places": ["가" * 31]}, "30자"),
])
def test_plan_rejects(client, kw, msg):
    r = post_plan(client, **kw)
    assert r.status_code == 400 and msg in r.text and not routes.PENDING_TRIP


def test_plan_exactly_ten_places_ok(client):
    assert post_plan(client, places=[f"장소{i}" for i in range(10)]).status_code == 200


# ---------------------------------------------------------------- plan 흐름 (그래프)

def test_plan_path_and_itinerary(graph):
    trip = mk_trip(days=4)
    st, path = run_plan(graph, trip)
    assert path == [A, R, W, X, P, F]
    assert st["intent"] == "itinerary" and st["entities"]["amount_assumed"] and st["entities"]["amount"] == 1_000_000
    it = st["itinerary"]
    assert len(it) == 4 == len(st["forecast"])
    assert [d["day"] for d in it] == [1, 2, 3, 4]
    assert [d["date"] for d in it] == [(TODAY + timedelta(days=1 + i)).isoformat() for i in range(4)]
    blob = " ".join(x for d in it for x in d["items"])
    assert "아사쿠사" in blob and "시부야" in blob
    assert "도착" in it[0]["items"][0] and "출국" in it[-1]["items"][-1]
    assert all(d["items"] and d["title"] for d in it)
    assert st["trip"]["places_auto"] is False and "일정을 만들었어요" in st["final_answer"]
    assert "출처" not in st["final_answer"]


@pytest.mark.parametrize("city,days", [("tokyo", 3), ("paris", 5), ("bangkok", 2), ("newyork", 5), ("jeju", 1)])
def test_itinerary_length_equals_days_every_city(graph, city, days):
    st, _ = run_plan(graph, mk_trip(city, days, places=()), tid=f"t-{city}")
    assert len(st["itinerary"]) == days == len(st["forecast"])


def test_empty_places_auto_recommend(graph):
    st, path = run_plan(graph, mk_trip(days=3, places=()))
    assert path == [A, R, W, X, P, F]
    trip = st["trip"]
    assert trip["places_auto"] is True and trip["places"]
    assert all(p in " ".join(x for d in st["itinerary"] for x in d["items"]) for p in trip["places"])
    assert "추천" in st["final_answer"]


def test_more_days_than_example_still_filled(graph):
    st, _ = run_plan(graph, mk_trip("jeju", 5, places=("성산일출봉",)))   # 제주 일정 예시는 3일
    assert len(st["itinerary"]) == 5 and all(d["items"] for d in st["itinerary"])


def test_trip_persists_and_is_replaced(graph, run):
    tid = "t-keep"
    run_plan(graph, mk_trip(days=2), tid=tid)
    st, path = run("환율은?", tid)
    assert st["trip"]["destination"] == "tokyo" and len(st["itinerary"]) == 2 and path == [A, X, F]
    run_plan(graph, mk_trip("paris", 3, places=()), tid=tid)
    cfg = {"configurable": {"thread_id": tid}}
    now = graph.get_state(cfg).values
    assert now["trip"]["destination"] == "paris" and len(now["itinerary"]) == 3


def test_analyze_skips_parsing_for_plan(monkeypatch):
    from src.nodes import analyze as an

    def boom(*a, **k):
        raise AssertionError("LLM/규칙 파싱을 건너뛰어야 한다")
    monkeypatch.setattr(an, "_llm_analyze", boom)
    monkeypatch.setattr(an, "rule_based_analyze", boom)
    out = an.analyze_input({"user_input": "아무 말", "trip": mk_trip(), "plan_request": True})
    assert out["pending_intents"] == ["rag", "weather", "exchange", "plan"]
    assert out["entities"]["destination"] == "tokyo" and out["entities"]["currency"] == "JPY" and out["entities"]["days"] == 4


def test_router_plan_task():
    from src.nodes.router import route_by_intent
    assert route_by_intent({"pending_intents": ["plan"]}) == "plan_itinerary"
    assert "plan_itinerary" in {e.target for e in __import__("src.graph", fromlist=["x"]).build_graph().get_graph().edges}


def test_cli_format_plan(graph):
    st, _ = run_plan(graph, mk_trip(days=2))
    text = format_plan(st)
    assert "== 일정 ==" in text and "== 여행기간중 날씨현황 ==" in text and "1일차" in text and "2일차" in text


def test_llm_itinerary_used_then_falls_back(graph, monkeypatch):
    from src.nodes import plan_node
    trip = mk_trip(days=2, places=("아사쿠사",))

    def bad(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(plan_node, "_llm_itinerary", bad)
    st, _ = run_plan(graph, trip, tid="t-fb")
    assert len(st["itinerary"]) == 2          # 규칙 기반 폴백
    good = [{"day": i, "date": d, "title": "LLM", "items": ["아사쿠사"], "note": ""}
            for i, d in enumerate(trip_mod.trip_dates(trip), 1)]
    monkeypatch.setattr(plan_node, "_llm_itinerary", lambda *a, **k: good)
    st, _ = run_plan(graph, trip, tid="t-llm")
    assert st["itinerary"][0]["title"] == "LLM"


# ---------------------------------------------------------------- 기간 예보

def _payload(first_day: date, n_days: int, tz=32400):
    """OpenWeather /forecast 모양: 하루 3개씩(현지 03/12/21시), 기온·확률은 날짜마다 다르게."""
    items = []
    for i in range(n_days):
        d = first_day + timedelta(days=i)
        for hour, tmin, tmax, pop, desc in ((3, 10 + i, 12 + i, 0.1, "맑음"), (12, 15 + i, 20 + i, 0.6 if i == 0 else 0.2, "구름 조금"),
                                            (21, 11 + i, 14 + i, 0.3, "구름 조금")):
            local = datetime(d.year, d.month, d.day, hour, tzinfo=timezone(timedelta(seconds=tz)))
            items.append({"dt": int(local.timestamp()), "main": {"temp": tmax, "temp_min": tmin, "temp_max": tmax},
                          "weather": [{"description": desc}], "pop": pop})
    return {"list": items, "city": {"timezone": tz}}


def test_aggregate_forecast_by_local_date():
    agg = wx.aggregate_forecast(_payload(date(2026, 10, 17), 3))
    assert sorted(agg) == ["2026-10-17", "2026-10-18", "2026-10-19"]
    d0 = agg["2026-10-17"]
    assert (d0["tmin"], d0["tmax"], d0["pop"], d0["condition"], d0["source"]) == (10, 20, 60, "구름 조금", "forecast")
    assert agg["2026-10-18"]["tmin"] == 11 and agg["2026-10-18"]["pop"] == 30


def test_get_forecast_live_and_climate(monkeypatch):
    monkeypatch.setenv("WEATHER_MODE", "auto")
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-secret-key")
    get_settings.cache_clear()
    start = date(2026, 10, 17)
    calls = []

    def fake_get(url, **kw):
        calls.append((url, kw["params"]))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: _payload(start, 3))
    monkeypatch.setattr(wx.httpx, "get", fake_get)
    res = wx.get_forecast.invoke({"city": "tokyo", "start_date": "2026-10-17", "end_date": "2026-10-21"})
    assert res["ok"] and res["source"] == "live" and len(res["days"]) == 5
    assert [d["source"] for d in res["days"]] == ["forecast"] * 3 + ["climate"] * 2
    assert calls[0][0].endswith("/data/2.5/forecast") and calls[0][1]["lang"] == "kr" and calls[0][1]["units"] == "metric"
    far = res["days"][3]
    assert far["date"] == "2026-10-20" and "tmin" not in far and far["note"]
    assert "10월" in far["note"] or "예보 범위 밖" in far["note"] or "가을" in far["note"]
    assert "dummy-secret-key" not in str(res)


def test_get_forecast_climate_note_out_of_range_text(monkeypatch):
    from src.rag.guide import OUT_OF_RANGE_NOTE, climate_note
    assert "단풍" in climate_note("tokyo", 10)            # 가이드 '가을(10월 말~12월 초)'
    assert "벚꽃" in climate_note("tokyo", 4)
    assert climate_note("tokyo", 5) is None and "5일" in OUT_OF_RANGE_NOTE
    assert "건기" in climate_note("bangkok", 12)           # 11월~2월 (연말 넘김)
    res = wx.get_forecast.invoke({"city": "tokyo", "start_date": "2027-05-01", "end_date": "2027-05-02"})
    assert [d["note"] for d in res["days"]] == [OUT_OF_RANGE_NOTE] * 2 and res["source"] == "mock"


def test_get_forecast_failure_falls_back_to_mock(monkeypatch):
    monkeypatch.setenv("WEATHER_MODE", "auto")
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-secret-key")
    get_settings.cache_clear()

    def down(*a, **k):
        raise wx.httpx.ConnectError("blocked")
    monkeypatch.setattr(wx.httpx, "get", down)
    res = wx.get_forecast.invoke({"city": "paris", "start_date": START, "end_date": (TODAY + timedelta(days=3)).isoformat()})
    assert res["ok"] and res["source"] == "mock" and res["fallback_reason"] == "ConnectError"
    assert len(res["days"]) == 3 and all(d["source"] == "mock" for d in res["days"])
    assert "dummy-secret-key" not in str(res)


def test_get_forecast_validation():
    assert not wx.get_forecast.invoke({"city": "london", "start_date": START, "end_date": START})["ok"]
    assert not wx.get_forecast.invoke({"city": "tokyo", "start_date": "bad", "end_date": START})["ok"]
    assert not wx.get_forecast.invoke({"city": "tokyo", "start_date": START, "end_date": "2000-01-01"})["ok"]


def test_far_trip_all_climate(graph):
    far = (TODAY + timedelta(days=60)).isoformat()
    st, _ = run_plan(graph, mk_trip(days=3, start=far), tid="t-far")
    assert [f["source"] for f in st["forecast"]] == ["climate"] * 3 and all(f["note"] for f in st["forecast"])
    assert all(d["note"] for d in st["itinerary"])


# ---------------------------------------------------------------- 상세 요청 -> details

def test_detail_requests_accumulate(graph, run):
    tid = "t-detail"
    st0, _ = run_plan(graph, mk_trip(days=4), tid=tid)
    before = (st0["itinerary"], st0["forecast"])
    st, path = run("2일차 맛집 더 알려줘", tid)
    assert path == [A, R, F] and st["intent"] == "detail"
    assert len(st["details"]) == 1
    d = st["details"][0]
    assert d["day"] == 2 and d["section"] == "맛집" and d["body"] and d["id"] and d["created_at"].startswith("20")
    assert "라멘" in d["body"] or "스시" in d["body"]
    assert ".txt" not in d["body"] and "**" not in d["body"] and "[도쿄" not in d["body"]
    st, path = run("시부야 쇼핑 정보", tid)
    d2 = st["details"][1]
    assert d2["section"] == "쇼핑" and "day" not in d2 and "시부야" in d2["title"] and "시부야" in d2["body"]
    st, path = run("교통 자세히", tid)
    assert len(st["details"]) == 3 and st["details"][2]["section"] == "교통" and "스이카" in st["details"][2]["body"]
    assert (st["itinerary"], st["forecast"]) == before          # 일정과 날씨는 다시 계산하지 않는다
    assert "weather_tool" not in path and st["weather"] is None


def test_detail_not_triggered_without_trip_or_for_other_topics(run, graph):
    st, path = run("도쿄 맛집 추천해줘", "t-nodetail")
    assert path == [A, R, F] and not st.get("details") and st["intent"] == "recommend"
    tid = "t-weather"
    run_plan(graph, mk_trip(), tid=tid)
    st, path = run("도쿄 날씨 알려줘", tid)
    assert path == [A, W, F] and not st.get("details")
    st, path = run("파리 맛집 추천해줘", tid)               # 다른 도시는 상세 요청이 아니다
    assert st["intent"] != "detail"


def test_detail_llm_path_used_when_available(graph, run, monkeypatch):
    from langchain_core.messages import AIMessage
    from src.nodes import respond
    tid = "t-detail-llm"
    run_plan(graph, mk_trip(days=3), tid=tid)
    fake = SimpleNamespace(invoke=lambda msgs: AIMessage(content="- **라멘집** 추천\n- 현지에서 확인 필요"))
    monkeypatch.setattr(respond, "get_llm", lambda temperature=0.0: fake)
    st, _ = run("맛집 알려줘", tid)
    assert st["details"][-1]["body"] == "라멘집 추천\n현지에서 확인 필요"


# ---------------------------------------------------------------- 웹: 모달 / 보드 / debug

def test_modal_markup(client):
    html = client.get("/planner").text
    m = re.search(r'<dialog id="plan-modal".*?</dialog>', html, re.S)
    assert m
    modal = m.group(0)
    assert 'aria-labelledby="plan-modal-title"' in modal and 'id="plan-modal-title"' in modal
    assert f'min="{TODAY.isoformat()}"' in modal and f'value="{TODAY.isoformat()}"' in modal and 'type="date"' in modal
    assert 'name="end_date"' not in modal                        # 도착일 입력 없음
    days = re.findall(r'role="radio" data-days="(\d)" aria-checked="(true|false)"', modal)
    assert days == [("1", "false"), ("2", "false"), ("3", "true"), ("4", "false"), ("5", "false")]
    for n in range(1, 6):
        assert f">{n}일차</button>" in modal
    assert 'role="radiogroup"' in modal and 'name="days"' in modal and 'name="start_date"' in modal
    assert modal.count('name="destination"') == 5 and 'hx-get="/places?city=tokyo"' in modal
    assert 'id="places-chips"' in modal and "AI가 가이드를 바탕으로 추천해요" in modal and 'name="places_text"' in modal
    assert 'hx-post="/plan"' in modal and "계획 만들기" in modal and 'id="plan-duration"' in modal
    assert html.count('data-action="new-plan"') >= 3             # 헤더 2 + 빈 보드 CTA
    assert "새 여행 계획으로 시작해 보세요" in html and "여행지 선택</h2>" not in html


def test_plan_page_autostart_and_board(client):
    r = post_plan(client, places=["아사쿠사", "시부야"], days="3")
    url = r.headers["HX-Redirect"]
    tid = url.split("thread_id=")[1].split("&")[0]
    page = client.get(url).text
    assert f"/chat/stream?thread_id={tid}" in page and 'data-autostart="true"' in page
    assert re.search(r"도쿄 \d+/\d+~\d+/\d+ 2박3일, 아사쿠사·시부야 포함 계획 만들어줘", page)
    assert 'id="board-trip"' in page and "계획 수정" in page and re.search(r'data-action="edit-plan" data-destination="tokyo" data-start="[0-9-]+" data-days="3" data-places="아사쿠사|시부야"', page)
    assert "안녕하세요! 여행지" not in page and ".txt" not in page
    bl = ask_stream(client, tid)
    boards = "\n".join(h for n, h in bl if n == "board")
    for key in ("board-itinerary", "board-forecast", "board-exchange", 'id="board-trip"', "1일차", "2일차", "3일차"):
        assert key in boards
    assert boards.count('<li id="itin-day-') == 3 and ".txt" not in boards
    fc = [h for n, h in bl if n == "board" and 'id="board-forecast"' in h][-1]
    assert fc.count("일차 <span") == 3                           # 여행기간중 날씨현황도 정확히 N개 행
    assert "여행기간중 날씨현황" in fc and "기간 날씨" not in fc
    assert "예시 데이터" in fc or "예보" in fc
    restored = client.get(f"/?thread_id={tid}").text
    assert "3일차" in restored and 'id="board-forecast"' in restored and ".txt" not in restored
    assert "실행 흐름 보기" not in restored and "analyze_input" not in restored


def ask_stream(client, tid, debug=False):
    from tests.test_web import blocks
    with client.stream("GET", f"/chat/stream?thread_id={tid}" + ("&debug=1" if debug else "")) as s:
        return blocks("".join(s.iter_text()))


def test_detail_board_oob_and_day_link(client):
    r = post_plan(client, places=["아사쿠사"], days="3")
    tid = r.headers["HX-Redirect"].split("thread_id=")[1].split("&")[0]
    ask_stream(client, tid)
    bl = ask(client, "2일차 맛집 더 알려줘", tid)
    names = [n for n, _ in bl]
    assert "node_start" not in names and "node_end" not in names           # 기본 화면은 실행 흐름 없음
    boards = [h for n, h in bl if n == "board"]
    det = [h for h in boards if 'id="board-details"' in h]
    assert det and 'hx-swap-oob="outerHTML"' in det[-1] and "2일차" in det[-1] and "맛집" in det[-1]
    assert not any('id="board-forecast"' in h or 'id="board-guide"' in h or "skeleton" in h for h in boards)
    itin = [h for h in boards if 'id="board-itinerary"' in h]
    assert itin and "요청한 정보 보기" in itin[-1] and 'href="#detail-' in itin[-1]
    page = client.get(f"/?thread_id={tid}").text
    assert 'id="board-details"' in page and "2일차" in page and "요청한 정보 보기" in page and ".txt" not in page
    assert "요청한 정보" in page


def test_debug_flag_controls_execution_flow(client):
    plain = client.get("/planner").text
    assert "실행 흐름" not in plain
    dbg = client.get("/?debug=1").text
    assert 'name="debug" value="1"' in dbg
    # 접수 -> 스트림 연결에 debug 가 전달된다
    r = client.post("/chat", data={"message": "도쿄 날씨", "thread_id": "t-d1", "debug": "1"})
    assert "실행 흐름 보기" in r.text and "thread_id=t-d1&amp;debug=1" in r.text
    r = client.post("/chat", data={"message": "도쿄 날씨", "thread_id": "t-d2"})
    assert "실행 흐름" not in r.text and "debug=1" not in r.text
    bl = ask_stream(client, "t-d1", debug=True)
    assert {"node_start", "node_end"} <= {n for n, _ in bl} and "analyze_input" in "".join(h for _, h in bl)
    assert "총" in dict(bl)["done"]
    bl = ask_stream(client, "t-d2")
    assert not {"node_start", "node_end"} & {n for n, _ in bl} and "analyze_input" not in "".join(h for _, h in bl)
    assert dict(bl)["done"].strip() == ""
    # 사이드바 링크도 debug 유지
    assert "&amp;debug=1" in client.get("/threads?debug=1").text
    # 복원된 말풍선 안에도 실행 흐름은 없다
    assert "실행 흐름" not in client.get("/planner?thread_id=t-d2").text


def test_board_has_no_md_everywhere(client):
    r = post_plan(client, places=[], days="2")
    tid = r.headers["HX-Redirect"].split("thread_id=")[1].split("&")[0]
    bl = ask_stream(client, tid)
    assert ".txt" not in "".join(h for _, h in bl)
    page = client.get(f"/?thread_id={tid}").text
    assert ".txt" not in page and "AI 추천" in page


def test_forecast_card_renders_pop_value_not_dict_method():
    from src.web.app import templates
    html = templates.get_template("partials/card_forecast.html").render(
        s={"forecast": [{"date": "2026-10-16", "tmin": 11, "tmax": 20, "condition": "맑음", "pop": 40, "source": "forecast"}],
           "trip": {"days": 1, "start_date": "2026-10-16", "destination_ko": "파리"}, "weather": None},
        ent={"destination_ko": "파리"}, trip={"days": 1, "start_date": "2026-10-16", "destination_ko": "파리"},
        forecast=[{"date": "2026-10-16", "tmin": 11, "tmax": 20, "condition": "맑음", "pop": 40, "source": "forecast"}],
        loading=False, oob=False, fresh=False, request=None)
    assert "built-in method" not in html


def test_plan_autostarts_on_another_instance_via_token(client):
    """랜딩 POST /plan 뒤 /planner 를 다른 인스턴스가 받아도(메모리 PENDING 없음) 리다이렉트 주소의 토큰으로 계획이 시작된다."""
    url = post_plan(client, places=["아사쿠사"], days="3").headers["HX-Redirect"]
    routes.PENDING.clear()
    routes.PENDING_TRIP.clear()
    page = client.get(url).text
    assert 'data-autostart="true"' in page and "/chat/stream?thread_id=" in page
