"""여행 계획(trip) 검증과 표시용 문구. 웹 POST /plan 과 CLI --plan 이 같은 규칙을 쓴다."""
import re
from datetime import date, timedelta
from typing import Optional

from src.destinations import DESTINATIONS, supported_keys

MAX_DAYS = 5
MAX_PLACES = 10
MAX_PLACE_LEN = 30
WEEKDAYS = "월화수목금토일"


class TripError(ValueError):
    """사용자에게 그대로 보여줘도 되는 검증 오류 문구."""


def split_places(*raws) -> list[str]:
    """체크박스 값(list)과 자유 입력(쉼표/줄바꿈 구분)을 합쳐 공백 정리, 중복 제거. 순서 유지."""
    items: list[str] = []
    for raw in raws:
        if raw is None:
            continue
        parts = raw if isinstance(raw, (list, tuple)) else re.split(r"[,，、\n]", str(raw))
        for p in parts:
            t = re.sub(r"[|\s]+", " ", str(p)).strip()
            if t:
                items.append(t)
    return list(dict.fromkeys(items))


def _parse_date(raw: Optional[str], label: str) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        raise TripError(f"{label}을 YYYY-MM-DD 형식으로 입력해 주세요.") from None


def build_trip(destination: str, start: str, days, places: list[str] | None = None,
               today: date | None = None) -> dict:
    """검증을 통과한 trip 을 만든다. end_date 는 start_date + days - 1 로 계산한다. 실패하면 TripError."""
    today = today or date.today()
    key = (destination or "").strip()
    if key not in supported_keys():
        raise TripError("지원하지 않는 여행지예요. 목록에서 골라 주세요.")
    s = _parse_date(start, "출발일")
    if s < today:
        raise TripError("출발일은 오늘 이후로 골라 주세요.")
    try:
        n = int(str(days).strip())
    except (TypeError, ValueError):
        raise TripError(f"여행 일수는 1~{MAX_DAYS} 사이의 숫자로 골라 주세요.") from None
    if not 1 <= n <= MAX_DAYS:
        raise TripError(f"여행 일수는 1일차부터 {MAX_DAYS}일차까지 고를 수 있어요.")
    e = s + timedelta(days=n - 1)
    places = split_places(places or [])
    if len(places) > MAX_PLACES:
        raise TripError(f"원하는 장소는 최대 {MAX_PLACES}곳까지 고를 수 있어요.")
    if any(len(p) > MAX_PLACE_LEN for p in places):
        raise TripError(f"장소 이름은 {MAX_PLACE_LEN}자 이하로 입력해 주세요.")
    info = DESTINATIONS[key]
    return {"destination": key, "destination_ko": info["ko"], "start_date": s.isoformat(),
            "end_date": e.isoformat(), "days": n, "nights": n - 1,
            "places": places, "places_auto": False}


def duration_label(trip: dict) -> str:
    n, d = trip.get("nights", 0), trip.get("days", 1)
    return f"{n}박{d}일" if n else "당일치기"


def md(iso: str) -> str:
    """'2026-10-20' -> '10/20'"""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    return f"{d.month}/{d.day}"


def md_wd(iso: str) -> str:
    """'2026-10-20' -> '10/20(화)'"""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def trip_dates(trip: dict) -> list[str]:
    s = date.fromisoformat(trip["start_date"])
    return [(s + timedelta(days=i)).isoformat() for i in range(int(trip["days"]))]


def summary_text(trip: dict) -> str:
    """챗봇 위젯에 사용자 메시지로 보이는 요약 문장."""
    head = f"{trip['destination_ko']} {md(trip['start_date'])}~{md(trip['end_date'])} {duration_label(trip)}"
    places = trip.get("places") or []
    if places:
        return f"{head}, {'·'.join(places)} 포함 계획 만들어줘"
    return f"{head} 계획 만들어줘"
