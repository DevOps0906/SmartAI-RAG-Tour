"""CLI 진입점. 실행: python main.py  /  python -m src.main  (--trace, --once "질문")"""
import argparse
import sys
import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.destinations import supported_line
from src.graph import build_graph


def build_input(text: str, trip: dict | None = None) -> dict:
    """턴마다 초기화할 필드를 명시. messages 는 add_messages 로 누적, entities/trip/itinerary/forecast/details 는 유지.
    trip 을 주면 계획 생성 턴이다: trip 을 교체하고 이전 일정/예보를 비운다."""
    extra = ({"trip": trip, "plan_request": True, "itinerary": [], "forecast": []} if trip
             else {"plan_request": False})
    return {**extra, "detail_request": None,
        "messages": [HumanMessage(content=text)], "user_input": text,
        "intent": "unknown", "pending_intents": [], "needs_clarification": False,
        "clarify_question": "", "clarify_reason": None, "unsupported_destination": None, "step_count": 0, "rag_docs": [],
        "weather": None, "exchange": None, "errors": [], "final_answer": "",
    }


def _summary(node: str, delta: dict) -> str:
    """--trace 용 한 줄 요약 (State 값만 사용, 키/비밀 없음)."""
    parts = []
    if "intent" in delta:
        parts.append(f"intent={delta['intent']}")
    if node == "rag_search":
        parts.append(f"docs={len(delta.get('rag_docs') or [])}")
    if node == "weather_tool":
        w = delta.get("weather")
        parts.append(f"weather={'ok(' + w['source'] + ')' if w else 'none'}")
    if node == "exchange_tool":
        x = delta.get("exchange")
        parts.append(f"exchange={'ok(' + x['source'] + ')' if x else 'none'}")
    if "pending_intents" in delta:
        parts.append(f"pending={delta['pending_intents']}")
    if delta.get("needs_clarification"):
        parts.append("needs_clarification=True")
    return ", ".join(parts)


def run_turn_state(graph, text: str, thread_id: str, trace: bool = False) -> tuple[str, list[str]]:
    """한 턴 실행. (final_answer, 실행한 노드 경로) 반환. 스트림은 updates 모드로 한 번만 실행한다."""
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
    answer, path, docs, reason = "", [], [], None
    for update in graph.stream(build_input(text), cfg, stream_mode="updates"):
        for node, delta in update.items():
            delta = delta or {}
            path.append(node)
            reason = delta.get("clarify_reason") or reason
            if delta.get("rag_docs"):
                docs = delta["rag_docs"]
            if "final_answer" in delta:
                answer = delta["final_answer"]
            if trace:
                print(f"  [trace] {node}: {_summary(node, delta)}".rstrip(": "))
    if reason == "unsupported_destination" and path and path[-1] == "clarify":
        answer += "\n" + supported_line()   # CLI 는 선택 카드 대신 텍스트로 안내
    if docs and path and path[-1] == "generate_answer":
        # 웹은 출처 칩으로 보여주지만 CLI 는 텍스트 한 줄로 근거를 남긴다
        srcs = dict.fromkeys(f"{d['source']}({d['section']})" for d in docs)
        answer += "\n출처: " + ", ".join(srcs)
    return answer, path


def format_plan(values: dict) -> str:
    """CLI 용: 일정과 여행기간중 날씨현황를 텍스트로."""
    from src.trip import duration_label, md_wd
    trip = values.get("trip") or {}
    lines = [f"[{trip.get('destination_ko')}] {md_wd(trip.get('start_date'))} ~ {md_wd(trip.get('end_date'))} "
             f"· {duration_label(trip)}",
             "장소: " + (", ".join(trip.get("places") or []) or "-") + (" (AI 추천)" if trip.get("places_auto") else "")]
    lines.append("")
    lines.append("== 일정 ==")
    for d in values.get("itinerary") or []:
        lines.append(f"{d['day']}일차 {md_wd(d['date'])} - {d['title']}")
        lines += [f"  - {x}" for x in d["items"]]
        if d.get("note"):
            lines.append(f"  * {d['note']}")
    lines.append("")
    lines.append("== 여행기간중 날씨현황 ==")
    for f in values.get("forecast") or []:
        if f.get("source") == "climate":
            lines.append(f"{md_wd(f['date'])}  예상 기후: {f.get('note')}")
        else:
            tag = "예시" if f.get("source") == "mock" else "예보"
            lines.append(f"{md_wd(f['date'])}  {f['tmin']}~{f['tmax']}°  {f['condition']}  강수 {f['pop']}%  [{tag}]")
    return "\n".join(lines)


def run_plan(graph, trip: dict, thread_id: str, trace: bool = False) -> tuple[dict, list[str]]:
    """계획 생성 턴 실행. (최종 State 값, 노드 경로)"""
    from src.trip import summary_text
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
    path = []
    for update in graph.stream(build_input(summary_text(trip), trip=trip), cfg, stream_mode="updates"):
        for node, delta in update.items():
            path.append(node)
            if trace:
                print(f"  [trace] {node}: {_summary(node, delta or {})}".rstrip(": "))
    return graph.get_state(cfg).values, path


def run_turn(graph, text: str, thread_id: str, trace: bool = False) -> str:
    answer, path = run_turn_state(graph, text, thread_id, trace)
    if trace:
        print("  [trace] 경로: " + " -> ".join(path))
    return answer


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):   # Windows 콘솔(cp949)에서도 한글/기호 출력
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="스마트 여행 비서")
    ap.add_argument("--trace", action="store_true", help="노드 실행 순서 출력")
    ap.add_argument("--once", metavar="질문", help="질문 하나만 처리하고 종료")
    ap.add_argument("--plan", metavar="여행지", help="여행 계획 만들기 (예: --plan 도쿄 --start 2026-10-20 --days 4)")
    ap.add_argument("--start", metavar="YYYY-MM-DD", help="출발일 (--plan 과 함께)")
    ap.add_argument("--days", metavar="N", type=int, default=3, help="여행 일수 1~5 (기본 3)")
    ap.add_argument("--places", metavar="장소,장소", default="", help="원하는 장소 (쉼표 구분, 비우면 AI 추천)")
    args = ap.parse_args(argv)
    graph = build_graph(checkpointer=MemorySaver())
    thread_id = str(uuid.uuid4())

    if args.plan:
        from datetime import date
        from src.destinations import normalize_destination
        from src.trip import TripError, build_trip, split_places
        try:
            trip = build_trip(normalize_destination(args.plan) or args.plan, args.start or date.today().isoformat(),
                              args.days, split_places(args.places))
        except TripError as exc:
            print(f"오류: {exc}")
            sys.exit(2)
        values, path = run_plan(graph, trip, thread_id, args.trace)
        if args.trace:
            print("  [trace] 경로: " + " -> ".join(path))
        print(format_plan(values))
        print("\n비서>", values.get("final_answer", ""))
        return

    def ask(text: str) -> None:
        try:
            print("\n비서>", run_turn(graph, text, thread_id, args.trace))
        except Exception as exc:  # 최후 방어선 (NFR-02)
            print(f"\n비서> 죄송합니다. 처리 중 오류가 발생했습니다 ({type(exc).__name__}). 다시 시도해 주세요.")

    if args.once:
        ask(args.once)
        return
    print("스마트 여행 비서입니다. 종료: quit / exit")
    while True:
        try:
            text = input("\n나> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"quit", "exit", "q"}:
            break
        if text:
            ask(text)


if __name__ == "__main__":
    main()
