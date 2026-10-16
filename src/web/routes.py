"""웹 라우트. 개발서 17장 기준: POST /chat 은 접수만, 실행·스트림은 GET /chat/stream.
POST /plan 은 모달로 만든 여행 계획을 검증해 새 대화를 만들고(작업실에서는 화면 교체, 랜딩에서는 이동), 계획 생성 스트림을 자동으로 시작한다."""
from __future__ import annotations

import re
import uuid
from datetime import date

from fastapi import APIRouter, Form, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from urllib.parse import quote, urlparse

from src.courses import courses as landing_courses, slides as landing_slides
from src.destinations import DESTINATIONS, find_unsupported, normalize_destination, supported_destinations, supported_keys
from src.rag.guide import guide_places
from src.trip import MAX_DAYS, MAX_PLACES, TripError, build_trip, split_places, summary_text
from src.web import mock, threads as thread_store
from src.web.plans import clean_plan, plan_payload
from src.web.runtime import get_runtime
from src.web.sse import Renderer, format_sse, graph_events

router = APIRouter()

PENDING: dict[str, str] = {}   # thread_id -> 접수된 메시지 (단일 프로세스 전제)
PENDING_TRIP: dict[str, dict] = {}   # thread_id -> POST /plan 이 확정한 trip (스트림이 시작되면 꺼낸다)
RUNNING: set[str] = set()      # 실행 중인 thread_id (같은 대화 동시 실행 방지)

EXAMPLES = [
    "도쿄 날씨 알려줘",
    "50만원이면 엔화로 얼마야?",
    "5월에 맛집 위주로 갈 도시 추천해줘",
    "제주 2박 3일 일정 짜줘",
]
MAX_LEN = 1000


def _tpl(request: Request):
    return request.app.state.templates


def _is_debug(v) -> bool:
    return str(v or "").lower() in ("1", "true", "yes", "on")


def board_context(state: dict) -> dict:
    """State 에서 카드 표시용 파생값(가이드 요약 문서, 일정 일차 목록, 헤더 제목, 계획 보드 값)을 만든다."""
    docs = state.get("rag_docs") or []
    itin = [d for d in docs if d.get("section") == "일정 예시"]
    guide = [d for d in docs if d.get("section") != "일정 예시"][:3]
    # "**1일차**:" 와 "**1일**:" 두 형식을 모두 받고, 여러 청크(겹침 포함)를 일차 기준으로 합친다
    by_day: dict[int, str] = {}
    city = itin[0].get("city") if itin else None
    for d in itin:
        if d.get("city") != city:
            continue
        for m in re.finditer(r"\*\*(\d+)\s*일(?:차)?\*\*\s*[:：]\s*(.+)", d["content"]):
            by_day.setdefault(int(m.group(1)), m.group(2).strip())
    days = [{"label": f"{n}일차", "text": by_day[n]} for n in sorted(by_day)]
    ent = state.get("entities") or {}
    trip = state.get("trip") or None
    if trip:
        cur = DESTINATIONS.get(trip["destination"], {}).get("currency", "")
        title = f"{trip['destination_ko']} · {cur}".rstrip(" ·")
    elif ent.get("destination_ko"):
        title = f"{ent['destination_ko']} · {ent.get('currency') or ''}".rstrip(" ·")
    else:
        title = "여행 작업실"
    cities = list(dict.fromkeys(m.group(1) for d in guide if (m := re.match(r"\s*\[([^\s\]·]+)", d["content"]))))
    guide_city = ent.get("destination_ko") or (cities[0] if len(cities) == 1 else "")
    details = list(state.get("details") or [])
    first_by_day: dict[int, str] = {}
    for d in details:
        if d.get("day"):
            first_by_day.setdefault(int(d["day"]), d["id"])
    return {"s": state, "ent": ent, "guide_city": guide_city, "guide_docs": guide,
            "itin_docs": list({(d.get("source"), d.get("section")): d for d in itin}.values()),
            "itin_days": days, "header_title": title,
            "destinations": supported_destinations(), "selected_dest": ent.get("destination"),
            "trip": trip, "itinerary": state.get("itinerary") or [], "forecast": state.get("forecast") or [],
            "details": list(reversed(details)), "detail_by_day": first_by_day,
            "country": DESTINATIONS.get((trip or {}).get("destination", ""), {}).get("country", "")}


def _new_thread_id() -> str:
    return uuid.uuid4().hex


def _modal_ctx(debug: bool = False) -> dict:
    """계획 모달(partials/plan_modal.html)이 필요로 하는 값. 랜딩과 /planner 가 함께 쓴다."""
    return {"destinations": supported_destinations(), "today": date.today().isoformat(),
            "max_days": MAX_DAYS, "max_places": MAX_PLACES, "debug": debug}


