"""analyze_input - 입력 분석 (FR-02). LLM 구조화 출력 -> 실패 시 규칙 기반 폴백."""
import re
from datetime import date
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.destinations import (CURRENCY_WORDS, DESTINATIONS, destination_of_currency, find_unsupported,
                              normalize_destination, supported_destinations, unsupported_message)
from src.llm import get_llm
from src.prompts import ANALYZE_SYSTEM
from src.state import Entities, TravelState

SubIntent = Literal["recommend", "weather", "exchange", "itinerary"]
TASK_OF: dict[str, list[str]] = {
    "recommend": ["rag"], "itinerary": ["rag", "weather"],
    "weather": ["weather"], "exchange": ["exchange"],
}
ORDER = ["rag", "weather", "exchange", "plan"]
DEFAULT_AMOUNT = 1_000_000.0

PREFERENCE_QUESTION = ("어떤 여행을 원하세요? 가고 싶은 도시나 취향(휴양, 맛집, 쇼핑, 야경 등)을 알려주시면 "
                       "맞춰서 추천해 드릴게요. 현재 지원 도시: {names}")
DEST_QUESTION = "어느 여행지에 대한 질문인가요? 현재 지원 도시: {names}"


class Analysis(BaseModel):
    intent: Literal["recommend", "weather", "exchange", "itinerary", "multi", "unknown"]
    sub_intents: list[SubIntent] = Field(default_factory=list, description="multi일 때 포함된 개별 의도")
    destination: Optional[str] = Field(None, description="도시명 원문(예: 도쿄, Tokyo)")
    amount: Optional[float] = Field(None, description="환전 금액 (100만원 -> 1000000, 100달러 -> 100)")
    amount_currency: Optional[str] = Field(None, description="amount 의 통화 ISO 코드 (KRW, USD ...)")
    travel_date: Optional[str] = Field(None, description="YYYY-MM-DD 또는 null")
    days: Optional[int] = None
    interests: list[str] = Field(default_factory=list)


_KW = {
    "weather": ["날씨", "기온", "weather", "우산", "더워", "추워", "기후"],
    "exchange": ["환율", "환전", "엔화", "유로", "바트", "달러", "exchange", "예산", "얼마"],
    "itinerary": ["일정", "코스", "계획", "itinerary", "스케줄"],
    "recommend": ["추천", "어디", "가볼", "여행지", "갈만한", "볼거리", "맛집", "명소"],
}
_NIGHTS_RE = re.compile(r"\d+\s*박")
_INTEREST = ["맛집", "음식", "쇼핑", "휴양", "자연", "야경", "미술관", "박물관", "카페", "해변", "액티비티",
             "여름", "겨울", "봄", "가을", "가족", "커플", "혼자", "가성비"]
_DEICTIC = ("거기", "그곳", "그 도시", "여기")

_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_KRW_RE = re.compile(_NUM + r"\s*(만\s*원|천\s*원|만|원)")
_FX_WORDS = sorted((w for w in CURRENCY_WORDS), key=len, reverse=True)
_FX_RE = re.compile(_NUM + r"\s*(" + "|".join(map(re.escape, _FX_WORDS)) + r")", re.I)


def _parse_amount(text: str) -> tuple[Optional[float], Optional[str]]:
    """(금액, 통화코드). 단위(만원/원/달러 ...)가 붙은 숫자만 금액으로 본다 ('3박4일'의 3 을 금액으로 오인하지 않음)."""
    m = _KRW_RE.search(text)
    if m:
        val = float(m.group(1).replace(",", ""))
        unit = re.sub(r"\s", "", m.group(2))
        if unit.startswith("만"):
            val *= 10_000
        elif unit.startswith("천"):
            val *= 1_000
        return (val, "KRW") if val > 0 else (None, None)
    m = _FX_RE.search(text)
    if m:
        val = float(m.group(1).replace(",", ""))
        return (val, CURRENCY_WORDS[m.group(2).lower()]) if val > 0 else (None, None)
    return None, None


def _currency_hint_destination(text: str) -> Optional[str]:
    """'엔화 환율' 처럼 도시 없이 통화만 말한 경우 대응 도시를 추정 (한 글자 '엔' 은 제외)."""
    t = text.lower()
    for w in _FX_WORDS:
        if len(w) >= 2 and w in t:
            return destination_of_currency(CURRENCY_WORDS[w])
    return None


def _parse_days(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*박\s*(\d+)\s*일", text) or re.search(r"(\d+)\s*일(?!정)", text)
    return int(m.groups()[-1]) if m else None


def _parse_date(text: str) -> Optional[str]:
    m = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})\s*월", text)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{date.today().year}-{int(m.group(1)):02d}-15"
    return None


