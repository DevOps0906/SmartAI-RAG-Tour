"""T-13 ~ T-15 RAG + 임베딩 폴백."""
import json
import logging
import shutil

import pytest

from src.config import ROOT, get_settings
from src.rag.index import build_vectorstore, get_vectorstore
from src.rag.loader import load_and_split
from src.rag.retriever import search_guides

CITIES = {"tokyo", "paris", "bangkok", "newyork", "jeju"}


def test_chunks_have_metadata_for_all_five_guides():
    chunks = load_and_split(get_settings())
    assert {c.metadata["city"] for c in chunks} == CITIES
    assert all(c.metadata["section"] and c.metadata["source"].endswith(".txt") for c in chunks)
    assert all(c.page_content.startswith("[") for c in chunks)


def test_city_filter():
    docs = search_guides("맛집", destination="jeju", k=3)
    assert len(docs) == 3 and all(d["city"] == "jeju" for d in docs)


@pytest.mark.parametrize("city", sorted(CITIES))
def test_city_filter_always_returns_k(city):
    # 필터 후 결과가 k 개보다 적어지지 않아야 한다 (fetch_k 버그 회귀)
    assert len(search_guides("전혀 상관없는 질의 xyz", destination=city, k=4)) == 4


def test_global_search_returns_multiple_cities():
    docs = search_guides("휴양 해변 추천", k=5)
    assert len(docs) == 5


def test_fingerprint_change_triggers_rebuild(monkeypatch, tmp_path):
    guides = tmp_path / "guides"
    shutil.copytree(ROOT / "data" / "guides", guides)   # 원본 가이드는 건드리지 않는다
    monkeypatch.setenv("GUIDES_DIR", str(guides))
    get_settings.cache_clear()
    idx = get_settings().index_dir

    build_vectorstore()
    fp1 = json.loads((idx / "manifest.json").read_text(encoding="utf-8"))["fingerprint"]
    build_vectorstore()   # 변경 없음 -> 로드, fingerprint 동일
    assert json.loads((idx / "manifest.json").read_text(encoding="utf-8"))["fingerprint"] == fp1

    with open(guides / "jeju.txt", "a", encoding="utf-8") as f:
        f.write("\n\n## 비밀 장소\n오직 테스트에만 존재하는 유니크한줄기사과나무 정원.\n")
    build_vectorstore()
    fp2 = json.loads((idx / "manifest.json").read_text(encoding="utf-8"))["fingerprint"]
    assert fp2 != fp1
    get_vectorstore.cache_clear()
    docs = search_guides("유니크한줄기사과나무 정원", destination="jeju", k=1)
    assert docs[0]["section"] == "비밀 장소"


def test_huggingface_falls_back_to_hash_with_warning(monkeypatch, caplog):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "huggingface")
    monkeypatch.setattr("src.rag.embeddings._hf_available", lambda: False)
    get_settings.cache_clear()
    from src.rag.embeddings import HashEmbeddings, effective_provider, get_embeddings
    with caplog.at_level(logging.WARNING):
        emb = get_embeddings()
    assert isinstance(emb, HashEmbeddings) and effective_provider() == "hash"
    assert any("hash" in r.getMessage() for r in caplog.records)
    # 폴백 상태에서도 검색이 동작
    assert search_guides("도쿄 야경", k=2)


def test_openai_embedding_without_key_falls_back(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    get_settings.cache_clear()
    from src.rag.embeddings import effective_provider
    assert effective_provider() == "hash"


def test_hash_embeddings_deterministic_and_normalized():
    from src.rag.embeddings import HashEmbeddings
    e = HashEmbeddings()
    a, b = e.embed_query("도쿄 맛집"), e.embed_query("도쿄 맛집")
    assert a == b and abs(sum(x * x for x in a) - 1.0) < 1e-9


def test_clean_snippet():
    from src.rag.text import clean_snippet
    raw = "[도쿄 · 베스트 시즌과 기후] - **봄(3월 말~4월 초)**: 벚꽃이 핍니다. 맑은 날이 많아요.\n- **가을**: 선선합니다. `팁` __중요__"
    out = clean_snippet(raw, 0)
    assert out == "봄(3월 말~4월 초): 벚꽃이 핍니다. 맑은 날이 많아요. 가을: 선선합니다. 팁 중요"
    cut = clean_snippet(raw, 40)
    assert cut.endswith(".") and len(cut) <= 40   # 문장 경계 우선
    assert clean_snippet("# 제목\n- 항목", 50) == "제목 항목"
    assert clean_snippet("가" * 100, 10) == "가" * 10 + "…"


def test_template_answer_is_clean(run):
    state, _ = run("도쿄 3박 4일 여행 알려줘")
    ans = state["final_answer"]
    assert "**" not in ans and "[도쿄 ·" not in ans


def test_clean_snippet_flattens_markdown_table():
    from src.rag.text import clean_snippet
    raw = "[파리 · 예산과 물가] 대략 금액입니다.\n| 항목 | 대략 금액(EUR) |\n|---|---|\n| 숙박(1박) | 100~250 |\n| 식비(1일) | 40~90 |"
    out = clean_snippet(raw, 0)
    assert "|" not in out and "---" not in out
    assert "숙박(1박) 100~250;" in out and "식비(1일) 40~90;" in out