def planner_url(thread_id: str | None = None, debug=False) -> str:
    """여행 작업실 주소. 링크·리다이렉트는 모두 이 함수(또는 같은 형식)를 쓴다."""
    q = []
    if thread_id:
        q.append(f"thread_id={quote(thread_id, safe='')}")
    if _is_debug(debug):
        q.append("debug=1")
    return "/planner" + ("?" + "&".join(q) if q else "")


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request, thread_id: str | None = None, debug: str = ""):
    """메인 랜딩. 예전 주소(/?thread_id=…)로 들어오면 /planner 로 보낸다."""
    if thread_id is not None:
        return RedirectResponse(planner_url(thread_id, debug), status_code=307)
    ctx = _modal_ctx(_is_debug(debug))
    ctx.update(nav_active="landing", contained=True, slides=landing_slides(), courses=landing_courses())
    return _tpl(request).TemplateResponse(request, "landing.html", ctx)


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = ""):
    """GNB 검색창(HTMX 부분 템플릿). 지원 도시면 열기 표식, 아니면 준비 중 안내."""
    text = q.strip()[:50]
    key = normalize_destination(text) if text else None
    ctx = {"q": text, "empty": not text, "dest": None, "unsupported": [], "names": [d["ko"] for d in supported_destinations()]}
    if key:
        ctx["dest"] = {"key": key, "ko": DESTINATIONS[key]["ko"]}
    elif text:
        ctx["unsupported"] = find_unsupported(text)
    return _tpl(request).TemplateResponse(request, "partials/search_result.html", ctx)


def _is_partial(request: Request) -> bool:
    """HTMX 가 작업실 영역만 바꾸려고 부른 요청인가(히스토리 복원 요청은 전체 페이지)."""
    return bool(request.headers.get("HX-Request")) and not request.headers.get("HX-History-Restore-Request")


async def _workspace_ctx(graph, tid: str, debug) -> dict:
    """작업실(보드·요약 바·챗봇 대화) 한 thread 분의 템플릿 값. 체크포인트가 있으면 복원하고, POST /plan 직후면 스트림 자동 시작."""
    restored = await run_in_threadpool(thread_store.restore, graph, tid)
    state = restored["state"]
    # POST /plan 직후: 아직 체크포인트가 없으므로 접수된 trip 으로 계획 보드를 먼저 그리고 스트림을 자동 시작한다
    autostart = bool(not restored["messages"] and tid in PENDING and tid in PENDING_TRIP)
    if autostart:
        state = {"trip": PENDING_TRIP[tid]}
    ctx = board_context(state)
    ctx.update(
        empty=not restored["messages"] and not autostart, thread_id=tid, examples=EXAMPLES,
        messages=restored["messages"], sources=[], loading=autostart, oob=False, fresh=False,
        debug=_is_debug(debug), autostart=autostart, text=PENDING.get(tid) if autostart else None, offline=False,
    )
    return ctx


def _history_ctx(rows: list[dict], thread_id: str | None, debug, offset: int = 0) -> dict:
    """내 여행 기록 패널 값. rows 는 여행 계획 먼저, 대화 나중. 그룹 첫 항목에 group_start 를 달아 제목을 그린다."""
    n_trip = sum(1 for r in rows if r["kind"] == "trip")
    page = rows[offset:offset + thread_store.PAGE_SIZE]
    items = []
    for i, r in enumerate(page, start=offset):
        start = "trip" if i == 0 and r["kind"] == "trip" else "chat" if i == n_trip else ""
        items.append({**r, "group_start": start})
    end = offset + len(page)
    return {"items": items, "thread_id": thread_id, "debug": _is_debug(debug), "trip_count": n_trip,
            "server_ids": [r["thread_id"] for r in rows], "next_offset": end if end < len(rows) else None,
            "remaining": len(rows) - end}


@router.get("/planner", response_class=HTMLResponse)
async def planner(request: Request, thread_id: str | None = None, debug: str = ""):
    """여행 작업실. thread_id 가 없으면 가장 최근 여행 계획 thread, 기록이 없으면 빈 상태(새 대화).
    HTMX 요청이면 작업실 영역(보드, 요약 바, 챗봇 대화)만 돌려준다."""
    graph, cp = get_runtime(request.app)
    rows = await run_in_threadpool(thread_store.history_rows, cp)
    given = thread_store.valid_thread_id(thread_id)
    if given:
        tid = thread_id
    else:
        latest = next((r for r in rows if r["kind"] == "trip"), None)
        tid = latest["thread_id"] if latest else _new_thread_id()
    ctx = await _workspace_ctx(graph, tid, debug)
    if _is_partial(request):
        resp = _tpl(request).TemplateResponse(request, "partials/workspace.html", ctx)
        resp.headers["Vary"] = "HX-Request"
        if not given:   # 주소에 thread_id 가 없었다면 실제로 보여 준 기록의 주소로 바꿔 둔다
            resp.headers["HX-Replace-Url"] = planner_url(None if ctx["empty"] else tid, debug)
        return resp
    ctx.update(_history_ctx(rows, tid, debug), nav_active="planner", contained=False,
               **{k: v for k, v in _modal_ctx().items() if k != "debug"})
    resp = _tpl(request).TemplateResponse(request, "index.html", ctx)
    resp.headers["Vary"] = "HX-Request"
    return resp


