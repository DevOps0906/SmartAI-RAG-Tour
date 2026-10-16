"""그래프와 체크포인터 생성. 테스트는 app.state.checkpointer/graph 에 MemorySaver 기반 그래프를 먼저 넣어 두면 그대로 쓴다."""
import sqlite3
from pathlib import Path

from fastapi import FastAPI

from src.config import get_settings
from src.graph import build_graph


def make_checkpointer():
    """WEB_CHECKPOINT=sqlite(기본) 이면 SqliteSaver, 아니면 MemorySaver."""
    s = get_settings()
    if s.web_checkpoint == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver
        path = Path(s.web_db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
        saver.setup()   # 새 DB(새 clone, 서버리스 /tmp)에서도 기록 목록 조회가 checkpoints 테이블을 찾도록 미리 만든다
        return saver
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()


def get_runtime(app: FastAPI):
    """(graph, checkpointer). 없으면 설정대로 만들어 app.state 에 둔다."""
    if getattr(app.state, "graph", None) is None:
        cp = getattr(app.state, "checkpointer", None) or make_checkpointer()
        app.state.checkpointer = cp
        app.state.graph = build_graph(checkpointer=cp)
    return app.state.graph, app.state.checkpointer