def rule_based_analyze(text: str) -> Analysis:
    t = text.lower()
    amount, cur = _parse_amount(text)
    subs = [k for k, kws in _KW.items() if any(w in t for w in kws)]
    if _NIGHTS_RE.search(t) and "itinerary" not in subs:
        subs.append("itinerary")
    if amount and "exchange" not in subs:
        subs.append("exchange")
    # '일정'이 잡히면 단순 recommend 는 중복이므로 제거
    if "itinerary" in subs and "recommend" in subs:
        subs.remove("recommend")
    has_dest = normalize_destination(text) is not None
    if not subs:
        subs = ["recommend"] if has_dest else []   # 도시만 말하면 추천, 아무 단서 없으면 unknown
    if not subs:
        intent = "unknown"
    else:
        intent = subs[0] if len(subs) == 1 else "multi"
    return Analysis(
        intent=intent, sub_intents=subs if intent == "multi" else [],
        destination=text if has_dest else None,
        amount=amount if "exchange" in subs else None,
        amount_currency=cur if "exchange" in subs else None,
        travel_date=_parse_date(text), days=_parse_days(text),
        interests=[w for w in _INTEREST if w in text],
    )


def _llm_analyze(text: str, prev: Entities) -> Analysis:
    llm = get_llm().with_structured_output(Analysis)
    hint = f"이전 대화에서 확정된 목적지: {prev.get('destination_ko') or '없음'}"
    return llm.invoke([SystemMessage(content=ANALYZE_SYSTEM),
                       HumanMessage(content=f"{hint}\n사용자 입력: {text}")])


# ---- 여행 계획(trip) 대화: 계획 생성 턴과 상세 요청 턴 -----------------------------------------
# (키, 보드 라벨, 질문 키워드, 검색할 가이드 섹션)
DETAIL_TOPICS: list[tuple[str, str, tuple[str, ...], list[str]]] = [
    ("food", "맛집", ("맛집", "음식", "식당", "먹거리", "먹을", "레스토랑", "카페", "디저트", "먹방"), ["음식과 맛집"]),
    ("shopping", "쇼핑", ("쇼핑", "면세", "기념품", "백화점", "아울렛"), ["주요 명소", "추천 이유와 여행 스타일"]),
    ("transport", "교통", ("교통", "지하철", "버스", "택시", "이동", "패스", "교통카드"), ["교통"]),
    ("sights", "명소", ("명소", "볼거리", "관광", "가볼", "구경"), ["주요 명소"]),
    ("budget", "예산", ("예산", "물가", "비용", "경비", "가격"), ["예산과 물가"]),
    ("tips", "팁", ("주의", "매너", "안전", "꿀팁", "여행 팁", "팁"), ["여행 팁과 주의사항"]),
]
_DAY_RE = re.compile(r"(\d+)\s*일\s*차")
_NOT_DETAIL = ("날씨", "기온", "환율", "환전")
_ASK_WORDS = ("알려", "정보", "자세히", "더", "추천", "소개")


def parse_detail_request(text: str, trip: dict) -> Optional[dict]:
    """trip 이 있는 대화에서 '2일차 맛집 더 알려줘' 같은 상세 요청이면 {topic,label,sections,day,place}, 아니면 None."""
    from src.rag.guide import guide_places
    if any(w in text for w in _NOT_DETAIL) or find_unsupported(text):
        return None
    other = normalize_destination(text)
    if other and other != trip.get("destination"):
        return None
    day = None
    m = _DAY_RE.search(text)
    if m and 1 <= int(m.group(1)) <= int(trip.get("days") or 0):
        day = int(m.group(1))
    squeezed = text.replace(" ", "")
    place = None
    names = [*(trip.get("places") or []), *(p["name"] for p in guide_places(trip.get("destination") or ""))]
    for name in names:
        first = re.split(r"[\s,·]", name)[0]
        if name.replace(" ", "") in squeezed or (len(first) >= 2 and first in text):
            place = name
            break
    topic = next((x for x in DETAIL_TOPICS if any(k in text for k in x[2])), None)
    if topic:
        key, label, _, sections = topic
    elif day:
        key, label, sections = "schedule", "일정", ["일정 예시"]
    elif place and any(w in text for w in _ASK_WORDS):
        key, label, sections = "sights", "명소", ["주요 명소"]
    else:
        return None
    return {"topic": key, "label": label, "sections": sections, "day": day, "place": place}


def _plan_turn(state: TravelState) -> dict:
    """모달로 확정한 trip 이 들어온 턴: 파싱을 건너뛰고 엔티티와 작업 큐를 바로 채운다."""
    trip = state["trip"]
    info = DESTINATIONS.get(trip["destination"], {})
    entities: Entities = {
        "destination": trip["destination"], "destination_ko": info.get("ko") or trip.get("destination_ko"),
        "currency": info.get("currency"), "amount": DEFAULT_AMOUNT, "amount_currency": "KRW",
        "amount_assumed": True, "travel_date": None, "days": trip.get("days"), "interests": [],
    }
    return {"intent": "itinerary", "entities": entities, "pending_intents": ["rag", "weather", "exchange", "plan"],
            "needs_clarification": False, "clarify_question": "", "clarify_reason": None,
            "unsupported_destination": None, "detail_request": None, "step_count": 0,
            "errors": list(state.get("errors", []))}


