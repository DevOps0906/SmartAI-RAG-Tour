"""plan_itinerary - 여행 일정 구성 노드 (FR-10). trip 과 가이드(주요 명소, 일정 예시)로 일차별 일정을 만든다.

규칙 기반이 기본이고, LLM 이 있으면 LLM 으로 만들되 실패하거나 검증에 걸리면 규칙으로 폴백한다.
"""
import json
from datetime import date, timedelta

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.llm import get_llm
from src.nodes.common import pop_task
from src.prompts import PLAN_SYSTEM
from src.rag.guide import guide_itinerary, guide_places, itinerary_by_day, split_items
from src.rag.text import clean_snippet
from src.state import TravelState
from src.trip import md_wd

ARRIVAL = "도착 · 숙소 체크인"
DEPARTURE = "공항 이동 · 출국"
FREE_DAY = "자유 일정 · 취향에 맞춰 카페, 쇼핑, 산책"
_BOOKEND_WORDS = ("도착", "체크인", "공항", "출국", "귀국", "입국")
MAX_AUTO_PLACES = 8


class _LlmDay(BaseModel):
    title: str
    items: list[str] = Field(min_length=1)
    note: str = ""


class _LlmPlan(BaseModel):
    days: list[_LlmDay]


def _example_by_day(state: TravelState, city: str) -> dict[int, str]:
    """일정 예시: 검색된 rag_docs 의 청크를 우선 쓰고, 일차가 비면 가이드 파일에서 보장한다."""
    text = "\n".join(d["content"] for d in state.get("rag_docs") or []
                     if d.get("section") == "일정 예시" and d.get("city") == city)
    by_day = itinerary_by_day(text)
    return by_day or guide_itinerary(city)


def _spread(places: list[str], days: int) -> list[list[str]]:
    """장소를 일차에 고르게 나눈다 (앞 일차부터 한 곳씩 더 가져간다)."""
    base, extra = divmod(len(places), days)
    out, i = [], 0
    for d in range(days):
        n = base + (1 if d < extra else 0)
        out.append(places[i:i + n])
        i += n
    return out


def _place_item(name: str, desc: dict[str, str]) -> str:
    short = clean_snippet(desc.get(name, ""), 34)
    return f"{name} · {short}" if short else name


def _note(state: TravelState, iso: str) -> str:
    """해당 날짜의 예보/기후를 한 줄로. 없으면 빈 문자열."""
    for f in state.get("forecast") or []:
        if f.get("date") != iso:
            continue
        if f.get("source") == "climate":
            return clean_snippet(f.get("note", ""), 70)
        rain = f.get("pop", 0) >= 50 or any(w in (f.get("condition") or "") for w in ("비", "눈", "소나기"))
        label = "예상" if f.get("source") == "mock" else "예보"
        return f"{label} {f['tmin']}~{f['tmax']}° {f['condition']}" + (", 우산 지참" if rain else "")
    return ""


def rule_itinerary(state: TravelState, trip: dict, places: list[str]) -> list[dict]:
    city, n = trip["destination"], int(trip["days"])
    start = date.fromisoformat(trip["start_date"])
    desc = {p["name"]: p["desc"] for p in guide_places(city)}
    example = _example_by_day(state, city)
    spare = [p["name"] for p in guide_places(city) if p["name"] not in places]   # 일정 예시가 모자랄 때 채울 명소
    out: list[dict] = []
    for i, chosen in enumerate(_spread(places, n), start=1):
        iso = (start + timedelta(days=i - 1)).isoformat()
        first, last = i == 1 and n >= 1, i == n and n > 1
        items: list[str] = []
        if first:
            items.append(ARRIVAL)
        items += [_place_item(p, desc) for p in chosen]
        if not chosen:   # 선택 장소가 없는 일차는 가이드 일정 예시 항목으로 채운다
            fill = [x for x in split_items(example.get(i, ""))
                    if not any(w in x for w in _BOOKEND_WORDS)]
            if not fill and spare:
                fill = [_place_item(spare.pop(0), desc)]
            items += fill or ([] if first or last else [FREE_DAY])
        if last:
            items.append(DEPARTURE)
        names = [p for p in chosen] or [x for x in items if x not in (ARRIVAL, DEPARTURE, FREE_DAY)]
        title = " · ".join(re_short(x) for x in names[:2]) or ("도착과 첫 일정" if first else "마무리와 출국" if last else "자유 일정")
        out.append({"day": i, "date": iso, "title": title, "items": items, "note": _note(state, iso)})
    return out


def re_short(item: str) -> str:
    """항목 문자열에서 장소명 부분만 (' · ' 앞)."""
    return item.split(" · ")[0].strip()


def _llm_itinerary(state: TravelState, trip: dict, places: list[str]) -> list[dict]:
    llm = get_llm(temperature=0.3).with_structured_output(_LlmPlan)
    ctx = {"trip": trip, "places": places,
           "guide_places": guide_places(trip["destination"]),
           "example": {str(k): v for k, v in _example_by_day(state, trip["destination"]).items()},
           "forecast": state.get("forecast") or []}
    plan = llm.invoke([SystemMessage(content=PLAN_SYSTEM),
                       HumanMessage(content=json.dumps(ctx, ensure_ascii=False))])
    n = int(trip["days"])
    if len(plan.days) != n:
        raise ValueError("일수 불일치")
    start = date.fromisoformat(trip["start_date"])
    out = [{"day": i, "date": (start + timedelta(days=i - 1)).isoformat(), "title": d.title.strip()[:40],
            "items": [x.strip() for x in d.items if x.strip()], "note": d.note.strip()[:80]}
           for i, d in enumerate(plan.days, start=1)]
    blob = " ".join(x for d in out for x in d["items"])
    if any(not d["items"] for d in out) or not all(p in blob for p in places):
        raise ValueError("선택 장소 누락")
    return out


def plan_itinerary(state: TravelState) -> dict:
    trip = state.get("trip")
    base = {"pending_intents": pop_task(state, "plan"), "step_count": state.get("step_count", 0) + 1}
    if not trip:
        return {**base, "itinerary": []}
    trip = dict(trip)
    places = list(trip.get("places") or [])
    if not places:   # 장소를 고르지 않았으면 가이드 주요 명소에서 추천한다
        places = [p["name"] for p in guide_places(trip["destination"])][:min(MAX_AUTO_PLACES, max(2, trip["days"] * 2))]
        trip["places"], trip["places_auto"] = places, True
    try:
        itinerary = _llm_itinerary(state, trip, places)
    except Exception:   # LLMUnavailable, 네트워크, 검증 실패 모두 규칙 기반으로 폴백 (NFR-02)
        itinerary = rule_itinerary(state, trip, places)
    return {**base, "itinerary": itinerary, "trip": trip}
