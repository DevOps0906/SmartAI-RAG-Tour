"""임베딩 팩토리 + 오프라인 결정적 HashEmbeddings. 불가능한 provider 는 hash 로 자동 폴백(경고 로그)."""
import hashlib
import importlib.util
import logging
import math
import re
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from src.config import get_settings

log = logging.getLogger(__name__)


class HashEmbeddings(Embeddings):
    """오프라인/테스트용 결정적 임베딩: 문자 2,3-gram 해시 버킷 카운트 + L2 정규화."""

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        t = re.sub(r"\s+", " ", text.lower())
        vec = [0.0] * self.dim
        for n in (2, 3):
            for i in range(len(t) - n + 1):
                h = int(hashlib.md5(t[i:i + n].encode("utf-8")).hexdigest(), 16)
                vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _hf_available() -> bool:
    return (importlib.util.find_spec("langchain_huggingface") is not None
            and importlib.util.find_spec("sentence_transformers") is not None)


@lru_cache(maxsize=8)
def _resolve(provider: str, model: str, has_openai_key: bool) -> tuple[str, Embeddings]:
    """(실제 사용 provider 이름, Embeddings). 요청한 provider 를 쓸 수 없으면 hash 로 폴백한다."""
    if provider == "hash":
        return "hash", HashEmbeddings()
    if provider == "openai":
        if not has_openai_key:
            log.warning("EMBEDDING_PROVIDER=openai 이지만 OPENAI_API_KEY 가 없어 hash 임베딩으로 대체합니다.")
            return "hash", HashEmbeddings()
        from langchain_openai import OpenAIEmbeddings
        return "openai", OpenAIEmbeddings(model="text-embedding-3-small",
                                          api_key=get_settings().openai_api_key)
    if provider == "huggingface":
        if not _hf_available():
            log.warning("langchain-huggingface/sentence-transformers 가 설치되지 않아 hash 임베딩으로 대체합니다 "
                        "(pip install -r requirements-hf.txt).")
            return "hash", HashEmbeddings()
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
            return "huggingface", HuggingFaceEmbeddings(model_name=model,
                                                         encode_kwargs={"normalize_embeddings": True})
        except Exception as exc:   # 모델 다운로드 실패 등
            log.warning("HuggingFace 임베딩 로드 실패(%s) - hash 임베딩으로 대체합니다.", type(exc).__name__)
            return "hash", HashEmbeddings()
    raise ValueError(f"알 수 없는 EMBEDDING_PROVIDER: {provider}")


def _resolved() -> tuple[str, Embeddings]:
    s = get_settings()
    return _resolve(s.embedding_provider, s.embedding_model, bool(s.openai_api_key))


def get_embeddings() -> Embeddings:
    return _resolved()[1]


def effective_provider() -> str:
    """폴백까지 반영한 실제 provider 이름 (인덱스 fingerprint 에 사용)."""
    return _resolved()[0]
