"""generate_answer - 최종 응답 생성 (FR-07). LLM 실패 시 템플릿 폴백."""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.destinations import unsupported_note
from src.llm import get_llm
from src.rag.text import clean_snippet
from src.prompts import DETAIL_SYSTEM, RESPONSE_SYSTEM
from src.state import TravelState
from src.trip import duration_label, md, md_wd

KST = timezone(timedelta(hours=9))

# 사용자에게 알릴 필요가 없는 내부 정보성 오류(분석 폴백 등)
_INTERNAL_PREFIXES = ("analyze_input:",)


def _user_errors(state: TravelState) -> list[str]:
    return [e for e in state.get("errors", []) if not e.startswith(_INTERNAL_PREFIXES)]


def build_context(state: TravelState) -> str:
    ent = state.get("entities", {})
    parts = [f"[의도] {state.get('intent')}",
             f"[엔티티] {json.dumps(ent, ensure_ascii=False)}"]
    docs = state.get("rag_docs") or []
    if docs:
        body = "\n".join(f"- ({d['city']}/{d['section']}) {d['content']}" for d in docs)
        parts.append(f"[가이드 검색 결과]\n{body}")
    if state.get("weather"):
        parts.append(f"[날씨] {json.dumps(state['weather'], ensure_ascii=False)}")
    if state.get("exchange"):
        parts.append(f"[환율] {json.dumps(state['exchange'], ensure_ascii=False)}")
    errs = _user_errors(state)
    if errs:
        parts.append("[처리 중 문제] " + "; ".join(errs))
    return "\n\n".join(parts)


