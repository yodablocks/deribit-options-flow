"""
processor.py
Builds options flow signals from raw Deribit book summary data.

Field notes (from API inspection):
  mark_price    — in BTC (not USD). Multiply by underlying_price for USD.
  mark_iv       — already in % form (e.g. 77.55 = 77.55%). Divide by 100.
  open_interest — in BTC. Multiply by spot for USD notional.
  volume        — in BTC contracts.
  volume_usd    — already in USD (use this for premium flow).
  underlying_price — spot price for that expiry (use for USD conversion).
  expiration_timestamp — NOT in summary. Parse from instrument_name.
"""

from collections import defaultdict
from datetime import datetime, timezone
import math


# Map Deribit month codes to month numbers
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_instrument(name: str) -> dict | None:
    """
    Parse Deribit instrument name.
    Format: BTC-28JUN24-70000-C
    Returns: {currency, expiry_str, expiry_dt, strike, option_type}
    """
    try:
        parts = name.split("-")
        if len(parts) != 4:
            return None

        expiry_str = parts[1]  # e.g. "28JUN24"
        day   = int(expiry_str[:2])
        month = _MONTH_MAP.get(expiry_str[2:5].upper(), 0)
        year  = 2000 + int(expiry_str[5:])

        expiry_dt = datetime(year, month, day, 8, 0, 0, tzinfo=timezone.utc)

        return {
            "currency":    parts[0],
            "expiry_str":  expiry_str,
            "expiry_dt":   expiry_dt,
            "expiry_ms":   int(expiry_dt.timestamp() * 1000),
            "strike":      float(parts[2]),
            "option_type": "call" if parts[3] == "C" else "put",
        }
    except (ValueError, IndexError, KeyError):
        return None


def build_signals(summaries: list[dict], spot_price: float) -> dict:
    """
    Process raw option summaries into trading signals.
    """
    # Enrich summaries with parsed metadata
    enriched = []
    for s in summaries:
        parsed = parse_instrument(s.get("instrument_name", ""))
        if not parsed:
            continue
        underlying = float(s.get("underlying_price", spot_price) or spot_price)
        mark_price_btc = float(s.get("mark_price", 0) or 0)
        mark_price_usd = mark_price_btc * underlying
        mark_iv_pct    = float(s.get("mark_iv", 0) or 0)
        mark_iv        = mark_iv_pct / 100.0  # convert to decimal

        enriched.append({
            **s,
            **parsed,
            "mark_price_usd": mark_price_usd,
            "mark_iv_dec":    mark_iv,
            "underlying":     underlying,
        })

    calls = [e for e in enriched if e["option_type"] == "call"]
    puts  = [e for e in enriched if e["option_type"] == "put"]

    # OI in BTC
    total_call_oi  = sum(float(e.get("open_interest", 0)) for e in calls)
    total_put_oi   = sum(float(e.get("open_interest", 0)) for e in puts)

    # Volume in BTC
    total_call_vol = sum(float(e.get("volume", 0)) for e in calls)
    total_put_vol  = sum(float(e.get("volume", 0)) for e in puts)

    # Put/Call ratios
    pc_ratio_oi  = total_put_oi  / total_call_oi  if total_call_oi  > 0 else 1.0
    pc_ratio_vol = total_put_vol / total_call_vol if total_call_vol > 0 else 1.0

    # Premium flow in USD (use volume_usd which is already in USD)
    call_premium_usd = sum(float(e.get("volume_usd", 0)) for e in calls)
    put_premium_usd  = sum(float(e.get("volume_usd", 0)) for e in puts)
    net_premium      = call_premium_usd - put_premium_usd

    # OI by strike (in BTC)
    oi_by_strike = defaultdict(lambda: {"call": 0.0, "put": 0.0, "total": 0.0})
    for e in enriched:
        strike = e["strike"]
        oi     = float(e.get("open_interest", 0))
        otype  = e["option_type"]
        oi_by_strike[strike][otype] += oi
        oi_by_strike[strike]["total"] += oi

    # Max pain
    max_pain_strike = _calc_max_pain(oi_by_strike, spot_price)

    # Term structure
    term_structure = _calc_term_structure(enriched)

    # IV skew (25-delta proxy)
    iv_skew = _calc_iv_skew(enriched, spot_price)

    # ATM IV (nearest expiry, nearest strike)
    atm_iv = _calc_atm_iv(enriched, spot_price)

    # Gamma walls — top strikes by OI within 15% of spot
    gamma_walls = sorted(
        [(strike, data["total"]) for strike, data in oi_by_strike.items()
         if abs(strike - spot_price) / spot_price < 0.15],
        key=lambda x: x[1],
        reverse=True,
    )[:5]

    return {
        "spot_price":     spot_price,
        "pc_ratio_oi":    round(pc_ratio_oi, 4),
        "pc_ratio_vol":   round(pc_ratio_vol, 4),
        "net_premium":    round(net_premium, 0),
        "call_premium":   round(call_premium_usd, 0),
        "put_premium":    round(put_premium_usd, 0),
        "total_call_oi":  round(total_call_oi, 2),
        "total_put_oi":   round(total_put_oi, 2),
        "atm_iv":         round(atm_iv, 4),
        "iv_skew":        round(iv_skew, 4),
        "max_pain":       max_pain_strike,
        "gamma_walls":    gamma_walls,
        "term_structure": term_structure,
        "ts":             int(datetime.now(tz=timezone.utc).timestamp() * 1000),
    }


