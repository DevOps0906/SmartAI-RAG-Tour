"""랜딩용 데이터: 히어로 슬라이드와 인기 코스.

- 여행지는 레지스트리(destinations.py)가, 장소는 가이드 '주요 명소'(rag/guide.py)가 정답이다.
  courses() 는 지원 여행지만 담고, 가이드 명소에 없는 장소는 버린다.
- 경비는 가이드 '예산과 물가' 섹션을 대략 반영한 1인 기준 값(항공 제외)이다. 판매가가 아니라 참고용 표기다.
  환산 기준(2026 가이드): 100엔 ≈ 900원, 1유로 ≈ 1,500원, 100바트 ≈ 4,000원, 1달러 ≈ 1,400원.
- image 필드: None 이면 templates/illustrations 의 SVG 일러스트를 쓴다. 실사 이미지로 바꾸려면 정적 경로를 넣는다.
"""
from __future__ import annotations

from src.destinations import DESTINATIONS, supported_keys
from src.rag.guide import guide_places

COST_NOTE = "항공 제외 · 참고용"

# 슬라이드: 여행지별 1장. headline 은 줄바꿈(\n)으로 두 줄.
SLIDES: list[dict] = [
    {"dest": "tokyo", "headline": "골목마다 맛집,\n도쿄 3일 미식 여행",
     "desc": "신주쿠 야경에서 아사쿠사 골목까지, 먹고 걷는 하루를 가이드로 짜 드려요.",
     "tags": ["미식", "야경", "골목산책"], "image": None},
    {"dest": "paris", "headline": "해 질 녘 에펠탑,\n파리 4일 예술 산책",
     "desc": "미술관과 언덕 마을, 센강의 저녁까지 느리게 걷는 일정을 만들어 보세요.",
     "tags": ["미술관", "카페", "야경"], "image": None},
    {"dest": "bangkok", "headline": "황금빛 사원과 야시장,\n방콕 3일 도시 여행",
     "desc": "왕궁과 새벽 사원, 길거리 음식 골목을 한 동선으로 묶어 드려요.",
     "tags": ["사원", "야시장", "길거리음식"], "image": None},
    {"dest": "newyork", "headline": "스카이라인 아래,\n뉴욕 4일 도시 탐험",
     "desc": "공원과 미술관, 브로드웨이와 다리 산책까지 대도시의 하이라이트를 담았어요.",
     "tags": ["스카이라인", "미술관", "공연"], "image": None},
    {"dest": "jeju", "headline": "바다와 오름 사이,\n제주 3일 힐링 드라이브",
     "desc": "일출봉과 서쪽 해변, 한라산 자락까지 여유로운 드라이브 코스를 골라 보세요.",
     "tags": ["바다", "오름", "드라이브"], "image": None},
]

# 코스: (dest, 이름, 일수, 장소(가이드 '주요 명소' 이름), 해시태그, 1인 경비 만원, 경비 근거)
_COURSES: list[tuple[str, str, int, list[str], list[str], int, str]] = [
    ("tokyo", "미식·야경", 3, ["신주쿠", "시부야", "아사쿠사"], ["미식", "야경", "골목"], 55,
     "비즈니스호텔 2박 + 식비(이자카야·라멘) 기준"),
    ("tokyo", "전통·트렌드", 2, ["아사쿠사", "하라주쿠"], ["전통", "패션", "디저트"], 35,
     "1박 + 식비·교통 기준"),
    ("paris", "예술·야경", 4, ["에펠탑", "루브르 박물관", "몽마르트르"], ["미술관", "야경", "언덕"], 140,
     "가성비형 4박5일 700~1,000 EUR 구간 하단"),
    ("paris", "궁전·정원", 3, ["베르사유 궁전", "에펠탑"], ["궁전", "정원", "근교"], 110,
     "숙박 2박 + 식비·교통·입장 기준"),
    ("bangkok", "사원·강변", 3, ["왕궁과 왓프라깨우", "왓포", "왓아룬"], ["사원", "일몰", "마사지"], 35,
     "1일 2,000~3,500 THB 가성비 기준"),
    ("bangkok", "시장·길거리 음식", 4, ["짜뚜짝 주말시장", "카오산 로드", "왓포"], ["야시장", "길거리음식", "쇼핑"], 45,
     "1일 2,000~3,500 THB 가성비 기준"),
    ("newyork", "공원·미술관", 4, ["센트럴파크", "메트로폴리탄 미술관(MET)"], ["공원", "미술관", "산책"], 190,
     "중급 호텔 3박 + 식비·교통 기준"),
    ("newyork", "스카이라인·공연", 3, ["타임스스퀘어", "브루클린 브리지"], ["야경", "브로드웨이", "다리"], 150,
     "중급 호텔 2박 + 뮤지컬 1회 포함 기준"),
    ("jeju", "해변·드라이브", 3, ["협재해변", "섭지코지", "성산일출봉"], ["바다", "일출", "드라이브"], 45,
     "숙소 2박 + 식비·렌터카 기준"),
    ("jeju", "한라산·일출", 2, ["한라산", "성산일출봉"], ["등산", "일출", "자연"], 30,
     "숙소 1박 + 식비·렌터카 기준"),
]


def _hashtags(tags: list[str]) -> list[str]:
    return [f"#{t}" for t in tags]


def slides() -> list[dict]:
    """히어로 슬라이드(지원 여행지만). 각 항목: dest, dest_ko, country, headline_lines, desc, tags(#포함), image."""
    ok = set(supported_keys())
    out = []
    for s in SLIDES:
        if s["dest"] not in ok:
            continue
        info = DESTINATIONS[s["dest"]]
        out.append({**s, "dest_ko": info["ko"], "country": info["country"], "intro": info["intro"],
                    "headline_lines": s["headline"].split("\n"), "tags": _hashtags(s["tags"])})
    return out


def courses() -> list[dict]:
    """인기 코스 카드 데이터(지원 여행지만). places 는 가이드 '주요 명소'에 있는 이름만 남긴다.
    각 항목: id, dest, dest_ko, country, title, days, places, tags(#포함), cost_man, cost_label, cost_basis, image."""
    ok = set(supported_keys())
    guide_cache: dict[str, set[str]] = {}
    out = []
    for dest, name, days, places, tags, cost, basis in _COURSES:
        if dest not in ok:
            continue
        names = guide_cache.setdefault(dest, {p["name"] for p in guide_places(dest)})
        picked = [p for p in places if p in names]
        if not picked:
            continue
        info = DESTINATIONS[dest]
        out.append({
            "id": f"{dest}-{days}d-{len(out) + 1}", "dest": dest, "dest_ko": info["ko"], "country": info["country"],
            "title": f"[{info['ko']}] {name} {days}일", "days": days, "places": picked,
            "tags": _hashtags(tags), "cost_man": cost, "cost_label": f"약 {cost}만원~", "cost_basis": basis,
            "image": None,
        })
    return out
