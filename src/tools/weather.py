"""날씨 Tool (FR-04). 실제 API(OpenWeatherMap) -> 실패/키 없음 시 mock 폴백. 예외를 밖으로 던지지 않는다."""
from datetime import date as _date

import httpx
from langchain_core.tools import tool

from src.config import get_settings
from src.destinations import DESTINATIONS, normalize_destination

# 월별 평균 기온(1~12월)과 강수 많은 달 - mock 기후 데이터
_CLIMATE = {
    "tokyo":   ([5, 6, 9, 14, 19, 22, 26, 27, 24, 18, 13, 8], {6, 9}),
    "paris":   ([5, 6, 9, 12, 16, 19, 21, 21, 18, 13, 8, 5], {10, 11}),
    "bangkok": ([27, 28, 29, 30, 29, 29, 28, 28, 28, 28, 28, 27], {5, 6, 7, 8, 9, 10}),
    "newyork": ([0, 1, 5, 11, 17, 22, 25, 24, 20, 14, 9, 3], {4, 7}),
    "jeju":    ([6, 6, 9, 14, 18, 21, 26, 27, 23, 18, 13, 8], {6, 7, 8}),
}


def _advice(temp: float, rainy: bool) -> str:
    base = ("두꺼운 외투 필수" if temp < 5 else "겉옷 준비" if temp < 15
            else "가벼운 옷차림" if temp < 25 else "통풍 잘 되는 옷, 자외선 차단")
    return base + (", 우산 지참" if rainy else "")


def _mock(key: str, date_str: str | None, reason: str) -> dict:
    info = DESTINATIONS[key]
    try:
        d = _date.fromisoformat(date_str) if date_str else _date.today()
    except ValueError:
        d = _date.today()
    temps, rainy_months = _CLIMATE[key]
    t = float(temps[d.month - 1])
    rainy = d.month in rainy_months
    return {"ok": True, "source": "mock", "city": key, "city_ko": info["ko"], "date": d.isoformat(),
            "temp_c": t, "feels_like_c": t, "condition": "비" if rainy else "맑음",
            "humidity": 80 if rainy else 55, "advice": _advice(t, rainy),
            "fallback_reason": reason, "error": None}


def _live(key: str, api_key: str, timeout: float) -> dict:
    info = DESTINATIONS[key]
    r = httpx.get("https://api.openweathermap.org/data/2.5/weather", timeout=timeout,
                  params={"lat": info["lat"], "lon": info["lon"], "appid": api_key,
                          "units": "metric", "lang": "kr"})
    r.raise_for_status()
    j = r.json()
    t = float(j["main"]["temp"])
    desc = j["weather"][0]["description"]
    return {"ok": True, "source": "live", "city": key, "city_ko": info["ko"],
            "date": _date.today().isoformat(), "temp_c": t,
            "feels_like_c": float(j["main"]["feels_like"]), "condition": desc,
            "humidity": int(j["main"]["humidity"]),
            "advice": _advice(t, "비" in desc or "rain" in desc.lower()),
            "fallback_reason": None, "error": None}


@tool
def get_weather(city: str, date: str | None = None) -> dict:
    """지정한 여행지의 날씨를 조회한다. city는 tokyo|paris|bangkok|newyork|jeju (한글명도 허용),
    date는 YYYY-MM-DD(선택, 지정 시 월별 평년값 기준)."""
    key = normalize_destination(city)
    if key is None:
        return {"ok": False, "source": "none", "city": city,
                "error": f"지원하지 않는 도시: {city!r}"}
    s = get_settings()
    if date:                                   # 미래/특정일은 평년값
        return _mock(key, date, "date_specified_climatology")
    if s.weather_mode == "mock" or not s.openweather_api_key:
        return _mock(key, None, "no_api_key_or_mock_mode")
    try:
        return _live(key, s.openweather_api_key, s.http_timeout)
    except Exception as exc:                   # 네트워크/HTTP/파싱 오류 -> 폴백 (NFR-02). 클래스명만 기록(URL 의 appid 보호).
        return _mock(key, None, type(exc).__name__)


# ---------------------------------------------------------------- 기간 예보 (여행 계획)

FORECAST_WINDOW_DAYS = 5   # OpenWeather 무료 예보는 5일/3시간 간격


def _climate_day(key: str, d: _date) -> dict:
    """예보 범위 밖 날짜: 가이드 '베스트 시즌과 기후'의 계절 문장, 못 찾으면 안내 문구."""
    from src.rag.guide import OUT_OF_RANGE_NOTE, climate_note
    return {"date": d.isoformat(), "source": "climate", "note": climate_note(key, d.month) or OUT_OF_RANGE_NOTE}


