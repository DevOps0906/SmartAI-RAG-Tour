"""노드 공용 헬퍼."""
from src.state import TravelState


def pop_task(state: TravelState, task: str) -> list[str]:
    """완료(또는 실패)한 작업을 큐에서 제거. 실패해도 반드시 제거해 무한 루프 방지."""
    pending = list(state.get("pending_intents", []))
    if task in pending:
        pending.remove(task)
    return pending


def add_error(state: TravelState, msg: str) -> list[str]:
    """errors 목록에 항목을 추가한 새 목록을 반환 (리듀서 없이 덮어쓰기). 키/URL 노출 방지를 위해 호출부는 예외 클래스명만 넘긴다."""
    return [*state.get("errors", []), msg]