def _detail_turn(state: TravelState, det: dict) -> dict:
    trip = state["trip"]
    info = DESTINATIONS.get(trip["destination"], {})
    ent: Entities = {**(state.get("entities") or {}), "destination": trip["destination"],
                     "destination_ko": info.get("ko") or trip.get("destination_ko"),
                     "currency": info.get("currency"), "interests": [det["label"]]}
    return {"intent": "detail", "entities": ent, "pending_intents": ["rag"], "needs_clarification": False,
            "clarify_question": "", "clarify_reason": None, "unsupported_destination": None,
            "detail_request": det, "step_count": 0, "errors": list(state.get("errors", []))}


def build_pending_intents(intent: str, subs: list[str]) -> list[str]:
    parts = subs if intent == "multi" else [intent]
    tasks = {t for p in parts for t in TASK_OF.get(p, [])}
    return [t for t in ORDER if t in tasks]


def analyze_input(state: TravelState) -> dict:
    text = state["user_input"]
    prev: Entities = state.get("entities") or {}
    if state.get("trip") and state.get("plan_request"):
        return _plan_turn(state)
    if state.get("trip"):
        det = parse_detail_request(text, state["trip"])
        if det:
            return _detail_turn(state, det)
    errors: list[str] = []
    from_llm = True
    try:
        a = _llm_analyze(text, prev)
    except Exception as exc:  # LLMUnavailable, 네트워크, 파싱 오류 모두 폴백 (NFR-02). 클래스명만 기록.
        errors.append(f"analyze_input: 규칙 기반 분석으로 대체 ({type(exc).__name__})")
        a = rule_based_analyze(text)
        from_llm = False

    # LLM 이 multi 인데 세부 의도를 비웠거나, 단일인데 여러 개를 준 경우 보정
    if a.intent == "multi" and not a.sub_intents:
        a.sub_intents = rule_based_analyze(text).sub_intents
    if a.intent != "multi" and len(a.sub_intents) > 1:
        a.intent = "multi"

    tasks = build_pending_intents(a.intent, a.sub_intents)
    needs_dest = any(t in tasks for t in ("weather", "exchange")) or a.intent in ("itinerary", "multi")

    # 목적지: 이번 발화 > (환율이면) 통화명 추정 > 이전 턴 목적지 (목적지가 필요하거나 '거기' 같은 지시어일 때만)
    dest = normalize_destination(a.destination) or normalize_destination(text)
    # 미지원 지명: 사전 매칭 + (LLM 경로) LLM 이 뽑은 destination 이 레지스트리에 없으면 미지원으로 본다
    unsupported = find_unsupported(text)
    raw = (a.destination or "").strip() if from_llm else ""
    if (not unsupported and not dest and raw and len(raw) <= 30
            and raw not in _DEICTIC and not any(w in raw for w in _DEICTIC)):
        unsupported = [raw]
    only_unsupported = bool(unsupported) and not dest   # 지원 도시 없이 미지원 지명만 -> 이전 목적지로 대체하지 않는다
    if not dest and not only_unsupported and "exchange" in tasks:
        dest = _currency_hint_destination(text)
    if not dest and not only_unsupported and (needs_dest or any(w in text for w in _DEICTIC)):
        dest = prev.get("destination")
    info = DESTINATIONS.get(dest) if dest else None

    amount, amount_cur, assumed = a.amount, (a.amount_currency or "KRW").upper(), False
    if "exchange" in tasks and not amount:
        amount, amount_cur, assumed = DEFAULT_AMOUNT, "KRW", True   # 가정값 (respond 에서 가정 명시)
    entities: Entities = {
        "destination": dest,
        "destination_ko": info["ko"] if info else None,
        "currency": info["currency"] if info else None,
        "amount": amount,
        "amount_currency": amount_cur if amount else None,
        "amount_assumed": assumed,
        "travel_date": a.travel_date,
        "days": a.days,
        "interests": a.interests,
    }

    names = ", ".join(d["ko"] for d in supported_destinations())
    clarify, question, reason = False, "", None
    unsup_name = ", ".join(unsupported) if unsupported else None
    if only_unsupported:
        # 보드는 그대로 둔다(이전 entities 유지), clarify 노드가 사유로 문구를 분기한다
        return {
            "intent": a.intent, "entities": dict(prev), "pending_intents": [],
            "needs_clarification": True, "clarify_question": unsupported_message(unsup_name),
            "clarify_reason": "unsupported_destination", "unsupported_destination": unsup_name,
            "step_count": 0, "errors": [*state.get("errors", []), *errors],
        }
    if needs_dest and not dest:
        clarify, question = True, DEST_QUESTION.format(names=names)
    elif (tasks == ["rag"] and not dest and not a.interests and not a.days and not a.travel_date):
        # 도시도 취향도 없는 막연한 추천 요청 -> 취향 되묻기
        clarify, question = True, PREFERENCE_QUESTION.format(names=names)

    return {
        "intent": a.intent, "entities": entities, "pending_intents": tasks,
        "needs_clarification": clarify, "clarify_question": question,
        "clarify_reason": reason, "unsupported_destination": unsup_name,
        "detail_request": None, "step_count": 0, "errors": [*state.get("errors", []), *errors],
    }
