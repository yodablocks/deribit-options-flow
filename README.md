# deribit-options-flow

Deribit BTC/ETH options flow signals — no API key required.

Tracks where sophisticated money is positioned in options markets, which leads perp liquidation cascades on Hyperliquid by 1-4 hours. Feeds into `signal-pipeline` as a tier-2 indexed source.

## Live output example

```
=== Deribit Options Flow | BTC ===

  Put/Call Ratio (OI)  : 0.619  ⬇ bullish
  IV Skew (25d proxy)  : +19.07%  (fear)
  Net Premium Flow     : $-7,522,676  (puts dominant ↓)
  ATM IV               : 45.7%
  Max Pain             : $75,000  (spot diff: +13.9%)

  Gamma Walls (top 3 OI within 15% of spot):
    $60,000  OI=18,048 BTC  (-8.9% from spot)
    $70,000  OI=15,284 BTC  (+6.3% from spot)
    $75,000  OI=14,810 BTC  (+13.9% from spot)

  Term Structure (avg IV by expiry):
       12JUN26  IV=51.4%  (58 strikes)
       19JUN26  IV=45.3%  (46 strikes)
       26JUN26  IV=70.1%  (118 strikes)  ← event premium
       31JUL26  IV=42.7%  (104 strikes)
       28AUG26  IV=41.1%  (86 strikes)
       25SEP26  IV=48.0%  (116 strikes)
       25DEC26  IV=46.3%  (114 strikes)
       26MAR27  IV=44.5%  (92 strikes)
```

## How to read the signals

**Put/Call Ratio (OI-weighted)**
Ratio of total put OI to total call OI across all strikes and expiries.
- `< 0.8` — calls dominate, market is bullish positioned
- `> 1.2` — puts dominate, market is hedged/bearish
- The example (0.619) shows existing positioning is long-biased

**IV Skew**
25-delta proxy: put IV at 90% of spot minus call IV at 110% of spot.
Positive = puts more expensive = fear premium in the tail.
- The example (+19%) means even though positioning is bullish,
  the market is paying a significant premium to hedge downside.
  Classic late-cycle pattern: long but nervous.

**Net Premium Flow**
Call volume (USD) minus put volume (USD) for the day.
Reflects where actual money moved today, not existing positioning.
- The example (-$7.5M) means today's flow went into puts —
  contradicting the bullish OI ratio. Recent hedging despite long bias.
  This P/C OI vs net premium divergence is the most actionable signal.

**Max Pain**
Strike where the total payout to option holders is minimized.
Market makers are naturally hedged here — acts as a gravitational pull
toward expiry. The example ($75,000, +13.9% above spot) suggests
upside pressure into the next expiry.

**Gamma Walls**
Strikes with the highest open interest near spot (within 15%).
Dealers delta-hedge heavily at these levels, creating natural
support/resistance. The example shows:
- `$60,000` — strong support floor (-8.9%)
- `$70,000` — resistance level (+6.3%)
- `$75,000` — max pain coincides with gamma wall (strong magnet)

**Term Structure**
Average IV per expiry. Normal = upward sloping (more uncertainty further out).
Spikes at specific expiries signal event risk being priced in.
The 26JUN26 spike to 70.1% (vs 45% for adjacent expiries) indicates
the market is pricing a specific catalyst around that date.

## Why this leads HL liquidations

```
Deribit large put buying
    → market maker delta hedge (short perps on HL/Binance)
        → selling pressure moves HL price
            → hits liquidation clusters from hl-liquidation-heatmap
                → cascade amplifies the move
                    → more put buying (feedback loop)
```

Options positioning leads perp liquidations by 1-4 hours.
Combined with `hl-liquidation-heatmap` you get:
- **Direction + timing** — from options flow
- **Price targets** — from liquidation cluster map

## Setup

```bash
pip install -r requirements.txt
```

No API key required — Deribit public endpoints only.

## Usage

```bash
# Snapshot with full signal output
python main.py --currency BTC

# ETH options
python main.py --currency ETH

# JSON output for signal-pipeline ingestion
python main.py --currency BTC --output json
```

## signal-pipeline integration

```python
from fetcher import fetch_options_summary, fetch_index_price
from processor import build_signals
from signal import signals_from_snapshot

spot     = fetch_index_price("BTC")
summary  = fetch_options_summary("BTC")
snapshot = build_signals(summary, spot)
events   = signals_from_snapshot(snapshot, "BTC")
# → list[SignalEvent] with trust="indexed", ready for signal-pipeline
```

## Structure

```
deribit-options-flow/
├── fetcher.py    # Deribit public REST API
├── processor.py  # P/C ratio, IV skew, max pain, gamma walls, term structure
├── signal.py     # SignalEvent output for signal-pipeline
├── main.py       # CLI entrypoint
└── requirements.txt
```

## Roadmap

- [ ] WebSocket streaming for live IV updates
- [ ] OI heatmap by strike (visual, like hl-liquidation-heatmap)
- [ ] Cross-signal: options flow × HL liquidation level correlation
- [ ] ETH options flow (same pipeline, different currency)
