"""그래프 실행 -> SSE. 두 층으로 나눈다. (개발서 17.4)

1층 graph_events: 그래프 stream(updates)을 이벤트 사전(dict)으로 변환한다. HTML 없음, 테스트 대상.
2층 render_event: 사전 -> (SSE 이벤트명, HTML 조각) 목록. 기존 partials 를 재사용한다.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import AsyncIterator, Callable

import anyio

from src.destinations import city_ko, supported_destinations
from src.main import build_input
from src.nodes.router import route_by_intent

log = logging.getLogger("smart_travel.web")

LABELS = {
    "analyze_input": "질문 분석", "rag_search": "가이드 검색", "weather_tool": "날씨 조회",
    "exchange_tool": "환율 계산", "plan_itinerary": "일정 구성", "clarify": "되묻기", "generate_answer": "답변 작성",
}
# 노드가 끝나면 갱신되는 보드 카드 (일정 카드는 rag_docs 에 일정 예시가 있을 때만 별도 갱신)
CARD_OF = {"rag_search": ["guide"], "weather_tool": ["weather"], "exchange_tool": ["exchange"],
           "plan_itinerary": ["itinerary"]}
SKELETON_OF = CARD_OF  # 노드 시작 시 스켈레톤을 보이는 카드
TERMINAL = ("generate_answer", "clarify")
ERROR_MESSAGE = "응답을 만들지 못했어요. 잠시 후 다시 시도해 주세요."
PERSISTED = ("trip", "itinerary", "forecast", "details")   # 체크포인트에서 이어받는 계획 관련 필드


def format_sse(event: str, html: str) -> str:
    """SSE 와이어 형식. 여러 줄 data 는 줄마다 'data:' 를 붙인다."""
    lines = html.splitlines() or [""]
    return f"event: {event}\n" + "\n".join(f"data: {ln}" for ln in lines) + "\n\n"


def sources_of(state: dict) -> list[dict]:
    """답변 아래 출처 칩. 교통 섹션은 제외하고 최대 3개."""
    docs = state.get("rag_docs") or []
    return [{"city": city_ko(d.get("city")), "section": d["section"]} for d in docs if d["section"] != "교통"][:3]


def _status(node: str, delta: dict, prev_errors: list[str]) -> tuple[str, str | None]:
    new_errors = [e for e in (delta.get("errors") or []) if e not in prev_errors]
    if node == "analyze_input" and new_errors:
        return "fallback", "규칙 기반 분석으로 대체"
    if new_errors:
        return "error", None
    for key in ("weather", "exchange"):
        res = delta.get(key)
        if isinstance(res, dict) and res.get("source") == "mock":
            return "fallback", "예시 데이터" if key == "weather" else "고정 환율"
    if node == "weather_tool" and any(f.get("source") == "mock" for f in delta.get("forecast") or []):
        return "fallback", "예시 데이터"
    return "success", None


def _iter_in_thread(make_iter: Callable[[], object], stop: threading.Event) -> AsyncIterator:
    """동기 이터레이터를 워커 스레드 하나에서 끝까지 돌리며 이벤트 루프로 항목을 전달한다.
    (제너레이터를 호출마다 다른 스레드에서 next() 하면 contextvars 가 어긋나므로 한 스레드에서만 돌린다.)"""

    async def agen():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def worker():
            try:
                for item in make_iter():
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, ("item", item))
                loop.call_soon_threadsafe(queue.put_nowait, ("end", None))
            except BaseException as exc:  # noqa: BLE001 - 호출 측으로 전달
                loop.call_soon_threadsafe(queue.put_nowait, ("exc", exc))

        task = asyncio.ensure_future(anyio.to_thread.run_sync(worker))
        try:
            while True:
                kind, val = await queue.get()
                if kind == "item":
                    yield val
                elif kind == "exc":
                    raise val
                else:
                    break
        finally:
            stop.set()
            if not task.done():
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    return agen()


async def graph_events(graph, text: str, cfg: dict, trip: dict | None = None) -> AsyncIterator[dict]:
    """graph.stream(stream_mode="updates")를 이벤트 사전으로 변환한다. trip 을 주면 계획 생성 턴이다.

    node_start(node,label) / node_end(node,status,ms,note) / board(card,state) /
    answer(text,sources,clarify,pick) / done(total_ms) / error(message)
    """
    inp = build_input(text, trip=trip)
    state: dict = {}
    try:  # 이번 턴 전의 목적지와 계획. 목적지가 바뀌면 이전 도시 카드를 비운다
        snap = graph.get_state(cfg).values or {}
    except Exception:  # noqa: BLE001 - 체크포인터가 없거나 첫 턴
        snap = {}
    prev_dest = (snap.get("entities") or {}).get("destination")
    state.update({k: snap[k] for k in PERSISTED if snap.get(k)})
    state.update(inp)
    total0 = t0 = time.perf_counter()
    stop = threading.Event()
    quiet = False   # 상세 요청 턴 / 계획과 다른 도시를 물은 턴: 일정·날씨 등 보드 카드는 건드리지 않는다
    yield {"event": "node_start", "node": "analyze_input", "label": LABELS["analyze_input"]}
    try:
        stream = _iter_in_thread(lambda: graph.stream(inp, cfg, stream_mode="updates"), stop)
        async for update in stream:
            for node, delta in update.items():
                delta = delta or {}
                status, note = _status(node, delta, state.get("errors") or [])
                state.update({k: v for k, v in delta.items() if k not in ("messages", "details")})
                if delta.get("details"):
                    state["details"] = [*(state.get("details") or []), *delta["details"]]
                ev = {"event": "node_end", "node": node, "status": status,
                      "ms": int((time.perf_counter() - t0) * 1000)}
                if note:
                    ev["note"] = note
                yield ev
                cur_trip = state.get("trip")
                if node == "analyze_input" and not state.get("needs_clarification"):
                    ent = state.get("entities") or {}
                    other_city = bool(cur_trip) and not state.get("plan_request") and ent.get("destination") != cur_trip.get("destination")
                    quiet = state.get("intent") == "detail" or other_city
                    if ent.get("destination_ko") and not quiet:
                        yield {"event": "board", "card": "header", "state": dict(state)}
                        if prev_dest and ent.get("destination") != prev_dest and not cur_trip:
                            yield {"event": "board", "card": "reset", "state": {"entities": ent}}
                if not quiet:
                    for card in CARD_OF.get(node, []):
                        yield {"event": "board", "card": card, "state": dict(state)}
                    if (node == "rag_search" and not cur_trip
                            and any(d.get("section") == "일정 예시" for d in state.get("rag_docs") or [])):
                        yield {"event": "board", "card": "itinerary", "state": dict(state)}
                if node == "plan_itinerary" and not quiet:   # 장소를 AI 가 채웠다면 요약 바의 칩/배지를 갱신
                    yield {"event": "board", "card": "header", "state": dict(state)}
                if node == "generate_answer" and delta.get("details"):
                    # 요청한 정보 섹션만 갱신한다 (일정 카드는 일차별 '요청한 정보 보기' 링크 때문에 다시 그린다)
                    yield {"event": "board", "card": "details", "state": dict(state)}
                    yield {"event": "board", "card": "itinerary", "state": dict(state), "fresh": False}
                if node in TERMINAL:
                    yield {"event": "answer", "text": state.get("final_answer", ""), "clarify": node == "clarify",
                           "pick": node == "clarify" and state.get("clarify_reason") == "unsupported_destination",
                           "sources": [] if node == "clarify" or quiet else sources_of(state)}
                    continue
                nxt = route_by_intent(state)
                t0 = time.perf_counter()
                yield {"event": "node_start", "node": nxt, "label": LABELS.get(nxt, nxt), "skeleton": not quiet}
    except Exception:  # 최후 방어선 (NFR-02): 원문 예외는 서버 로그에만 남긴다
        log.exception("graph run failed")
        yield {"event": "error", "message": ERROR_MESSAGE}
    finally:
        stop.set()
    yield {"event": "done", "total_ms": int((time.perf_counter() - total0) * 1000)}


# ---------------------------------------------------------------- 2층: 사전 -> HTML 조각

CARD_TEMPLATE = {"weather": "card_weather", "exchange": "card_exchange", "guide": "card_guide", "itinerary": "card_itinerary",
                 "forecast": "card_forecast", "details": "card_details"}
CLASSIC_CARDS = ("weather", "exchange", "guide", "itinerary")


class Renderer:
    """한 번의 스트림 동안 실행 흐름(steps)을 누적하며 사전을 HTML 조각으로 바꾼다.
    debug 가 아니면 실행 흐름(노드/상태/ms)은 HTML 로 내보내지 않는다."""

    def __init__(self, tpl, request, board_context: Callable[[dict], dict], debug: bool = False):
        self.tpl, self.request, self.board_context, self.debug = tpl, request, board_context, debug
        self.steps: list[dict] = []
        self.trip_mode = False
        self._empty_cleared = False

    def _render(self, name: str, **ctx) -> str:
        return self.tpl.get_template(name).render(request=self.request, **ctx)

    def _card(self, card: str, state: dict, loading: bool, fresh: bool | None = None) -> str:
        if card == "weather" and self.trip_mode:
            card = "forecast"   # 계획 보드에서는 현재 날씨가 여행기간중 날씨현황 카드 안에 들어 있다
        ctx = self.board_context(state)
        fresh = (not loading) if fresh is None else fresh
        return self._render(f"partials/{CARD_TEMPLATE[card]}.html", loading=loading, oob=True, fresh=fresh, **ctx)

    def render(self, ev: dict) -> list[tuple[str, str]]:
        out = self._render_event(ev)
        if not self._empty_cleared:
            for i, (name, html) in enumerate(out):
                if name == "board":  # 첫 board 데이터가 오면 보드 상단의 빈 상태 안내문을 지운다
                    self._empty_cleared = True
                    out[i] = (name, html + '<p id="board-empty" hx-swap-oob="delete"></p>')
                    break
        return out

    def _render_event(self, ev: dict) -> list[tuple[str, str]]:
        kind = ev["event"]
        out: list[tuple[str, str]] = []
        if kind == "node_start":
            self.steps.append({"node": ev["node"], "label": ev.get("label"), "status": "running", "ms": None})
            if self.debug:
                out.append(("node_start", self._render("partials/trace.html", steps=self.steps)))
            if ev.get("skeleton", True):
                for card in SKELETON_OF.get(ev["node"], []):
                    out.append(("board", self._card(card, {}, loading=True)))
        elif kind == "node_end":
            for s in reversed(self.steps):
                if s["node"] == ev["node"] and s["status"] == "running":
                    s.update(status=ev["status"], ms=ev["ms"], note=ev.get("note"))
                    break
            if self.debug:
                out.append(("node_end", self._render("partials/trace.html", steps=self.steps)))
        elif kind == "board":
            if (ev.get("state") or {}).get("trip"):
                self.trip_mode = True
            if ev["card"] == "reset":  # 목적지 변경: 이전 도시 카드를 빈 상태로 (이번 턴 결과가 뒤에 다시 채운다)
                for card in CLASSIC_CARDS:
                    out.append(("board", self._card(card, ev["state"], loading=False, fresh=False)))
            elif ev["card"] == "header":
                out.append(("board", self._render("partials/header_title.html", **self.board_context(ev["state"]))))
            else:
                out.append(("board", self._card(ev["card"], ev["state"], loading=False, fresh=ev.get("fresh"))))
        elif kind == "answer":
            out.append(("answer", self._render("partials/stream_msg.html", kind="answer", text=ev["text"], sources=ev["sources"],
                                                                         pick=ev.get("pick"), destinations=supported_destinations())))
        elif kind == "error":
            for s in self.steps:  # 멈춘 단계는 오류로 표시
                if s["status"] == "running":
                    s["status"] = "error"
            out.append(("error", self._render("partials/stream_msg.html", kind="error", message=ev["message"])))
        elif kind == "done":
            out.append(("done", self._render("partials/stream_msg.html", kind="done", total_ms=ev["total_ms"],
                                             debug=self.debug)))
        return out
