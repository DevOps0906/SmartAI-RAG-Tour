"""rag_search - 목적지 RAG 검색 (FR-03)."""
from src.config import get_settings
from src.nodes.common import add_error, pop_task
from src.rag.retriever import ITINERARY_SECTION, itinerary_docs, search_guides, section_docs
from src.state import TravelState

PLACES_SECTION = "주요 명소"


def _ensure_sections(docs: list, dest: str, sections: list[str]) -> list:
    """검색 결과에 없는 섹션은 레지스트리 도시의 해당 섹션 청크로 보충한다."""
    have = {d["section"] for d in docs}
    for sec in sections:
        if sec not in have:
            docs = docs + (itinerary_docs(dest) if sec == ITINERARY_SECTION else section_docs(dest, sec))
    return docs


def rag_search(state: TravelState) -> dict:
    s = get_settings()
    ent = state.get("entities", {})
    dest = ent.get("destination")
    query = " ".join([state["user_input"], *ent.get("interests", [])]).strip()
    docs, errors = [], state.get("errors", [])
    detail = state.get("detail_request") or {}
    try:
        k = s.rag_top_k + 4 if detail else s.rag_top_k
        docs = search_guides(query, destination=dest, k=k)
        if dest and not docs:
            docs = search_guides(query, destination=None, k=k)
        if dest and detail:
            # 상세 요청: 주제에 맞는 섹션을 반드시 포함한다 (일정이나 날씨는 다시 계산하지 않는다)
            docs = _ensure_sections(docs, dest, list(detail.get("sections") or []))
        else:
            # 일정 요청(기간 지정 또는 itinerary 의도)이면 그 도시의 일정 예시를 반드시 포함한다
            wants_itin = (bool(ent.get("days")) or state.get("intent") == "itinerary"
                          or any(w in state.get("user_input", "") for w in ("일정", "코스", "스케줄")))
            if dest and wants_itin and not any(d["section"] == ITINERARY_SECTION for d in docs):
                docs = docs + itinerary_docs(dest)
            if dest and state.get("plan_request"):   # 계획 생성: 주요 명소도 보장
                docs = _ensure_sections(docs, dest, [PLACES_SECTION])
    except Exception as exc:  # 인덱스/임베딩 실패 -> 계속 진행 (NFR-02). 클래스명만 기록.
        errors = add_error(state, f"rag_search: {type(exc).__name__}")
    return {"rag_docs": docs, "pending_intents": pop_task(state, "rag"),
            "errors": errors, "step_count": state.get("step_count", 0) + 1}
