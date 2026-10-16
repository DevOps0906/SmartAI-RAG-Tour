"""환경변수 로딩/설정. 비밀값은 .env 에서만 읽고, 코드 어디서든 get_settings() 로만 접근한다. (NFR-03)"""
import os
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")  # .env 없으면 조용히 무시

# Vercel 은 VERCEL=1 을 넣어 준다. 배포 번들은 읽기 전용이고 /tmp 만 쓸 수 있으며, torch(로컬 임베딩)는 번들 한도를 넘는다.
ON_VERCEL = bool(os.environ.get("VERCEL"))
WRITABLE = Path(tempfile.gettempdir()) if ON_VERCEL else ROOT / "data"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_model: str
    # 키는 repr 에 노출되지 않도록 repr=False (로그/예외 출력 보호)
    anthropic_api_key: str | None = field(repr=False)
    openai_api_key: str | None = field(repr=False)
    embedding_provider: str
    embedding_model: str
    openweather_api_key: str | None = field(repr=False)
    weather_mode: str          # auto | mock
    exchange_mode: str         # auto | mock
    exchange_api_base: str
    guides_dir: Path
    index_dir: Path
    rag_top_k: int
    chunk_size: int
    chunk_overlap: int
    http_timeout: float
    max_steps: int
    web_checkpoint: str        # sqlite | memory (17장 웹 계층)
    web_db_path: str
    web_secret: str = field(repr=False)   # 접수 토큰(src/web/pending.py) 서명 키


@lru_cache
def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        llm_provider=(e("LLM_PROVIDER") or "anthropic").lower(),
        llm_model=e("LLM_MODEL") or "claude-sonnet-5-5",
        anthropic_api_key=e("ANTHROPIC_API_KEY") or None,
        openai_api_key=e("OPENAI_API_KEY") or None,
        embedding_provider=(e("EMBEDDING_PROVIDER") or ("hash" if ON_VERCEL else "huggingface")).lower(),
        embedding_model=e("EMBEDDING_MODEL") or "intfloat/multilingual-e5-small",
        openweather_api_key=e("OPENWEATHER_API_KEY") or None,
        weather_mode=(e("WEATHER_MODE") or "auto").lower(),
        exchange_mode=(e("EXCHANGE_MODE") or "auto").lower(),
        exchange_api_base=e("EXCHANGE_API_BASE") or "https://open.er-api.com/v6/latest",
        guides_dir=Path(e("GUIDES_DIR") or str(ROOT / "data" / "guides")),
        index_dir=Path(e("RAG_INDEX_DIR") or str(WRITABLE / "index")),
        rag_top_k=int(e("RAG_TOP_K") or "4"),
        chunk_size=int(e("RAG_CHUNK_SIZE") or "500"),
        chunk_overlap=int(e("RAG_CHUNK_OVERLAP") or "80"),
        http_timeout=float(e("HTTP_TIMEOUT") or "5"),
        max_steps=int(e("MAX_STEPS") or "8"),
        web_checkpoint=(e("WEB_CHECKPOINT") or "sqlite").lower(),
        web_db_path=e("WEB_DB_PATH") or str(WRITABLE / "threads.sqlite"),
        web_secret=e("WEB_SECRET") or "smart-travel-dev-secret",
    )
