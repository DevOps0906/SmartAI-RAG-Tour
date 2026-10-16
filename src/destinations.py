"""도시 메타데이터와 이름 정규화. 날씨/환율/RAG 가 공유한다."""
import re
from typing import Optional

# 여행지 레지스트리: 지원 여행지의 단일 정답. 날씨/환율/RAG/웹 선택 카드/미지원 안내가 모두 이것을 본다.
# 새 여행지 추가: data/guides/{key}.txt 를 만들고 아래에 항목 하나를 추가한다 (enabled=True).
# 지원 여부는 supported_destinations() 로 판정한다 (enabled 이고 가이드 파일이 존재).
DESTINATIONS: dict[str, dict] = {
    "tokyo":   {"ko": "도쿄", "country": "일본", "currency": "JPY", "lat": 35.6762, "lon": 139.6503,
                "intro": "전통과 최첨단이 공존하는 도시", "guide": "tokyo.txt", "enabled": True,
                "aliases": ["tokyo", "도쿄", "동경", "東京"]},
    "paris":   {"ko": "파리", "country": "프랑스", "currency": "EUR", "lat": 48.8566, "lon": 2.3522,
                "intro": "미술관과 카페가 가득한 낭만의 도시", "guide": "paris.txt", "enabled": True,
                "aliases": ["paris", "파리"]},
    "bangkok": {"ko": "방콕", "country": "태국", "currency": "THB", "lat": 13.7563, "lon": 100.5018,
                "intro": "사원, 야시장, 길거리 음식의 천국", "guide": "bangkok.txt", "enabled": True,
                "aliases": ["bangkok", "방콕"]},
    "newyork": {"ko": "뉴욕", "country": "미국", "currency": "USD", "lat": 40.7128, "lon": -74.0060,
                "intro": "박물관, 공연, 스카이라인의 대도시", "guide": "newyork.txt", "enabled": True,
                "aliases": ["newyork", "뉴욕", "nyc", "맨해튼"]},
    "jeju":    {"ko": "제주", "country": "대한민국", "currency": "KRW", "lat": 33.4996, "lon": 126.5312,
                "intro": "바다와 오름, 힐링 드라이브 여행지", "guide": "jeju.txt", "enabled": True,
                "aliases": ["jeju", "제주", "제주도"]},
}

PICK_PHRASE = "아래 여행지 중에서 선택해 주세요."


def supported_destinations() -> list[dict]:
    """선택 가능한 여행지 목록 (등록 순서). enabled 이고 가이드 md 가 있는 항목만. 각 항목은 key 를 포함한다."""
    from src.config import get_settings
    gdir = get_settings().guides_dir
    return [{"key": k, **v} for k, v in DESTINATIONS.items()
            if v.get("enabled") and (gdir / v.get("guide", f"{k}.txt")).is_file()]


def supported_keys() -> list[str]:
    return [d["key"] for d in supported_destinations()]


def city_ko(key: Optional[str]) -> str:
    """도시 키 -> 한글명 (레지스트리에 없으면 키 그대로)."""
    info = DESTINATIONS.get(key or "")
    return info["ko"] if info else (key or "")


def supported_line() -> str:
    """CLI 용 '선택 가능: 도쿄(일본), 파리(프랑스), ...'"""
    return "선택 가능: " + ", ".join(f"{d['ko']}({d['country']})" for d in supported_destinations())


def unsupported_message(name: str) -> str:
    return f"지금 요청하신 {name}의 정보는 아직 존재하지 않습니다. {PICK_PHRASE}"


def unsupported_note(name: str) -> str:
    """지원 도시와 미지원 지명이 함께 나왔을 때 답변 끝에 붙이는 한 줄."""
    names = ", ".join(d["ko"] for d in supported_destinations())
    return f"참고: {name}의 정보는 아직 존재하지 않습니다. (지원 여행지: {names})"


