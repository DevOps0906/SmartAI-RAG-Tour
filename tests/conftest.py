"""모든 테스트는 외부 네트워크/키 없이 실행되도록 환경을 고정한다. (14.1)"""
import uuid

import pytest

from src.config import get_settings


def _clear_caches():
    get_settings.cache_clear()
    from src.rag.embeddings import _resolve
    from src.rag.index import get_vectorstore
    get_vectorstore.cache_clear()
    _resolve.cache_clear()


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GUIDES_DIR", "RAG_TOP_K", "MAX_STEPS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {
        "LLM_PROVIDER": "none", "EMBEDDING_PROVIDER": "hash",
        "WEATHER_MODE": "mock", "EXCHANGE_MODE": "mock",
        "OPENWEATHER_API_KEY": "", "RAG_INDEX_DIR": str(tmp_path / "index"),
    }.items():
        monkeypatch.setenv(k, v)
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture
def graph():
    from langgraph.checkpoint.memory import MemorySaver
    from src.graph import build_graph
    return build_graph(checkpointer=MemorySaver())


@pytest.fixture
def run(graph):
    """run(text, thread_id=None) -> (State 값 dict, 실행 노드 경로 list). 같은 thread_id 면 다중 턴."""
    from src.main import build_input

    def _run(text: str, thread_id: str = "t-default"):
        cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
        path = []
        for upd in graph.stream(build_input(text), cfg, stream_mode="updates"):
            path.extend(upd.keys())
        return graph.get_state(cfg).values, path

    return _run


@pytest.fixture
def new_thread():
    return lambda: f"t-{uuid.uuid4().hex[:8]}"
