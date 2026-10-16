"""T-08 ~ T-12 날씨/환율 Tool."""
import json

import httpx
import pytest

from src.config import get_settings
from src.tools.exchange import convert_currency
from src.tools.weather import get_weather

WEATHER_KEYS = {"ok", "source", "city", "city_ko", "date", "temp_c", "feels_like_c", "condition",
                "humidity", "advice", "fallback_reason", "error"}


@pytest.mark.parametrize("city", ["tokyo", "paris", "bangkok", "newyork", "jeju", "도쿄"])
def test_weather_mock_all_cities(city):
    r = get_weather.invoke({"city": city})
    assert r["ok"] and r["source"] == "mock" and WEATHER_KEYS <= r.keys()


def test_weather_date_uses_climatology():
    r = get_weather.invoke({"city": "tokyo", "date": "2026-01-10"})
    assert r["temp_c"] == 5.0 and r["fallback_reason"] == "date_specified_climatology"


def test_weather_unknown_city():
    assert get_weather.invoke({"city": "atlantis"})["ok"] is False


def test_weather_live_failure_falls_back(monkeypatch):
    monkeypatch.setenv("WEATHER_MODE", "auto")
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-secret-key")
    get_settings.cache_clear()

    def boom(*a, **k):
        raise httpx.ConnectError("down https://x?appid=dummy-secret-key")
    monkeypatch.setattr("src.tools.weather.httpx.get", boom)
    r = get_weather.invoke({"city": "tokyo"})
    assert r["ok"] and r["source"] == "mock" and r["fallback_reason"] == "ConnectError"
    assert "dummy-secret-key" not in json.dumps(r)


def test_weather_live_success(monkeypatch):
    monkeypatch.setenv("WEATHER_MODE", "auto")
    monkeypatch.setenv("OPENWEATHER_API_KEY", "k")
    get_settings.cache_clear()

    class R:
        def raise_for_status(self): pass
        def json(self): return {"main": {"temp": 21.5, "feels_like": 21.0, "humidity": 60},
                                "weather": [{"description": "구름 조금"}]}
    monkeypatch.setattr("src.tools.weather.httpx.get", lambda *a, **k: R())
    r = get_weather.invoke({"city": "paris"})
    assert r["source"] == "live" and r["temp_c"] == 21.5 and r["fallback_reason"] is None


@pytest.mark.parametrize("cur,per_krw", [("JPY", 0.1087), ("EUR", 0.000625), ("THB", 0.0244), ("USD", 0.000725)])
def test_exchange_mock_rates(cur, per_krw):
    r = convert_currency.invoke({"amount": 1_000_000, "to_currency": cur})
    assert r["ok"] and r["source"] == "mock" and r["base"] == "KRW"
    assert r["converted"] == pytest.approx(1_000_000 * per_krw, rel=1e-6)


def test_exchange_mock_krw_to_jpy():
    r = convert_currency.invoke({"amount": 1_000_000, "to_currency": "JPY"})
    assert r["ok"] and abs(r["converted"] - 108_700) < 1


def test_exchange_foreign_to_krw_cross_rate():
    r = convert_currency.invoke({"amount": 100, "to_currency": "KRW", "from_currency": "USD"})
    assert r["ok"] and r["converted"] == pytest.approx(100 / 0.000725, rel=1e-6)


@pytest.mark.parametrize("amount", [0, -5])
def test_exchange_invalid_amount(amount):
    assert convert_currency.invoke({"amount": amount, "to_currency": "JPY"})["ok"] is False


def test_exchange_same_currency():
    r = convert_currency.invoke({"amount": 5, "to_currency": "KRW"})
    assert r["ok"] and r["rate"] == 1.0


def test_exchange_unsupported_currency():
    assert convert_currency.invoke({"amount": 5, "to_currency": "XXX"})["ok"] is False


def test_exchange_live_failure_falls_back(monkeypatch):
    monkeypatch.setenv("EXCHANGE_MODE", "auto")
    get_settings.cache_clear()

    def boom(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr("src.tools.exchange.httpx.get", boom)
    r = convert_currency.invoke({"amount": 1000, "to_currency": "JPY"})
    assert r["ok"] and r["source"] == "mock" and r["fallback_reason"] == "ReadTimeout"


def test_exchange_live_success(monkeypatch):
    monkeypatch.setenv("EXCHANGE_MODE", "auto")
    get_settings.cache_clear()

    class R:
        def raise_for_status(self): pass
        def json(self): return {"result": "success", "rates": {"JPY": 0.11}, "time_last_update_utc": "now"}
    monkeypatch.setattr("src.tools.exchange.httpx.get", lambda *a, **k: R())
    r = convert_currency.invoke({"amount": 1000, "to_currency": "JPY"})
    assert r["source"] == "live" and r["rate"] == 0.11 and r["rate_date"] == "now"
