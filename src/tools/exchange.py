"""환율 Tool (FR-05). open.er-api.com(무키) -> 실패 시 mock 환율표 폴백. 예외를 밖으로 던지지 않는다."""
import httpx
from langchain_core.tools import tool

from src.config import get_settings

# mock: 1 KRW 당 각 통화 (대략값, 실제 시세와 다를 수 있음)
_MOCK_PER_KRW = {"KRW": 1.0, "JPY": 0.1087, "EUR": 0.000625, "THB": 0.0244, "USD": 0.000725}


def _mock_rate(base: str, target: str) -> float | None:
    if base not in _MOCK_PER_KRW or target not in _MOCK_PER_KRW:
        return None
    return _MOCK_PER_KRW[target] / _MOCK_PER_KRW[base]   # 교차환율


def _result(base, target, amount, rate, source, rate_date=None, reason=None) -> dict:
    return {"ok": True, "source": source, "base": base, "target": target, "rate": rate,
            "amount": amount, "converted": round(amount * rate, 4), "rate_date": rate_date,
            "fallback_reason": reason, "error": None}


@tool
def convert_currency(amount: float, to_currency: str, from_currency: str = "KRW") -> dict:
    """금액을 환산한다. 기본 기준 통화는 KRW. 통화는 ISO 4217 코드(JPY, EUR, THB, USD, KRW)."""
    base, target = (from_currency or "").upper().strip(), (to_currency or "").upper().strip()
    if amount is None or amount <= 0:
        return {"ok": False, "source": "none", "error": "금액은 0보다 커야 합니다"}
    if not target:
        return {"ok": False, "source": "none", "error": "대상 통화가 없습니다"}
    if base == target:
        return _result(base, target, amount, 1.0, "mock", reason="same_currency")

    s = get_settings()
    reason = "mock_mode"
    if s.exchange_mode != "mock":
        try:
            r = httpx.get(f"{s.exchange_api_base}/{base}", timeout=s.http_timeout)
            r.raise_for_status()
            j = r.json()
            if j.get("result") == "success" and target in j.get("rates", {}):
                return _result(base, target, amount, float(j["rates"][target]), "live",
                               rate_date=j.get("time_last_update_utc"))
            reason = "rate_not_in_response"
        except Exception as exc:               # 클래스명만 기록
            reason = type(exc).__name__
    rate = _mock_rate(base, target)
    if rate is None:
        return {"ok": False, "source": "none", "error": f"지원하지 않는 통화: {base}->{target}"}
    return _result(base, target, amount, rate, "mock", reason=reason)