@router.get("/threads", response_class=HTMLResponse)
async def threads(request: Request, thread_id: str | None = None, debug: str = "", offset: int = Query(0, ge=0)):
    """내 여행 기록 패널. offset 이 있으면 "더 보기"용 항목(li)만 돌려준다."""
    _, cp = get_runtime(request.app)
    rows = await run_in_threadpool(thread_store.history_rows, cp)
    cur = thread_id if thread_store.valid_thread_id(thread_id) else None
    ctx = _history_ctx(rows, cur, debug, offset)
    name = "partials/history_items.html" if offset else "partials/threads.html"
    return _tpl(request).TemplateResponse(request, name, ctx)


@router.delete("/threads/{thread_id}")
async def delete_thread(request: Request, thread_id: str):
    """기록에서 삭제: 체크포인터의 thread 를 지운다(로컬 사본은 브라우저가 따로 지운다). 없으면 404, 답변 작성 중이면 409."""
    _, cp = get_runtime(request.app)
    if thread_id in RUNNING:
        return JSONResponse({"error": "running"}, status_code=409)
    ok = await run_in_threadpool(thread_store.delete_thread, cp, thread_id)
    if not ok:
        return JSONResponse({"error": "not found"}, status_code=404)
    PENDING.pop(thread_id, None)
    PENDING_TRIP.pop(thread_id, None)
    return JSONResponse({"deleted": thread_id})


@router.get("/places", response_class=HTMLResponse)
async def places(request: Request, city: str = "", selected: list[str] | None = Query(default=None)):
    """모달 3구획: 고른 여행지 가이드 '주요 명소'의 장소 칩(체크박스). selected 는 미리 체크할 값(계획 수정용)."""
    key = city.strip()
    ctx = {"city": key, "chips": [], "message": None, "max_places": MAX_PLACES}
    if not key:
        ctx["message"] = "여행지를 먼저 골라 주세요."
    elif key not in supported_keys():
        ctx["message"] = "지원하지 않는 여행지예요."
    else:
        names = [p["name"] for p in guide_places(key)]
        picked = split_places(selected or [])
        extra = [p for p in picked if p not in names]   # 가이드에 없는 직접 입력 장소도 체크된 칩으로 되살린다
        ctx["chips"] = [{"name": n, "checked": n in picked} for n in [*names, *extra]]
        if not ctx["chips"]:
            ctx["message"] = "이 여행지의 추천 장소가 아직 없어요. 직접 입력해 주세요."
    return _tpl(request).TemplateResponse(request, "partials/places.html", ctx)


def _from_workspace(request: Request) -> bool:
    """요청한 화면이 작업실(/planner)인가. 헤더가 없으면(직접 호출) 작업실로 본다. 랜딩이면 HX-Redirect 로 이동시킨다."""
    cur = request.headers.get("HX-Current-URL")
    return not cur or urlparse(cur).path == "/planner"


@router.post("/plan")
async def plan(request: Request, destination: str = Form(""), start_date: str = Form(""), days: str = Form("3"),
               places: list[str] = Form(default=[]), places_text: str = Form(""), debug: str = Form("")):
    """모달 폼 검증 -> 새 thread_id. 일반 POST 와 랜딩의 HTMX 요청은 /planner?thread_id=… 로 이동시키고,
    작업실의 HTMX 요청은 페이지 이동 없이 작업실을 새 thread 로 교체한다(HX-Push-Url). 실패하면 400 과 오류 조각."""
    try:
        if len(places_text) > 300:
            raise TripError("직접 입력한 장소가 너무 길어요.")
        trip = build_trip(destination, start_date, days, split_places(places, places_text))
    except TripError as exc:
        return _tpl(request).TemplateResponse(request, "partials/plan_error.html", {"error": str(exc)}, status_code=400)
    tid = _new_thread_id()
    PENDING[tid] = summary_text(trip)
    PENDING_TRIP[tid] = trip
    url = planner_url(tid, debug)
    if request.headers.get("HX-Request"):
        if not _from_workspace(request):
            return Response(status_code=200, headers={"HX-Redirect": url})
        graph, _ = get_runtime(request.app)
        ctx = await _workspace_ctx(graph, tid, debug)
        resp = _tpl(request).TemplateResponse(request, "partials/workspace.html", ctx)
        resp.headers.update({"HX-Push-Url": url, "HX-Retarget": "#board-root", "HX-Reswap": "innerHTML", "Vary": "HX-Request"})
        return resp
    return RedirectResponse(url, status_code=303)


