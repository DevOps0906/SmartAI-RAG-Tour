"""exchange_tool - 환율 계산 노드 (FR-05)."""
from src.nodes.common import add_error, pop_task
from src.state import TravelState
from src.tools.exchange import convert_currency


def exchange_tool(state: TravelState) -> dict:
    ent = state.get("entities", {})
    exchange, errors = None, state.get("errors", [])
    amount_cur = (ent.get("amount_currency") or "KRW").upper()
    if amount_cur == "KRW":   # 기본: 원화 -> 목적지 통화
        base, target = "KRW", ent.get("currency") or ""
    else:                     # '100달러' 처럼 외화 금액을 말한 경우: 외화 -> 원화
        base, target = amount_cur, "KRW"
    try:
        res = convert_currency.invoke({
            "amount": ent.get("amount") or 1_000_000.0,
            "to_currency": target,
            "from_currency": base,
        })
        if res.get("ok"):
            exchange = res
        else:
            errors = add_error(state, f"exchange_tool: {res.get('error')}")
    except Exception as exc:
        errors = add_error(state, f"exchange_tool: {type(exc).__name__}")
    return {"exchange": exchange, "pending_intents": pop_task(state, "exchange"),
            "errors": errors, "step_count": state.get("step_count", 0) + 1}