# 미지원 지명 사전: (표시명, [별칭...]). 국가와 도시를 함께 둔다. 한글 별칭은 공백 제거 후 부분 일치,
# 영문 별칭은 단어 경계로 일치시킨다. '서울/부산'처럼 출발지로 자주 쓰이는 이름은 넣지 않는다.
UNSUPPORTED_PLACES: list[tuple[str, list[str]]] = [
    ("런던", ["런던", "london"]), ("영국", ["영국", "england", "잉글랜드", "uk"]),
    ("오사카", ["오사카", "osaka", "大阪"]), ("교토", ["교토", "kyoto"]), ("후쿠오카", ["후쿠오카", "fukuoka"]),
    ("삿포로", ["삿포로", "sapporo"]), ("오키나와", ["오키나와", "okinawa"]), ("나고야", ["나고야", "nagoya"]),
    ("로마", ["로마", "rome"]), ("밀라노", ["밀라노", "milan"]), ("베네치아", ["베네치아", "베니스", "venice"]),
    ("피렌체", ["피렌체", "florence"]), ("이탈리아", ["이탈리아", "italy"]),
    ("싱가포르", ["싱가포르", "싱가폴", "singapore"]),
    ("다낭", ["다낭", "danang", "da nang"]), ("하노이", ["하노이", "hanoi"]),
    ("호치민", ["호치민", "ho chi minh", "saigon"]), ("베트남", ["베트남", "vietnam"]),
    ("하와이", ["하와이", "hawaii", "호놀룰루"]), ("괌", ["괌", "guam"]), ("사이판", ["사이판", "saipan"]),
    ("시드니", ["시드니", "sydney"]), ("멜버른", ["멜버른", "melbourne"]), ("호주", ["호주", "australia"]),
    ("뉴질랜드", ["뉴질랜드", "new zealand"]),
    ("바르셀로나", ["바르셀로나", "barcelona"]), ("마드리드", ["마드리드", "madrid"]), ("스페인", ["스페인", "spain"]),
    ("리스본", ["리스본", "lisbon"]), ("포르투갈", ["포르투갈", "portugal"]),
    ("홍콩", ["홍콩", "hong kong", "hongkong"]), ("마카오", ["마카오", "macau"]),
    ("타이베이", ["타이베이", "타이페이", "taipei"]), ("대만", ["대만", "taiwan"]),
    ("발리", ["발리", "bali"]), ("인도네시아", ["인도네시아", "indonesia"]), ("세부", ["세부섬", "cebu"]),
    ("보라카이", ["보라카이", "boracay"]), ("필리핀", ["필리핀", "philippines"]),
    ("쿠알라룸푸르", ["쿠알라룸푸르", "kualalumpur"]), ("말레이시아", ["말레이시아", "malaysia"]),
    ("상하이", ["상하이", "shanghai"]), ("베이징", ["베이징", "북경", "beijing"]), ("중국", ["중국", "china"]),
    ("LA", ["로스앤젤레스", "로스엔젤레스", "엘에이", "los angeles", "la"]),
    ("샌프란시스코", ["샌프란시스코", "san francisco"]), ("라스베이거스", ["라스베이거스", "라스베가스", "las vegas"]),
    ("시카고", ["시카고", "chicago"]), ("보스턴", ["보스턴", "boston"]), ("시애틀", ["시애틀", "seattle"]),
    ("마이애미", ["마이애미", "miami"]), ("워싱턴", ["워싱턴", "washington"]),
    ("밴쿠버", ["밴쿠버", "vancouver"]), ("토론토", ["토론토", "toronto"]), ("캐나다", ["캐나다", "canada"]),
    ("베를린", ["베를린", "berlin"]), ("뮌헨", ["뮌헨", "munich"]), ("독일", ["독일", "germany"]),
    ("취리히", ["취리히", "zurich"]), ("스위스", ["스위스", "switzerland"]),
    ("암스테르담", ["암스테르담", "amsterdam"]), ("네덜란드", ["네덜란드", "netherlands"]),
    ("프라하", ["프라하", "prague"]), ("비엔나", ["비엔나", "vienna"]),
    ("부다페스트", ["부다페스트", "budapest"]), ("이스탄불", ["이스탄불", "istanbul"]),
    ("튀르키예", ["튀르키예", "터키", "turkey"]), ("두바이", ["두바이", "dubai"]),
    ("아테네", ["아테네", "athens"]), ("그리스", ["그리스", "greece"]),
    ("카이로", ["카이로", "cairo"]), ("이집트", ["이집트", "egypt"]), ("몰디브", ["몰디브", "maldives"]),
    ("멕시코", ["멕시코", "mexico"]), ("러시아", ["러시아", "russia"]),
]
# 한글 별칭이 다른 낱말의 일부일 때 걸러내는 부정 전방탐색 (예: 호주머니, 대만족, 로마자)
_NEG_AFTER = {"호주": "(?!머니)", "대만": "(?!족)", "로마": "(?!자)"}


def _alias_regex(alias: str) -> tuple[re.Pattern, bool]:
    """(패턴, 공백제거 텍스트에 적용 여부). 영문 별칭은 단어 경계, 한글 별칭은 부분 일치."""
    if alias.isascii():
        return re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"), False
    return re.compile(re.escape(alias) + _NEG_AFTER.get(alias, "")), True


_UNSUP_RE = [(name, [_alias_regex(a) for a in aliases]) for name, aliases in UNSUPPORTED_PLACES]


def find_unsupported(text: Optional[str]) -> list[str]:
    """문장 속 미지원 지명(표시명)을 등장 순서대로. 지원 여행지의 별칭과 겹치는 이름은 제외한다."""
    if not text:
        return []
    spaced = re.sub(r"\s+", " ", text.lower())
    tight = spaced.replace(" ", "")
    ok_aliases = {a.lower() for d in supported_destinations() for a in d["aliases"]}
    hits: list[tuple[int, str]] = []
    for name, pats in _UNSUP_RE:
        if name.lower() in ok_aliases:
            continue
        pos = [m.start() for rx, use_tight in pats if (m := rx.search(tight if use_tight else spaced))]
        if pos:
            hits.append((min(pos), name))
    return [n for _, n in sorted(hits)]


# 통화 표기(한글/코드) -> ISO 코드. 금액 파싱과 목적지 추정에 쓴다. (긴 표기가 먼저 매칭되도록 정렬해서 사용)
CURRENCY_WORDS: dict[str, str] = {
    "달러": "USD", "usd": "USD", "dollars": "USD", "dollar": "USD",
    "유로": "EUR", "eur": "EUR", "euros": "EUR", "euro": "EUR",
    "엔화": "JPY", "엔": "JPY", "jpy": "JPY",
    "바트": "THB", "thb": "THB",
}


def normalize_destination(text: Optional[str]) -> Optional[str]:
    """문자열(단어 또는 문장 전체)에서 도시 키를 찾는다. 없으면 None."""
    if not text:
        return None
    t = text.lower().replace(" ", "")
    for d in supported_destinations():
        if any(a.lower() in t for a in d["aliases"]):
            return d["key"]
    return None


def destination_of_currency(code: Optional[str]) -> Optional[str]:
    """통화 코드에 대응하는 대표 도시 키 (KRW -> 제주). 없으면 None."""
    for key, info in DESTINATIONS.items():
        if info["currency"] == code:
            return key
    return None