@router.get("/plan/{thread_id}.json")
async def plan_json(request: Request, thread_id: str):
    """로컬 저장용: 체크포인트 State 에서 계획 필드만 추려 돌려준다. 없는 thread 나 계획 없는 대화는 404."""
    if not thread_store.valid_thread_id(thread_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    graph, _ = get_runtime(request.app)
    restored = await run_in_threadpool(thread_store.restore, graph, thread_id)
    payload = plan_payload(restored["state"], thread_id)
    if payload is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.post("/plan/offline", response_class=HTMLResponse)
async def plan_offline(request: Request, workspace: str = "", thread_id: str = "", debug: str = ""):
    """브라우저 로컬 저장본(JSON)을 읽기 전용 보드로 그린다. 서버에 저장하지 않는다(서버 DB 가 초기화된 뒤 열람용)."""
    try:
        data = clean_plan(await request.json())
    except ValueError:
        data = None
    if data is None:
        return HTMLResponse("", status_code=400)
    state = {"trip": data["trip"], "itinerary": data["itinerary"], "forecast": data["forecast"],
             "exchange": data["exchange"], "details": data["details"]}
    ctx = board_context(state)
    ctx.update(empty=False, loading=False, oob=False, fresh=False, sources=[], readonly=True, offline=True,
               country=DESTINATIONS.get(data["trip"]["destination"], {}).get("country", ""))
    if workspace:   # 기록 패널에서 열기: 보드와 함께 제목, 대화 스레드, thread 정보도 바꾼다
        tid = thread_id if thread_store.valid_thread_id(thread_id) else _new_thread_id()
        ctx.update(thread_id=tid, offline=True, empty=False, autostart=False, messages=[], examples=[], debug=_is_debug(debug))
        return _tpl(request).TemplateResponse(request, "partials/workspace.html", ctx)
    return _tpl(request).TemplateResponse(request, "partials/offline_plan.html", ctx)


@router.post("/chat", response_class=HTMLResponse)
async def chat(request: Request, message: str = Form(""), thread_id: str = Form(""), debug: str = Form("")):
    text = message.strip()
    tid = thread_id if thread_store.valid_thread_id(thread_id) else _new_thread_id()
    if not (1 <= len(text) <= MAX_LEN):
        return _tpl(request).TemplateResponse(
            request, "partials/message_pair.html",
            {"error": "메시지는 1자 이상 1000자 이하로 입력해 주세요.", "thread_id": tid},
        )
    if tid in RUNNING:
        return _tpl(request).TemplateResponse(
            request, "partials/message_pair.html", {"error": "이전 답변을 만드는 중이에요.", "thread_id": tid}
        )
    PENDING[tid] = text
    resp = _tpl(request).TemplateResponse(request, "partials/message_pair.html",
                                          {"text": text, "thread_id": tid, "debug": _is_debug(debug)})
    resp.headers["HX-Trigger"] = "thread-updated"
    return resp


@router.get("/chat/stream")
async def chat_stream(request: Request, thread_id: str = "", debug: str = ""):
    tpl = _tpl(request)
    graph, _ = get_runtime(request.app)
    renderer = Renderer(tpl, request, board_context, debug=_is_debug(debug))
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}

    async def gen():
        text = PENDING.pop(thread_id, None)
        trip = PENDING_TRIP.pop(thread_id, None)
        if text is None or thread_id in RUNNING:
            for ev in ({"event": "error", "message": "응답을 만들지 못했어요. 잠시 후 다시 시도해 주세요."},
                       {"event": "done", "total_ms": 0}):
                for name, html in renderer.render(ev):
                    yield format_sse(name, html)
            return
        RUNNING.add(thread_id)
        try:
            async for ev in graph_events(graph, text, cfg, trip=trip):
                for name, html in renderer.render(ev):
                    yield format_sse(name, html)
        finally:
            RUNNING.discard(thread_id)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/dev/components", response_class=HTMLResponse)
async def dev_components(request: Request):
    return _tpl(request).TemplateResponse(request, "dev/components.html", {"threads": mock.THREADS, "thread_id": None})
