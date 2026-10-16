"""weather_tool - 날씨 조회 노드 (FR-04). trip 이 있으면 여행 기간 예보도 함께 가져온다 (FR-11)."""
from src.nodes.common import add_error, pop_task
from src.state import TravelState
from src.tools.weather import get_forecast, get_weather


def _fetch_forecast(state: TravelState, errors: list[str]) -> tuple[list[dict], list[str]]:
    """같은 도시의 trip 이 있을 때만 기간 예보를 조회한다. 실패해도 예외를 밖으로 던지지 않는다."""
    trip = state.get("trip")
    ent = state.get("entities", {})
    if not trip or trip.get("destination") != ent.get("destination"):
        return list(state.get("forecast") or []), errors
    try:
        res = get_forecast.invoke({"city": trip["destination"], "start_date": trip["start_date"],
                                   "end_date": trip["end_date"]})
        if res.get("ok"):
            return list(res["days"]), errors
        return [], add_error({"errors": errors}, f"weather_tool: 기간 예보 {res.get('error')}")
    except Exception as exc:
        return [], add_error({"errors": errors}, f"weather_tool: 기간 예보 {type(exc).__name__}")


def weather_tool(state: TravelState) -> dict:
    ent = state.get("entities", {})
    weather, errors = None, state.get("errors", [])
    try:
        res = get_weather.invoke({"city": ent.get("destination") or "", "date": ent.get("travel_date")})
        if res.get("ok"):
            weather = res
        else:
            errors = add_error(state, f"weather_tool: {res.get('error')}")
    except Exception as exc:
        errors = add_error(state, f"weather_tool: {type(exc).__name__}")
    forecast, errors = _fetch_forecast(state, errors)
    out = {"weather": weather, "pending_intents": pop_task(state, "weather"),
           "errors": errors, "step_count": state.get("step_count", 0) + 1}
    if state.get("trip"):
        out["forecast"] = forecast
    return out
