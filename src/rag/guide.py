"""가이드 Markdown 에서 구조화된 정보(주요 명소, 일정 예시, 월별 기후 문장)를 꺼낸다.

벡터 인덱스를 거치지 않고 레지스트리가 가리키는 가이드 파일을 직접 읽으므로 임베딩 없이도 동작한다.
화면에는 파일명을 내보내지 않는다(이 모듈의 반환값에는 파일명이 없다).
"""
import re
from functools import lru_cache
from typing import Optional

from src.config import get_settings
from src.destinations import DESTINATIONS
from src.rag.loader import parse_guide
from src.rag.text import clean_snippet

PLACES_SECTION = "주요 명소"
ITINERARY_SECTION = "일정 예시"
CLIMATE_SECTION = "베스트 시즌과 기후"
OUT_OF_RANGE_NOTE = "예보 범위 밖이에요(약 5일 이내만 예보)"


@lru_cache(maxsize=32)
def _sections(path: str, mtime: float) -> dict[str, str]:
    from pathlib import Path
    _, secs = parse_guide(Path(path))
    return dict(secs)


def guide_sections(city: str) -> dict[str, str]:
    """{섹션 제목: 본문}. 도시/파일이 없으면 빈 사전."""
    info = DESTINATIONS.get(city or "")
    if not info:
        return {}
    path = get_settings().guides_dir / info.get("guide", f"{city}.txt")
    try:
        return _sections(str(path), path.stat().st_mtime)
    except OSError:
        return {}


def guide_places(city: str) -> list[dict]:
    """'주요 명소' 섹션의 장소 목록 [{name, desc}]. 굵은 글씨 불릿(- **이름**: 설명)과 '### 이름' 두 형식을 받는다.
    '기타'나 '그 밖에 ...' 같은 나머지 안내 줄은 제외한다."""
    body = guide_sections(city).get(PLACES_SECTION, "")
    out: list[dict] = []
    heads = list(re.finditer(r"^###\s+(.+)$", body, re.M))
    if heads:
        for i, m in enumerate(heads):
            name = m.group(1).strip()
            end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
            if name in ("기타", "그 밖에"):
                continue
            out.append({"name": name, "desc": clean_snippet(body[m.end():end], 0)})
    else:
        for m in re.finditer(r"^[-*]\s+\*\*(.+?)\*\*\s*[:：]\s*(.+)$", body, re.M):
            out.append({"name": m.group(1).strip(), "desc": clean_snippet(m.group(2), 0)})
    seen: set[str] = set()
    return [p for p in out if not (p["name"] in seen or seen.add(p["name"]))]


def itinerary_by_day(text: str) -> dict[int, str]:
    """'**1일차**: ...' 또는 '**1일**: ...' 줄을 {일차: 본문}으로. 여러 청크가 겹쳐도 먼저 나온 것을 쓴다."""
    by_day: dict[int, str] = {}
    for m in re.finditer(r"\*\*(\d+)\s*일(?:차)?\*\*\s*[:：]\s*(.+)", text or ""):
        by_day.setdefault(int(m.group(1)), m.group(2).strip())
    return by_day


def guide_itinerary(city: str) -> dict[int, str]:
    return itinerary_by_day(guide_sections(city).get(ITINERARY_SECTION, ""))


def split_items(text: str) -> list[str]:
    """일정 예시 한 줄을 활동 항목으로 나눈다 (쉼표 기준, 끝 마침표 제거)."""
    parts = [p.strip(" .。") for p in re.split(r"[,，、]", text or "")]
    return [p for p in parts if p]


_RANGE = re.compile(r"(\d{1,2})\s*월?(?:\s*(?:초|중순|말))?\s*~\s*(\d{1,2})\s*월")


def _month_in(m: int, a: int, b: int) -> bool:
    return a <= m <= b if a <= b else (m >= a or m <= b)


def climate_note(city: str, month: int) -> Optional[str]:
    """'베스트 시즌과 기후' 섹션에서 month 에 해당하는 계절 문장을 찾아 정리해 돌려준다. 없으면 None."""
    body = guide_sections(city).get(CLIMATE_SECTION, "")
    for line in body.splitlines():
        if not line.lstrip().startswith(("-", "*")):
            continue
        for m in _RANGE.finditer(line):
            if _month_in(month, int(m.group(1)), int(m.group(2))):
                return clean_snippet(line, 90)
    return None
