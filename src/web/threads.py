"""체크포인터에 저장된 대화(thread) 조회: 목록, 제목, 대화 복원, 보드 복원. (개발서 17.3)

별도 표 없이 체크포인트(messages, 각 턴의 weather/exchange/rag_docs)만 읽는다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage

from src.destinations import PICK_PHRASE

THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TITLE_LEN = 30
PAGE_SIZE = 30


def valid_thread_id(tid: str | None) -> bool:
    return bool(tid and THREAD_ID_RE.match(tid))


def _cfg(tid: str) -> dict:
    return {"configurable": {"thread_id": tid}}


def _thread_ids(cp) -> list[str]:
    conn = getattr(cp, "conn", None)
    if conn is not None:  # SqliteSaver: 전체 체크포인트를 읽지 않고 id 만 조회
        with cp.lock:
            return [r[0] for r in conn.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()]
    seen: dict[str, None] = {}
    for t in cp.list(None):
        seen[t.config["configurable"]["thread_id"]] = None
    return list(seen)


def _first_human(messages) -> str:
    for m in messages or []:
        if isinstance(m, HumanMessage):
            return str(m.content).strip()
    return ""


def rel_time(ts: str | None, now: datetime | None = None) -> str:
    if not ts:
        return ""
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    sec = max(0, int(((now or datetime.now(timezone.utc)) - t).total_seconds()))
    if sec < 60:
        return "방금"
    if sec < 3600:
        return f"{sec // 60}분 전"
    if sec < 86400:
        return f"{sec // 3600}시간 전"
    days = sec // 86400
    return "어제" if days == 1 else f"{days}일 전"


def _created_ts(cp, tid: str, fallback: str) -> str:
    """스레드의 첫 체크포인트 시각(= 만든 시각). 못 구하면 fallback(마지막 체크포인트 시각)."""
    try:
        conn = getattr(cp, "conn", None)
        if conn is not None:
            with cp.lock:
                row = conn.execute("SELECT checkpoint_id FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = '' "
                                   "ORDER BY checkpoint_id ASC LIMIT 1", (tid,)).fetchone()
            tup = cp.get_tuple({"configurable": {"thread_id": tid, "checkpoint_ns": "", "checkpoint_id": row[0]}}) if row else None
        else:
            tups = list(cp.list(_cfg(tid)))
            tup = tups[-1] if tups else None
        return (tup.checkpoint.get("ts") if tup else "") or fallback
    except Exception:  # noqa: BLE001 - 시각 표시용이라 실패해도 목록은 그린다
        return fallback


def list_threads(cp) -> list[dict]:
    """체크포인터의 모든 대화를 만든 시각 최근 순으로. 메시지가 없는 스레드는 제외한다.

    각 항목: thread_id, title(첫 사용자 메시지 앞 30자), kind("trip"|"chat"), ts(만든 시각), updated_at(상대 표기),
    trip 이 있으면 summary("파리 10/16~10/19 · 3박4일")와 places(앞 3곳).
    """
    from src.web.plans import summary_of   # 순환 import 방지
    rows = []
    for tid in _thread_ids(cp):
        tup = cp.get_tuple(_cfg(tid))
        if tup is None:
            continue
        values = tup.checkpoint.get("channel_values") or {}
        title = _first_human(values.get("messages"))
        if not title:
            continue
        last = tup.checkpoint.get("ts") or ""
        row = {"thread_id": tid, "title": title[:TITLE_LEN], "ts": _created_ts(cp, tid, last), "kind": "chat"}
        trip = values.get("trip")
        if isinstance(trip, dict) and trip.get("start_date") and trip.get("end_date"):
            try:
                row.update(kind="trip", summary=summary_of(trip), places=list(trip.get("places") or [])[:3],
                           places_auto=bool(trip.get("places_auto")))
            except (KeyError, TypeError, ValueError):
                pass
        rows.append(row)
    rows.sort(key=lambda r: r["ts"], reverse=True)
    for r in rows:
        r["updated_at"] = rel_time(r["ts"])
    return rows


def history_rows(cp) -> list[dict]:
    """내 여행 기록 순서: 여행 계획 thread(최근 순) 다음에 일반 대화(최근 순)."""
    rows = list_threads(cp)
    return [r for r in rows if r["kind"] == "trip"] + [r for r in rows if r["kind"] != "trip"]


def has_thread(cp, tid: str) -> bool:
    return valid_thread_id(tid) and cp.get_tuple(_cfg(tid)) is not None


def delete_thread(cp, tid: str) -> bool:
    """체크포인터에서 thread 를 지운다. 없으면 False."""
    if not has_thread(cp, tid):
        return False
    cp.delete_thread(tid)
    return True


def restore(graph, tid: str) -> dict:
    """대화 + 보드 State 복원. 반환: {messages: [{role,text}], state: {...}} (없으면 messages 빈 목록).

    build_input 이 턴마다 weather/exchange/rag_docs 를 비우므로, 보드는 체크포인트 이력을 최신부터 훑어
    카드별로 가장 최근에 값이 있던 턴의 것을 모은다.
    """
    snap = graph.get_state(_cfg(tid))
    values = snap.values if snap else {}
    msgs = []
    for m in values.get("messages") or []:
        if isinstance(m, HumanMessage):
            msgs.append({"role": "user", "text": str(m.content)})
        elif isinstance(m, AIMessage) and str(m.content).strip():
            text = str(m.content)
            msgs.append({"role": "assistant", "text": text, "pick": PICK_PHRASE in text})  # 미지원 안내 말풍선은 선택 카드 복원
    if not msgs:
        return {"messages": [], "state": {}}

    trip = values.get("trip") or None
    weather = exchange = None
    guide: list = []
    itin: list = []
    dest = (trip or {}).get("destination") or (values.get("entities") or {}).get("destination")
    for h in graph.get_state_history(_cfg(tid)):
        v = h.values or {}
        if v.get("intent") == "detail":
            continue   # 상세 요청 턴의 검색 결과는 가이드 카드에 섞지 않는다
        if dest and ((v.get("entities") or {}).get("destination") or dest) != dest:
            if trip:
                continue   # 계획 대화: 다른 도시를 물은 턴만 건너뛴다
            break  # 이전 도시의 결과는 현재 보드에 섞지 않는다
        weather = weather or v.get("weather")
        exchange = exchange or v.get("exchange")
        docs = v.get("rag_docs") or []
        guide = guide or [d for d in docs if d.get("section") != "일정 예시"]
        itin = itin or [d for d in docs if d.get("section") == "일정 예시"]
        if weather and exchange and guide and itin:
            break
    state = {
        "entities": values.get("entities") or {}, "weather": weather, "exchange": exchange,
        "rag_docs": guide + itin, "final_answer": values.get("final_answer", ""), "errors": [],
    }
    if trip:
        state.update(trip=trip, itinerary=values.get("itinerary") or [], forecast=values.get("forecast") or [],
                     details=values.get("details") or [])
    return {"messages": msgs, "state": state}
