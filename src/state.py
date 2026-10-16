"""에이전트 전역 상태 정의. (FR-01)"""
import operator
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

Intent = Literal["recommend", "weather", "exchange", "itinerary", "detail", "multi", "unknown"]
Task = Literal["rag", "weather", "exchange", "plan"]


class Entities(TypedDict, total=False):
    destination: Optional[str]      # 정규화 키 (레지스트리 DESTINATIONS 의 지원 항목)
    destination_ko: Optional[str]   # 표시용 한글명
    amount: Optional[float]         # 환전 기준 금액
    amount_currency: Optional[str]  # amount 의 통화 (기본 KRW, "100달러" 면 USD)
    amount_assumed: bool            # 금액을 말하지 않아 기본값(100만원)을 가정했는지
    currency: Optional[str]         # 목적지 통화 코드 (JPY, EUR ...)
    travel_date: Optional[str]      # YYYY-MM-DD
    days: Optional[int]             # 여행 일수
    interests: list[str]            # 취향 키워드 (맛집, 휴양, 쇼핑 ...)


class RagDoc(TypedDict):
    content: str
    city: str
    section: str
    source: str
    score: float                    # FAISS L2 거리 (낮을수록 유사)


class Trip(TypedDict, total=False):
    """모달에서 확정한 여행 계획. 체크포인트에 남아 다음 턴에도 유지되고, 새 계획을 만들면 교체된다."""
    destination: str                # 레지스트리 키
    destination_ko: str
    start_date: str                 # YYYY-MM-DD
    end_date: str
    days: int                       # 여행 일수 (도착일 포함)
    nights: int
    places: list[str]               # 사용자가 고른 장소 (비면 plan_itinerary 가 가이드에서 추천)
    places_auto: bool               # places 가 AI 추천으로 채워졌는지


class ItineraryDay(TypedDict, total=False):
    day: int
    date: str                       # YYYY-MM-DD
    title: str
    items: list[str]
    note: str


class DetailCard(TypedDict, total=False):
    """챗봇 상세 요청 결과. 보드의 '요청한 정보' 섹션에 누적된다."""
    id: str
    title: str
    body: str
    section: str                    # 주제 라벨 (맛집, 쇼핑, 교통 ...)
    day: int                        # 일차를 말한 경우만
    created_at: str


class TravelState(TypedDict, total=False):
    # 대화/입력
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    # 분석 결과
    intent: Intent
    entities: Entities
    # 제어 흐름
    pending_intents: list[Task]
    needs_clarification: bool
    clarify_question: str
    clarify_reason: Optional[str]          # None | "unsupported_destination" (clarify 문구 분기)
    unsupported_destination: Optional[str]  # 이번 턴에 감지된 미지원 지명 ("런던, 로마"). 턴마다 초기화
    step_count: int
    # 작업 결과
    rag_docs: list[RagDoc]
    weather: Optional[dict]
    exchange: Optional[dict]
    # 여행 계획 (모달 -> POST /plan). trip/itinerary/forecast 는 턴마다 초기화하지 않고 체크포인트에 유지한다
    trip: Optional[Trip]
    plan_request: bool                     # 이번 턴이 계획 생성 요청인지 (analyze_input 이 파싱을 건너뜀)
    itinerary: list[ItineraryDay]
    forecast: list[dict]                   # 기간 날씨: {date, tmin, tmax, condition, pop, source: forecast|climate|mock}
    detail_request: Optional[dict]         # 이번 턴의 상세 요청 {topic, label, sections, day, place}
    details: Annotated[list[DetailCard], operator.add]   # 요청한 정보 카드 누적
    # 출력/진단
    errors: list[str]
    final_answer: str
