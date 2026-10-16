"""FAISS 인덱스 빌드/로드. 가이드 파일 또는 임베딩/청킹 설정이 바뀌면 자동 재빌드한다. (CLI: --rebuild)"""
import argparse
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from langchain_community.vectorstores import FAISS

from src.config import Settings, get_settings
from src.rag.embeddings import effective_provider, get_embeddings
from src.rag.loader import load_and_split


def _fingerprint(s: Settings) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(s.guides_dir).glob("*.txt")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    # 폴백까지 반영한 실제 provider 를 쓴다 (huggingface 요청 -> hash 폴백 시 hash 로 기록)
    prov = effective_provider()
    model = s.embedding_model if prov == "huggingface" else ""
    h.update(f"{prov}|{model}|{s.chunk_size}|{s.chunk_overlap}".encode())
    return h.hexdigest()


def build_vectorstore(force: bool = False) -> FAISS:
    s = get_settings()
    idx = Path(s.index_dir)
    manifest = idx / "manifest.json"
    fp = _fingerprint(s)
    emb = get_embeddings()
    if not force and manifest.exists() and (idx / "index.faiss").exists():
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("fingerprint") == fp:
                # 직접 생성한 로컬 인덱스만 로드하므로 역직렬화 허용
                return FAISS.load_local(str(idx), emb, allow_dangerous_deserialization=True)
        except Exception:
            pass   # 손상된 인덱스 -> 재빌드
    chunks = load_and_split(s)
    if not chunks:
        raise RuntimeError(f"가이드 문서가 없습니다: {s.guides_dir}")
    vs = FAISS.from_documents(chunks, emb)
    idx.mkdir(parents=True, exist_ok=True)
    vs.save_local(str(idx))
    manifest.write_text(json.dumps({"fingerprint": fp, "chunks": len(chunks),
                                    "embedding": effective_provider()}), encoding="utf-8")
    return vs


@lru_cache(maxsize=1)
def get_vectorstore() -> FAISS:
    return build_vectorstore()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="여행 가이드 FAISS 인덱스 빌드")
    ap.add_argument("--rebuild", action="store_true", help="기존 인덱스를 무시하고 재생성")
    args = ap.parse_args()
    vs = build_vectorstore(force=args.rebuild)
    print(f"인덱스 준비 완료: {vs.index.ntotal}개 청크 (embedding={effective_provider()})")