def _calc_max_pain(oi_by_strike: dict, spot: float) -> float:
    if not oi_by_strike:
        return spot
    strikes   = sorted(oi_by_strike.keys())
    min_pain  = float("inf")
    max_pain_strike = spot
    for test_strike in strikes:
        total_pain = sum(
            max(0, test_strike - s) * d["call"] +
            max(0, s - test_strike) * d["put"]
            for s, d in oi_by_strike.items()
        )
        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = test_strike
    return max_pain_strike


def _calc_atm_iv(enriched: list[dict], spot: float) -> float:
    candidates = []
    for e in enriched:
        iv   = e.get("mark_iv_dec", 0)
        if iv <= 0:
            continue
        dist = abs(e["strike"] - spot)
        exp  = e["expiry_ms"]
        candidates.append((exp, dist, iv))
    if not candidates:
        return 0.0
    candidates.sort()
    nearest_exp = candidates[0][0]
    same_exp = [(d, iv) for ex, d, iv in candidates if ex == nearest_exp]
    same_exp.sort()
    return same_exp[0][1] if same_exp else 0.0


def _calc_iv_skew(enriched: list[dict], spot: float) -> float:
    """
    25-delta skew proxy: put IV at 90% spot minus call IV at 110% spot.
    Positive = put skew = fear. Negative = call skew = greed.
    Uses nearest expiry only for consistency.
    """
    if not enriched:
        return 0.0

    # Find nearest expiry
    nearest_exp = min(e["expiry_ms"] for e in enriched)
    near = [e for e in enriched if e["expiry_ms"] == nearest_exp]

    put_iv  = _find_nearest_iv(near, spot * 0.90, "put")
    call_iv = _find_nearest_iv(near, spot * 1.10, "call")
    return put_iv - call_iv


def _find_nearest_iv(enriched: list[dict], target: float,
                     option_type: str) -> float:
    best_dist = float("inf")
    best_iv   = 0.0
    for e in enriched:
        if e["option_type"] != option_type:
            continue
        iv   = e.get("mark_iv_dec", 0)
        dist = abs(e["strike"] - target)
        if dist < best_dist and iv > 0:
            best_dist = dist
            best_iv   = iv
    return best_iv


def _calc_term_structure(enriched: list[dict]) -> list[dict]:
    by_expiry = defaultdict(list)
    for e in enriched:
        iv = e.get("mark_iv_dec", 0)
        if iv > 0:
            by_expiry[(e["expiry_ms"], e["expiry_str"])].append(iv)

    result = []
    for (exp_ms, exp_str), ivs in sorted(by_expiry.items()):
        result.append({
            "expiry":    exp_str,
            "expiry_ms": exp_ms,
            "avg_iv":    round(sum(ivs) / len(ivs), 4),
            "n":         len(ivs),
        })
    return result
