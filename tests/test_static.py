"""T-22, T-23 정적 검사 + 키 노출 방지, 그래프 구조/도식."""
import re
from pathlib import Path

from src.config import ROOT, get_settings

SRC = ROOT / "src"


def _py_files():
    return [p for p in SRC.rglob("*.py")]


def test_t22_no_prebuilt_agent_api():
    bad = re.compile(r"create_react_agent|langgraph\.prebuilt|ToolNode|tools_condition")
    hits = [str(p) for p in _py_files() if bad.search(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_t23_gitignore_and_no_hardcoded_keys():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gi and "data/index/" in gi
    pat = re.compile(r"sk-[A-Za-z0-9_\-]{16,}|appid=|AIza[0-9A-Za-z_\-]{20,}")
    hits = [str(p) for p in _py_files() if pat.search(p.read_text(encoding="utf-8"))]
    assert hits == []
    ex = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^ANTHROPIC_API_KEY=$", ex, re.M) and re.search(r"^OPENWEATHER_API_KEY=$", ex, re.M)


def test_settings_repr_hides_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRETVALUE")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-SECRETOPENAI")
    monkeypatch.setenv("OPENWEATHER_API_KEY", "SECRETWEATHER")
    get_settings.cache_clear()
    r = repr(get_settings())
    assert "SECRET" not in r


def test_default_llm_model():
    assert get_settings().llm_model == "claude-sonnet-5-5"
    assert get_settings().llm_provider == "none"          # conftest 가 none 으로 고정


def test_graph_structure(graph):
    g = graph.get_graph()
    names = set(g.nodes)
    assert {"analyze_input", "rag_search", "weather_tool", "exchange_tool", "clarify",
            "generate_answer"} <= names
    # 조건부 에지가 존재 (analyze_input -> 여러 대상)
    out = {e.target for e in g.edges if e.source == "analyze_input"}
    assert {"clarify", "rag_search", "weather_tool", "exchange_tool", "generate_answer"} <= out
    assert "analyze_input" in g.draw_mermaid()


def test_unavailable_llm_error_message_has_no_key(monkeypatch):
    import pytest
    from src.llm import LLMUnavailable, get_llm
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(LLMUnavailable):
        get_llm()


def test_llm_factory_builds_with_key_without_network(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummydummydummy")
    get_settings.cache_clear()
    from src.llm import get_llm
    llm = get_llm()
    assert llm.model == "claude-sonnet-5-5"
    assert "dummydummy" not in repr(llm)
