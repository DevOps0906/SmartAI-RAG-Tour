"""가이드 검색."""
from typing import Optional

from src.rag.index import get_vectorstore
from src.state import RagDoc


def search_guides(query: str, destination: Optional[str] = None, k: int = 4) -> list[RagDoc]:
    vs = get_vectorstore()
    kwargs: dict = {"k": k}
    if destination:
        # FAISS 메타 필터는 fetch_k 개의 상위 후보에 대해서만 적용된다. 코퍼스가 작으므로
        # 후보를 전체 청크 수로 잡아 필터 후 결과가 k 개보다 적어지는 문제를 막는다.
        kwargs["filter"] = {"city": destination}
        kwargs["fetch_k"] = max(vs.index.ntotal, k)
    results = vs.similarity_search_with_score(query, **kwargs)
    return [RagDoc(content=d.page_content, city=d.metadata["city"], section=d.metadata["section"],
                   source=d.metadata["source"], score=float(score)) for d, score in results]


ITINERARY_SECTION = "일정 예시"


def section_docs(destination: str, section: str) -> list[RagDoc]:
    """해당 도시의 특정 섹션 청크를 순서대로 돌려준다(유사도 검색과 무관하게 보장)."""
    vs = get_vectorstore()
    docs = [d for d in vs.docstore._dict.values()
            if d.metadata.get("city") == destination and d.metadata.get("section") == section]
    return [RagDoc(content=d.page_content, city=d.metadata["city"], section=d.metadata["section"],
                   source=d.metadata["source"], score=0.0) for d in docs]


def itinerary_docs(destination: str) -> list[RagDoc]:
    """해당 도시의 '일정 예시' 섹션 청크를 순서대로 돌려준다(유사도 검색과 무관하게 보장)."""
    return section_docs(destination, ITINERARY_SECTION)
