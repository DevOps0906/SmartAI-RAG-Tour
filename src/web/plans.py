"""내 여행 계획의 로컬 저장본(브라우저 localStorage `smart-travel:plans`)을 위한 서버 쪽 도우미.

- plan_payload(): 체크포인트 State 에서 저장할 필드만 추린다(API 키, errors, 메시지, 내부 상태는 제외).
- clean_plan(): 브라우저가 보낸 저장본을 화면에 그리기 전에 모양과 길이를 정리한다(신뢰하지 않는다).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from src.destinations import DESTINATIONS
from src.trip import duration_label, md

TRIP_KEYS = ("destination", "destination_ko", "country", "currency", "start_date", "end_date", "days", "nights", "places", "places_auto")
FORECAST_KEYS = ("date", "tmin", "tmax", "condition", "pop", "source", "note")
EXCHANGE_KEYS = ("base", "target", "rate", "amount", "converted", "source")
MAX_ITEMS = 30
MAX_TEXT = 600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def summary_of(trip: dict) -> str:
    """'도쿄 10/16~10/18 · 2박3일'"""
    return f"{trip.get('destination_ko', '')} {md(trip['start_date'])}~{md(trip['end_date'])} · {duration_label(trip)}"


def plan_payload(state: dict, thread_id: str) -> dict | None:
    """계획(trip)이 있는 State 만 저장 대상이다. 없으면 None."""
    trip = state.get("trip")
    if not trip:
        return None
    info = DESTINATIONS.get(trip.get("destination", ""), {})
    t = {k: trip.get(k) for k in TRIP_KEYS}
    t["destination_ko"] = trip.get("destination_ko") or info.get("ko", "")
    t["country"] = info.get("country", "")
    t["currency"] = info.get("currency", "")
    t["places"] = list(trip.get("places") or [])
    t["places_auto"] = bool(trip.get("places_auto"))
    x = state.get("exchange")
    exchange = {k: x.get(k) for k in EXCHANGE_KEYS} if isinstance(x, dict) and x.get("ok") else None
    now = _now()
    return {
        "thread_id": thread_id, "saved_at": now, "updated_at": now, "trip": t,
        "itinerary": [{"day": d.get("day"), "date": d.get("date"), "title": d.get("title"), "items": list(d.get("items") or [])}
                      for d in state.get("itinerary") or []],
        "forecast": [{k: f.get(k) for k in FORECAST_KEYS} for f in state.get("forecast") or []],
        "exchange": exchange,
        "details": [{"title": d.get("title"), "body": d.get("body"), "section": d.get("section"), "day": d.get("day")}
                    for d in state.get("details") or []],
        "summary": summary_of(t),
    }


def _s(v, n: int = MAX_TEXT) -> str:
    return str(v)[:n] if v is not None else ""


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def clean_plan(raw) -> dict | None:
    """브라우저 저장본 -> 보드 State 로 쓸 사전. 모양이 틀리면 None."""
    if not isinstance(raw, dict) or not isinstance(raw.get("trip"), dict):
        return None
    t = raw["trip"]
    try:
        days = max(1, min(int(t.get("days") or 1), 5))
        trip = {"destination": _s(t.get("destination"), 20), "destination_ko": _s(t.get("destination_ko"), 20),
                "start_date": _s(t.get("start_date"), 10), "end_date": _s(t.get("end_date"), 10),
                "days": days, "nights": max(0, days - 1),
                "places": [_s(p, 40) for p in (t.get("places") or [])[:10]], "places_auto": bool(t.get("places_auto"))}
        date.fromisoformat(trip["start_date"]); date.fromisoformat(trip["end_date"])   # 날짜 모양 확인
    except (TypeError, ValueError, IndexError):
        return None
    itin = []
    for d in (raw.get("itinerary") or [])[:MAX_ITEMS]:
        if isinstance(d, dict):
            itin.append({"day": int(_num(d.get("day")) or 0), "date": _s(d.get("date"), 10), "title": _s(d.get("title"), 200),
                         "items": [_s(i, 300) for i in (d.get("items") or [])[:MAX_ITEMS]]})
    fc = []
    for f in (raw.get("forecast") or [])[:MAX_ITEMS]:
        if isinstance(f, dict):
            fc.append({"date": _s(f.get("date"), 10), "tmin": _num(f.get("tmin")), "tmax": _num(f.get("tmax")),
                       "condition": _s(f.get("condition"), 40), "pop": _num(f.get("pop")), "source": _s(f.get("source"), 10),
                       "note": _s(f.get("note"), 300)})
    x = raw.get("exchange")
    exchange = None
    if isinstance(x, dict) and _num(x.get("rate")) and _num(x.get("amount")) is not None and _num(x.get("converted")) is not None:
        exchange = {"ok": True, "base": _s(x.get("base"), 5), "target": _s(x.get("target"), 5), "rate": x["rate"],
                    "amount": x["amount"], "converted": x["converted"], "source": _s(x.get("source"), 10)}
    details = []
    for i, d in enumerate((raw.get("details") or [])[:MAX_ITEMS]):
        if isinstance(d, dict):
            details.append({"id": f"offline-{i}", "title": _s(d.get("title"), 100), "body": _s(d.get("body"), 2000),
                            "section": _s(d.get("section"), 20), "day": int(_num(d.get("day")) or 0) or None})
    return {"trip": trip, "itinerary": itin, "forecast": fc, "exchange": exchange, "details": details}