def _fmt_money(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def _forecast_line(forecast: list[dict]) -> str:
    rows = []
    for f in forecast:
        if f.get("source") == "climate":
            rows.append(f"{md(f['date'])} 예상 기후")
        else:
            rows.append(f"{md(f['date'])} {f['tmin']}~{f['tmax']}° {f['condition']}")
    return ", ".join(rows)


def render_plan_fallback(state: TravelState) -> str:
    """계획 생성 턴의 템플릿 응답: 일정을 일차별로 요약하고 날씨/환율을 덧붙인다."""
    trip, itin = state["trip"], state.get("itinerary") or []
    lines = [f"{trip['destination_ko']} {md(trip['start_date'])}~{md(trip['end_date'])} "
             f"{duration_label(trip)} 일정을 만들었어요. (LLM 없이 생성된 요약)"]
    if trip.get("places_auto"):
        lines.append("- 장소를 고르지 않으셔서 가이드의 주요 명소를 바탕으로 추천했어요.")
    for d in itin:
        lines.append(f"- {d['day']}일차({md_wd(d['date'])}) {d['title']}: " + " / ".join(d["items"]))
    fc = state.get("forecast") or []
    if fc:
        tag = {"mock": "예시 데이터·참고용", "forecast": "예보"}.get(fc[0].get("source"), "예보와 계절 설명")
        lines.append(f"- 여행기간중 날씨현황({tag}): {_forecast_line(fc)}")
    x = state.get("exchange")
    if x:
        lines.append(f"- 환율: {_fmt_money(x['amount'])} {x['base']} = {_fmt_money(x['converted'])} {x['target']} "
                     "(100만원 기준, 참고용)")
    errs = _user_errors(state)
    if errs:
        lines.append("- 일부 정보를 가져오지 못했어요: " + "; ".join(errs))
    return "\n".join(lines)


def _doc_lines(content: str) -> list[str]:
    """가이드 청크를 표시용 줄 목록으로 (접두사/마크다운 제거, 빈 줄 제외)."""
    body = re.sub(r"^\s*\[[^\]]*\]\s*", "", content or "")
    out = []
    for ln in body.splitlines():
        c = clean_snippet(ln, 150)
        if c and len(c) > 1:
            out.append(c)
    return out


def detail_lines(state: TravelState) -> list[str]:
    """상세 요청에 맞는 가이드 줄을 고른다 (주제 키워드, 장소, 해당 일차 일정 단어로 점수화)."""
    from src.nodes.analyze import DETAIL_TOPICS
    det = state.get("detail_request") or {}
    itin = {d["day"]: d for d in state.get("itinerary") or []}
    day_items = (itin.get(det.get("day")) or {}).get("items") or []
    if det.get("topic") == "schedule":
        d = itin.get(det.get("day")) or {}
        lines = [*d.get("items", []), *([d["note"]] if d.get("note") else [])]
        return [clean_snippet(x, 150) for x in lines]
    topic_kw = next((x[2] for x in DETAIL_TOPICS if x[0] == det.get("topic")), ())
    wanted = list(det.get("sections") or [])
    docs = [d for d in state.get("rag_docs") or [] if d["section"] in wanted] or list(state.get("rag_docs") or [])
    docs.sort(key=lambda d: wanted.index(d["section"]) if d["section"] in wanted else 99)
    lines = list(dict.fromkeys(ln for d in docs for ln in _doc_lines(d["content"])))
    tokens = {w for it in day_items for w in re.split(r"[\s·/,]+", it) if len(w) >= 2}

    def score(ln: str) -> int:
        return (3 * bool(det.get("place") and det["place"].split()[0] in ln)
                + (2 * sum(k in ln for k in topic_kw) if det.get("topic") == "shopping" else 0)
                + sum(w in ln for w in tokens))

    scored = sorted(((score(x), i, x) for i, x in enumerate(lines)), key=lambda r: (-r[0], r[1]))
    if det.get("topic") == "shopping":   # 쇼핑은 전용 섹션이 없어 키워드에 걸린 줄만 쓴다
        scored = [r for r in scored if r[0] > 0] or scored
    return [x for _, _, x in scored[:6]]


def detail_title(det: dict) -> str:
    if det.get("topic") == "schedule":
        return f"{det['day']}일차 일정"
    return f"{det['place'] + ' ' if det.get('place') else ''}{det['label']}"


def _clean_block(text: str) -> str:
    return "\n".join(c for c in (clean_snippet(ln, 0) for ln in (text or "").splitlines()) if c)


def _detail_answer(state: TravelState) -> tuple[str, str]:
    """(말풍선 텍스트, 카드 본문). LLM 이 있으면 LLM, 없거나 실패하면 가이드 줄로 만든다."""
    det = state["detail_request"]
    ko = (state.get("trip") or {}).get("destination_ko", "")
    try:
        llm = get_llm(temperature=0.3)
        reply = llm.invoke([SystemMessage(content=DETAIL_SYSTEM),
                            HumanMessage(content=f"사용자 질문: {state['user_input']}\n\n{build_context(state)}")])
        text = reply.content if isinstance(reply.content, str) else "".join(
            b.get("text", "") for b in reply.content if isinstance(b, dict))
        text = text.strip()
        if text:
            return text, _clean_block(text)
    except Exception:
        pass
    lines = detail_lines(state)
    day = f"{det['day']}일차 일정 기준으로 " if det.get("day") and det.get("topic") != "schedule" else ""
    head = f"{ko} {detail_title(det)} 정보를 {day}정리했어요."
    text = head + "\n" + "\n".join(f"- {x}" for x in lines) + "\n보드의 '요청한 정보'에도 담아 두었어요."
    return text, "\n".join(lines)


def render_fallback(state: TravelState) -> str:
    """LLM 없이 State 만으로 만드는 템플릿 응답."""
    if state.get("plan_request") and state.get("trip") and state.get("itinerary"):
        return render_plan_fallback(state)
    ent = state.get("entities", {})
    name = ent.get("destination_ko") or "여행지"
    docs = state.get("rag_docs") or []
    w, x = state.get("weather"), state.get("exchange")

    if state.get("intent") == "unknown" and not (docs or w or x):
        return ("여행 관련 질문을 도와드릴 수 있어요. 예: '도쿄 3박4일 일정 짜줘', '방콕 날씨 어때?', "
                "'파리 100만원이면 몇 유로야?', '여름에 휴양하기 좋은 곳 추천해줘'")

    lines = [f"{name} 관련 안내입니다. (LLM 없이 생성된 요약)"]
    for d in docs[:3]:
        snippet = clean_snippet(d["content"], 160)
        lines.append(f"- {d['section']}: {snippet}")  # 출처 파일은 말풍선 아래 출처 칩으로 보여준다
    if w:
        tag = "예시 데이터·참고용" if w.get("source") == "mock" else "실시간"
        lines.append(f"- 날씨({tag}): {w['condition']}, {w['temp_c']}°C, "
                     f"습도 {w['humidity']}%. {w.get('advice', '')}".rstrip())
    if x:
        tag = "고정 환율·참고용" if x.get("source") == "mock" else "실시간"
        lines.append(f"- 환율({tag}): 1 {x['base']} = {x['rate']:.6g} {x['target']}, "
                     f"{_fmt_money(x['amount'])} {x['base']} = {_fmt_money(x['converted'])} {x['target']}")
        if ent.get("amount_assumed"):
            lines.append("- 금액을 말씀하지 않으셔서 100만원 기준으로 계산했어요.")
        if x["base"] == x["target"]:
            lines.append("- 같은 통화(국내 여행)라 환전이 필요 없어요.")
    if not (docs or w or x):
        lines.append("- 질문을 이해했지만 보여드릴 정보를 찾지 못했어요. 도시와 원하는 정보를 알려주세요.")
    errs = _user_errors(state)
    if errs:
        lines.append("- 일부 정보를 가져오지 못했어요: " + "; ".join(errs))
    return "\n".join(lines)


def _history(state: TravelState) -> list:
    """직전 대화 최근 6개. 현재 턴 입력은 컨텍스트에 따로 넣으므로 제외하고, Anthropic 규칙상 human 으로 시작시킨다."""
    hist = list(state.get("messages", []))[:-1][-6:]
    while hist and not isinstance(hist[0], HumanMessage):
        hist.pop(0)
    return hist


def _detail_turn(state: TravelState) -> dict:
    text, body = _detail_answer(state)
    det = state["detail_request"]
    card = {"id": uuid.uuid4().hex[:8], "title": detail_title(det), "body": body, "section": det["label"],
            "created_at": datetime.now(KST).isoformat(timespec="seconds")}
    if det.get("day"):
        card["day"] = det["day"]
    return {"final_answer": text, "messages": [AIMessage(content=text)], "details": [card]}


def generate_answer(state: TravelState) -> dict:
    if state.get("detail_request") and state.get("trip"):
        return _detail_turn(state)
    ctx = build_context(state)
    try:
        llm = get_llm(temperature=0.3)
        reply = llm.invoke([SystemMessage(content=RESPONSE_SYSTEM), *_history(state),
                            HumanMessage(content=f"사용자 질문: {state['user_input']}\n\n{ctx}")])
        text = reply.content if isinstance(reply.content, str) else "".join(
            b.get("text", "") for b in reply.content if isinstance(b, dict))
        text = text.strip() or render_fallback(state)
    except Exception:
        text = render_fallback(state)
    if state.get("unsupported_destination"):   # 지원 도시와 함께 나온 미지원 지명: 정상 답변 뒤에 한 줄 안내
        text = text + "\n\n" + unsupported_note(state["unsupported_destination"])
    return {"final_answer": text, "messages": [AIMessage(content=text)]}
