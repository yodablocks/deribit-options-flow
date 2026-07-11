"""
fetcher.py
Deribit public API — no auth required for market data.

Endpoints used:
  GET /api/v2/public/get_book_summary_by_currency
    → all active options for BTC/ETH with OI, volume, IV, mark price
  GET /api/v2/public/get_index_price
    → current spot reference price
  GET /api/v2/public/ticker?instrument_name=BTC-PERPETUAL
    → perp reference (for basis calculation)
"""

import requests
from datetime import datetime, timezone

BASE = "https://www.deribit.com/api/v2"


def _get(endpoint: str, params: dict = {}) -> dict:
    r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Deribit error: {data['error']}")
    return data["result"]


def fetch_options_summary(currency: str = "BTC") -> list[dict]:
    """
    Fetch all active options for a currency.
    Returns list of instruments with:
      instrument_name, expiration_timestamp, strike, option_type (call/put),
      open_interest, volume, bid_iv, ask_iv, mark_iv, underlying_price
    """
    result = _get("public/get_book_summary_by_currency", {
        "currency": currency,
        "kind": "option",
    })
    return result if isinstance(result, list) else []


def fetch_index_price(currency: str = "BTC") -> float:
    """Current spot index price."""
    result = _get("public/get_index_price", {
        "index_name": f"{currency.lower()}_usd"
    })
    return float(result.get("index_price", 0))


def fetch_ticker(instrument_name: str) -> dict:
    """Full ticker for a specific instrument including Greeks."""
    return _get("public/ticker", {"instrument_name": instrument_name})


def fetch_instruments(currency: str = "BTC") -> list[dict]:
    """All active option instruments with strike/expiry metadata."""
    result = _get("public/get_instruments", {
        "currency": currency,
        "kind": "option",
        "expired": False,
    })
    return result if isinstance(result, list) else []
