"""개발 전용 목업 데이터: /dev/components 미리보기와 단위 테스트에서만 쓴다. 실제 화면(/, /chat)은 그래프 State 를 쓴다."""
from __future__ import annotations

from copy import deepcopy

THREAD_ID = "t-tokyo-1"
USER_TEXT = "도쿄 3박 4일 일정이랑 날씨 알려주고, 50만원이면 엔화로 얼마인지도 알려줘"

_TOKYO_ITINERARY = (
    "### 3박 4일 모델\n"
    "- **1일차**: 공항 도착, 숙소 체크인, 신주쿠 산책, 도쿄도청 야경, 이자카야 저녁.\n"
    "- **2일차**: 아사쿠사 센소지, 스카이트리, 아키하바라 쇼핑, 우에노 저녁.\n"
    "- **3일차**: 메이지 신궁, 하라주쿠, 시부야 스크램블, 시부야 스카이 일몰과 야경.\n"
    "- **4일차**: 긴자 또는 츠키지 아침 식사, 기념품 쇼핑, 공항 이동.\n"
)

MOCK_STATE: dict = {
    "user_input": USER_TEXT,
    "intent": "multi",
    "entities": {
        "destination": "tokyo",
        "destination_ko": "도쿄",
        "amount": 500000,
        "currency": "JPY",
        "travel_date": "2026-11-20",
        "days": 4,
        "interests": ["맛집", "쇼핑"],
    },
    "pending_intents": [],
    "weather": {
        "ok": True, "source": "mock", "city": "tokyo", "city_ko": "도쿄", "date": "2026-11-20",
        "temp_c": 13.0, "feels_like_c": 12.0, "condition": "맑음", "humidity": 55,
        "advice": "겉옷 준비", "fallback_reason": "no_api_key_or_mock_mode", "error": None,
    },
    "exchange": {
        "ok": True, "source": "mock", "base": "KRW", "target": "JPY", "rate": 0.1099,
        "amount": 500000, "converted": 54945, "rate_date": None,
        "fallback_reason": "no_api_key_or_mock_mode", "error": None,
    },
    "rag_docs": [
        {"content": "라멘, 스시, 이자카야부터 미슐랭 식당까지 선택 폭이 넓습니다. 회전초밥은 가성비가 좋고 오마카세는 예약이 필요합니다.",
         "city": "tokyo", "section": "음식과 맛집", "source": "tokyo.txt", "score": 0.41},
        {"content": "아사쿠사, 시부야, 신주쿠, 하라주쿠가 대표 명소입니다. 시부야 스카이와 도쿄도청 무료 전망대에서 야경을 볼 수 있습니다.",
         "city": "tokyo", "section": "주요 명소", "source": "tokyo.txt", "score": 0.52},
        {"content": "스이카(Suica) 한 장으로 지하철, JR, 버스, 편의점까지 이용할 수 있습니다.",
         "city": "tokyo", "section": "교통", "source": "tokyo.txt", "score": 0.63},
        {"content": _TOKYO_ITINERARY, "city": "tokyo", "section": "일정 예시", "source": "tokyo.txt", "score": 0.58},
    ],
    "errors": [],
    "final_answer": (
        "도쿄 3박 4일 일정을 정리했어요. 11월 20일 무렵 기온은 13° 안팎이라 겉옷을 챙기시면 좋아요. "
        "50만원은 약 54,945엔이에요(실제 수수료 별도). 첫날은 신주쿠 야경과 이자카야, 둘째 날은 아사쿠사와 아키하바라를 추천해요."
    ),
}

MOCK_TRACE = [
    {"node": "analyze_input", "status": "success", "ms": 812},
    {"node": "rag_search", "status": "success", "ms": 143},
    {"node": "weather_tool", "status": "fallback", "ms": 21},
    {"node": "exchange_tool", "status": "fallback", "ms": 18},
    {"node": "generate_answer", "status": "success", "ms": 1204},
]

THREADS = [
    {"thread_id": "t-tokyo-1", "title": "도쿄 3박 4일 일정이랑 날씨", "updated_at": "방금"},
    {"thread_id": "t-jeju-1", "title": "제주 2박 3일 일정 짜줘", "updated_at": "어제"},
    {"thread_id": "t-paris-1", "title": "5월에 파리 날씨 어때요?", "updated_at": "3일 전"},
]


def get_state(empty: bool = False) -> dict:
    """보드가 읽는 State. empty=True 면 결과 필드를 비운 빈 상태."""
    s = deepcopy(MOCK_STATE)
    if empty:
        s.update({"weather": None, "exchange": None, "rag_docs": [], "entities": {}, "final_answer": "", "intent": "unknown"})
    return s