def _mock_day(key: str, d: _date) -> dict:
    temps, rainy_months = _CLIMATE[key]
    t = float(temps[d.month - 1])
    rainy = d.month in rainy_months
    return {"date": d.isoformat(), "tmin": round(t - 3), "tmax": round(t + 3), "condition": "비" if rainy else "맑음",
            "pop": 70 if rainy else 10, "source": "mock"}


def aggregate_forecast(payload: dict) -> dict[str, dict]:
    """OpenWeather /forecast 응답(3시간 간격)을 도시 현지 날짜별로 집계한다.
    {date: {date, tmin, tmax, condition(가장 많이 나온 설명), pop(최대 강수확률 %), source: "forecast"}}"""
    from collections import Counter
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(seconds=int((payload.get("city") or {}).get("timezone") or 0)))
    buckets: dict[str, list[dict]] = {}
    for it in payload.get("list") or []:
        local = datetime.fromtimestamp(int(it["dt"]), tz).date().isoformat()
        buckets.setdefault(local, []).append(it)
    out: dict[str, dict] = {}
    for day, items in sorted(buckets.items()):
        lows = [float(i["main"].get("temp_min", i["main"]["temp"])) for i in items]
        highs = [float(i["main"].get("temp_max", i["main"]["temp"])) for i in items]
        descs = Counter((i.get("weather") or [{}])[0].get("description", "") for i in items)
        out[day] = {"date": day, "tmin": round(min(lows)), "tmax": round(max(highs)),
                    "condition": descs.most_common(1)[0][0] or "정보 없음",
                    "pop": int(round(max(float(i.get("pop") or 0) for i in items) * 100)), "source": "forecast"}
    return out


def _live_forecast(key: str, api_key: str, timeout: float) -> dict[str, dict]:
    info = DESTINATIONS[key]
    r = httpx.get("https://api.openweathermap.org/data/2.5/forecast", timeout=timeout,
                  params={"lat": info["lat"], "lon": info["lon"], "appid": api_key,
                          "units": "metric", "lang": "kr"})
    r.raise_for_status()
    return aggregate_forecast(r.json())


@tool
def get_forecast(city: str, start_date: str, end_date: str) -> dict:
    """여행 기간(start_date~end_date, YYYY-MM-DD)의 날짜별 예보를 조회한다. 약 5일 이내는 OpenWeather 예보
    (source=forecast), 그 밖의 날짜는 가이드의 계절 설명(source=climate). 키가 없거나 실패하면 예시 데이터(mock)."""
    from datetime import timedelta
    key = normalize_destination(city)
    if key is None:
        return {"ok": False, "source": "none", "city": city, "days": [], "error": f"지원하지 않는 도시: {city!r}"}
    try:
        s, e = _date.fromisoformat(start_date), _date.fromisoformat(end_date)
    except (TypeError, ValueError):
        return {"ok": False, "source": "none", "city": key, "days": [], "error": "날짜는 YYYY-MM-DD 형식이어야 합니다"}
    if e < s or (e - s).days >= 14:
        return {"ok": False, "source": "none", "city": key, "days": [], "error": "날짜 범위가 올바르지 않습니다(최대 14일)"}
    dates = [s + timedelta(days=i) for i in range((e - s).days + 1)]
    cfg = get_settings()
    live: dict[str, dict] | None = None
    reason = "no_api_key_or_mock_mode"
    if cfg.weather_mode != "mock" and cfg.openweather_api_key:
        try:
            live = _live_forecast(key, cfg.openweather_api_key, cfg.http_timeout)
        except Exception as exc:               # 클래스명만 기록(URL 의 appid 보호)
            reason = type(exc).__name__
    if live is not None:
        days = [live.get(d.isoformat()) or _climate_day(key, d) for d in dates]
        return {"ok": True, "source": "live", "city": key, "city_ko": DESTINATIONS[key]["ko"], "days": days,
                "fallback_reason": None, "error": None}
    today = _date.today()
    days = [_mock_day(key, d) if 0 <= (d - today).days < FORECAST_WINDOW_DAYS else _climate_day(key, d) for d in dates]
    return {"ok": True, "source": "mock", "city": key, "city_ko": DESTINATIONS[key]["ko"], "days": days,
            "fallback_reason": reason, "error": None}
