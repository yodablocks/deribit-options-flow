"""
signal.py
Converts processed options flow data into SignalEvent format
compatible with signal-pipeline's three-tier trust model.

Trust tier: indexed (tier-2) — Deribit is a centralized exchange,
data is reliable but not chain-native.

Outputs multiple signals per snapshot:
  - pc_ratio     : put/call ratio sentiment
  - iv_skew      : fear/greed gauge
  - net_premium  : directional money flow
  - max_pain     : gravitational price level
  - gamma_wall   : high-OI strike levels (support/resistance)
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Literal


TrustTier = Literal["chain_native", "indexed", "social"]


@dataclass
class SignalEvent:
    source:     str
    signal_type: str
    value:      float
    direction:  Literal["bullish", "bearish", "neutral"]
    magnitude:  float          # 0.0 – 1.0 normalized
    trust:      TrustTier
    ts:         int            # unix ms
    metadata:   dict


def signals_from_snapshot(snapshot: dict, currency: str = "BTC") -> list[SignalEvent]:
    """
    Convert a processed options snapshot into a list of SignalEvents
    ready for signal-pipeline ingestion.
    """
    ts   = snapshot["ts"]
    spot = snapshot["spot_price"]
    events = []

    # ── 1. Put/Call Ratio ────────────────────────────────────────────────────
    pc = snapshot["pc_ratio_oi"]
    # PC > 1.2 = bearish (more puts), PC < 0.8 = bullish (more calls)
    if pc > 1.2:
        pc_direction = "bearish"
        pc_magnitude = min((pc - 1.0) / 1.0, 1.0)
    elif pc < 0.8:
        pc_direction = "bullish"
        pc_magnitude = min((1.0 - pc) / 0.5, 1.0)
    else:
        pc_direction = "neutral"
        pc_magnitude = abs(pc - 1.0) / 0.2

    events.append(SignalEvent(
        source=      f"deribit_{currency.lower()}",
        signal_type= "put_call_ratio",
        value=       pc,
        direction=   pc_direction,
        magnitude=   round(pc_magnitude, 4),
        trust=       "indexed",
        ts=          ts,
        metadata={
            "pc_ratio_vol": snapshot["pc_ratio_vol"],
            "total_call_oi": snapshot["total_call_oi"],
            "total_put_oi":  snapshot["total_put_oi"],
            "spot":          spot,
        }
    ))

    # ── 2. IV Skew ──────────────────────────────────────────────────────────
    skew = snapshot["iv_skew"]
    # Positive skew = put IV > call IV = fear = bearish
    skew_direction = "bearish" if skew > 0.02 else "bullish" if skew < -0.02 else "neutral"
    skew_magnitude = min(abs(skew) / 0.10, 1.0)

    events.append(SignalEvent(
        source=      f"deribit_{currency.lower()}",
        signal_type= "iv_skew",
        value=       skew,
        direction=   skew_direction,
        magnitude=   round(skew_magnitude, 4),
        trust=       "indexed",
        ts=          ts,
        metadata={
            "atm_iv": snapshot["atm_iv"],
            "spot":   spot,
        }
    ))

    # ── 3. Net Premium Flow ─────────────────────────────────────────────────
    net = snapshot["net_premium"]
    # Positive = call premium dominant = bullish
    prem_direction = "bullish" if net > 0 else "bearish"
    total_prem = snapshot["call_premium"] + snapshot["put_premium"]
    prem_magnitude = min(abs(net) / max(total_prem, 1), 1.0) if total_prem > 0 else 0.0

    events.append(SignalEvent(
        source=      f"deribit_{currency.lower()}",
        signal_type= "net_premium_flow",
        value=       net,
        direction=   prem_direction,
        magnitude=   round(prem_magnitude, 4),
        trust=       "indexed",
        ts=          ts,
        metadata={
            "call_premium": snapshot["call_premium"],
            "put_premium":  snapshot["put_premium"],
            "spot":         spot,
        }
    ))

    # ── 4. Max Pain ─────────────────────────────────────────────────────────
    max_pain = snapshot["max_pain"]
    pain_diff = (max_pain - spot) / spot  # positive = max pain above spot
    pain_direction = "bullish" if pain_diff > 0.01 else "bearish" if pain_diff < -0.01 else "neutral"
    pain_magnitude = min(abs(pain_diff) / 0.05, 1.0)

    events.append(SignalEvent(
        source=      f"deribit_{currency.lower()}",
        signal_type= "max_pain",
        value=       max_pain,
        direction=   pain_direction,
        magnitude=   round(pain_magnitude, 4),
        trust=       "indexed",
        ts=          ts,
        metadata={
            "spot":      spot,
            "diff_pct":  round(pain_diff * 100, 2),
        }
    ))

    # ── 5. Gamma Walls ──────────────────────────────────────────────────────
    for strike, oi in snapshot["gamma_walls"][:3]:
        wall_diff = (strike - spot) / spot
        wall_direction = "bullish" if wall_diff > 0 else "bearish"

        events.append(SignalEvent(
            source=      f"deribit_{currency.lower()}",
            signal_type= "gamma_wall",
            value=       strike,
            direction=   wall_direction,
            magnitude=   round(min(oi / 10000, 1.0), 4),
            trust=       "indexed",
            ts=          ts,
            metadata={
                "oi":       oi,
                "spot":     spot,
                "diff_pct": round(wall_diff * 100, 2),
            }
        ))

    return events
