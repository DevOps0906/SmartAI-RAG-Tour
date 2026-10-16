"""표시용 텍스트 정리. RAG 인덱스 원문은 건드리지 않고, 화면/템플릿 답변에 내보낼 때만 쓴다."""
import re

_PREFIX = re.compile(r"^\s*\[[^\]]*\]\s*")
_HEADER = re.compile(r"^\s*#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*[-*•]\s+", re.M)
_EMPH = re.compile(r"\*\*|__|`")
_TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$", re.M)  # |---|---|
_TABLE_ROW = re.compile(r"^[ \t]*\|(.*)\|[ \t]*$", re.M)
_SENT_END = re.compile(r"[.!?。！？](?=\s|$)|다\.(?=\s|$)")


def clean_snippet(text: str, limit: int = 120) -> str:
    """'[도시 · 섹션] ' 접두사와 Markdown 기호를 걷어내고 공백을 정리한 뒤 limit 자 안으로 자연스럽게 자른다.

    limit <= 0 이면 자르지 않는다. 문장 경계(마침표 등)를 우선하고, 없으면 마지막 공백, 그래도 없으면 글자 수로 자른다.
    """
    t = _PREFIX.sub("", text or "")
    t = _HEADER.sub("", t)
    t = _BULLET.sub("", t)
    t = _EMPH.sub("", t)
    t = _TABLE_SEP.sub("", t)
    # 표 행 "| 숙박(1박) | 100~250 |" -> "숙박(1박) 100~250;"
    t = _TABLE_ROW.sub(lambda m: " ".join(c.strip() for c in m.group(1).split("|") if c.strip()) + ";", t)
    t = re.sub(r"\s+", " ", t).strip()
    if limit <= 0 or len(t) <= limit:
        return t
    head = t[:limit]
    floor = limit // 2
    cut = -1
    for m in _SENT_END.finditer(head):
        if m.end() >= floor:
            cut = m.end()
    if cut > 0:
        return head[:cut].rstrip()
    sp = head.rfind(" ")
    if sp >= floor:
        head = head[:sp]
    return head.rstrip(" ,;:·-") + "…"
