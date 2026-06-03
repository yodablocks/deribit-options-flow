"""
deribit-options-flow — CLI entrypoint
"""

import argparse
import json
import dataclasses
from fetcher import fetch_options_summary, fetch_index_price
from processor import build_signals
from signal import signals_from_snapshot


def main():
    parser = argparse.ArgumentParser(description="Deribit options flow signals")
    parser.add_argument("--currency", default="BTC", choices=["BTC", "ETH"])
    parser.add_argument("--output",   default="print", choices=["print", "json"])
    parser.add_argument("--heatmap",  default=None,
                        help="Render OI heatmap and save to file (e.g. oi.png)")
    args = parser.parse_args()

    print(f"\n=== Deribit Options Flow | {args.currency} ===\n")

    print(f"[1/3] Fetching spot price...")
    spot = fetch_index_price(args.currency)
    print(f"      {args.currency} spot: ${spot:,.0f}")

    print(f"[2/3] Fetching options chain...")
    summaries = fetch_options_summary(args.currency)
    print(f"      {len(summaries)} instruments")

    print(f"[3/3] Building signals...\n")
    snapshot = build_signals(summaries, spot)

    pc   = snapshot["pc_ratio_oi"]
    skew = snapshot["iv_skew"]
    net  = snapshot["net_premium"]

    print(f"  Put/Call Ratio (OI)  : {pc:.3f}  "
          f"{'⬆ bearish' if pc > 1.2 else '⬇ bullish' if pc < 0.8 else '→ neutral'}")
    print(f"  IV Skew (25d proxy)  : {skew*100:+.2f}%  "
          f"({'fear' if skew > 0.02 else 'greed' if skew < -0.02 else 'neutral'})")
    print(f"  Net Premium Flow     : ${net:,.0f}  "
          f"({'calls dominant ↑' if net > 0 else 'puts dominant ↓'})")
    print(f"  ATM IV               : {snapshot['atm_iv']*100:.1f}%")
    print(f"  Max Pain             : ${snapshot['max_pain']:,.0f}  "
          f"(spot diff: {(snapshot['max_pain']-spot)/spot*100:+.1f}%)")

    print(f"\n  Gamma Walls (top 3 OI within 15% of spot):")
    for strike, oi in snapshot["gamma_walls"][:3]:
        diff = (strike - spot) / spot * 100
        print(f"    ${strike:,.0f}  OI={oi:,.1f} BTC  ({diff:+.1f}% from spot)")

    print(f"\n  Term Structure (avg IV by expiry):")
    for t in snapshot["term_structure"][:8]:
        print(f"    {t['expiry']:>10}  IV={t['avg_iv']*100:.1f}%  ({t['n']} strikes)")

    events = signals_from_snapshot(snapshot, args.currency)
    print(f"\n  → {len(events)} SignalEvents generated")

    if args.output == "json":
        print(json.dumps([dataclasses.asdict(e) for e in events], indent=2))

    if args.heatmap:
        print(f"\n[viz]  Rendering OI heatmap...")
        from visualizer import plot_oi_heatmap
        plot_oi_heatmap(
            summaries=summaries,
            spot_price=spot,
            max_pain=snapshot["max_pain"],
            currency=args.currency,
            output=args.heatmap,
        )


if __name__ == "__main__":
    main()
