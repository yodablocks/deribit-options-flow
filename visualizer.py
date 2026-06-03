"""
visualizer.py
OI heatmap by strike × expiry — Deribit options

Layout:
  Main heatmap: strike (y) × expiry (x)
    - Cell color: red = put dominant, green = call dominant
    - Cell intensity: OI magnitude
    - Cell text: total OI in BTC
  Right panel: total OI per strike (bar chart)
  Top panel: total OI per expiry (bar chart)
  Overlays: spot price line, max pain marker
"""

import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
from collections import defaultdict
from processor import parse_instrument


BG_COLOR     = "#0D0D0F"
SURFACE      = "#14141A"
GRID_COLOR   = "#252530"
TEXT_PRIMARY = "#E8E6E1"
TEXT_SEC     = "#666680"
CALL_COLOR   = "#27AE7A"
PUT_COLOR    = "#E05252"
SPOT_COLOR   = "#FFD700"
PAIN_COLOR   = "#FF8C00"


def _fmt_oi(n: float) -> str:
    if n >= 1000:
        return f"{n/1000:.1f}K"
    return f"{n:.0f}"


def _fmt_strike(s: float) -> str:
    return f"${s/1000:.0f}K"


def plot_oi_heatmap(
    summaries: list[dict],
    spot_price: float,
    max_pain: float,
    currency: str = "BTC",
    output: str | None = None,
) -> None:
    """
    Render OI heatmap: strike (y) × expiry (x).
    """
    # ── parse and bucket data ─────────────────────────────────────────────
    # { strike: { expiry_str: { call: oi, put: oi } } }
    data = defaultdict(lambda: defaultdict(lambda: {"call": 0.0, "put": 0.0}))
    expiry_order = {}  # expiry_str → expiry_ms for sorting

    for s in summaries:
        parsed = parse_instrument(s.get("instrument_name", ""))
        if not parsed:
            continue
        oi     = float(s.get("open_interest", 0))
        strike = parsed["strike"]
        expiry = parsed["expiry_str"]
        otype  = parsed["option_type"]
        exp_ms = parsed["expiry_ms"]

        data[strike][expiry][otype] += oi
        expiry_order[expiry] = exp_ms

    if not data:
        print("[viz] No data.")
        return

    # Filter strikes within 30% of spot for readability
    strikes = sorted([
        s for s in data.keys()
        if abs(s - spot_price) / spot_price < 0.30
    ], reverse=True)  # high → low on y-axis

    expiries = sorted(expiry_order.keys(), key=lambda e: expiry_order[e])

    if not strikes or not expiries:
        print("[viz] No strikes/expiries in range.")
        return

    n_strikes  = len(strikes)
    n_expiries = len(expiries)

    strike_idx = {s: i for i, s in enumerate(strikes)}
    expiry_idx = {e: i for i, e in enumerate(expiries)}

    # Build grids
    call_grid  = np.zeros((n_strikes, n_expiries))
    put_grid   = np.zeros((n_strikes, n_expiries))

    for strike, exp_data in data.items():
        if strike not in strike_idx:
            continue
        si = strike_idx[strike]
        for expiry, sides in exp_data.items():
            if expiry not in expiry_idx:
                continue
            ei = expiry_idx[expiry]
            call_grid[si, ei] = sides["call"]
            put_grid[si, ei]  = sides["put"]

    total_grid = call_grid + put_grid
    max_oi     = total_grid.max() or 1.0

    # Strike totals (for right bar)
    strike_totals = total_grid.sum(axis=1)
    # Expiry totals (for top bar)
    expiry_totals = total_grid.sum(axis=0)

    # ── figure layout ─────────────────────────────────────────────────────
    plt.rcParams.update({
        "figure.facecolor": BG_COLOR,
        "axes.facecolor":   SURFACE,
        "axes.edgecolor":   GRID_COLOR,
        "text.color":       TEXT_PRIMARY,
        "xtick.color":      TEXT_SEC,
        "ytick.color":      TEXT_PRIMARY,
        "font.family":      "monospace",
        "font.size":        8,
    })

    fig_w = max(14, n_expiries * 1.1 + 4)
    fig_h = max(10, n_strikes * 0.45 + 3)

    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=BG_COLOR)

    gs = fig.add_gridspec(
        2, 2,
        width_ratios=[4, 1],
        height_ratios=[1, 4],
        left=0.08, right=0.97,
        top=0.88, bottom=0.10,
        hspace=0.04, wspace=0.04,
    )

    ax_top  = fig.add_subplot(gs[0, 0])   # expiry OI bar
    ax_heat = fig.add_subplot(gs[1, 0])   # main heatmap
    ax_right = fig.add_subplot(gs[1, 1])  # strike OI bar
    ax_corner = fig.add_subplot(gs[0, 1]) # empty corner
    ax_corner.set_visible(False)

    y_pos = np.arange(n_strikes)
    x_pos = np.arange(n_expiries)

    # ── main heatmap ──────────────────────────────────────────────────────
    rgba = np.zeros((n_strikes, n_expiries, 4))

    for si in range(n_strikes):
        for ei in range(n_expiries):
            c = call_grid[si, ei]
            p = put_grid[si, ei]
            t = c + p
            if t == 0:
                continue
            intensity = min(t / max_oi, 1.0) ** 0.5
            if c >= p:
                r, g, b_ = mcolors.to_rgb(CALL_COLOR)
            else:
                r, g, b_ = mcolors.to_rgb(PUT_COLOR)
            rgba[si, ei] = [r, g, b_, intensity * 0.9]

    ax_heat.imshow(
        rgba, aspect="auto", origin="upper",
        extent=[-0.5, n_expiries - 0.5, n_strikes - 0.5, -0.5],
        interpolation="nearest",
    )

    # Grid lines
    for xi in range(n_expiries + 1):
        ax_heat.axvline(xi - 0.5, color=GRID_COLOR, linewidth=0.4, alpha=0.6)
    for yi in range(n_strikes + 1):
        ax_heat.axhline(yi - 0.5, color=GRID_COLOR, linewidth=0.4, alpha=0.6)

    # OI text in cells (only if large enough)
    threshold = max_oi * 0.05
    for si in range(n_strikes):
        for ei in range(n_expiries):
            t = total_grid[si, ei]
            if t >= threshold:
                ax_heat.text(ei, si, _fmt_oi(t),
                    ha="center", va="center",
                    fontsize=6, color="white", alpha=0.9, fontweight="bold")

    # Spot price line
    spot_y = None
    for i, strike in enumerate(strikes):
        if strike <= spot_price:
            spot_y = i - 0.5
            break
    if spot_y is not None:
        ax_heat.axhline(spot_y, color=SPOT_COLOR, linewidth=1.5,
                        linestyle="--", alpha=0.8, zorder=5)
        ax_heat.text(-0.45, spot_y - 0.3, f"Spot ${spot_price:,.0f}",
                     color=SPOT_COLOR, fontsize=7, fontweight="bold")

    # Max pain marker
    if max_pain in strike_idx:
        pain_y = strike_idx[max_pain]
        ax_heat.axhline(pain_y, color=PAIN_COLOR, linewidth=1.0,
                        linestyle=":", alpha=0.7, zorder=5)
        ax_heat.text(n_expiries - 0.55, pain_y - 0.3,
                     f"Max pain ${max_pain:,.0f}",
                     color=PAIN_COLOR, fontsize=6.5,
                     ha="right", fontweight="bold")

    # Axes
    ax_heat.set_yticks(y_pos)
    ax_heat.set_yticklabels([_fmt_strike(s) for s in strikes], fontsize=7.5)
    ax_heat.set_xticks(x_pos)
    ax_heat.set_xticklabels(expiries, rotation=45, ha="right", fontsize=7.5,
                             color=TEXT_SEC)
    ax_heat.set_facecolor(SURFACE)
    ax_heat.spines[:].set_color(GRID_COLOR)
    ax_heat.tick_params(length=0)

    # ── top bar: OI per expiry ────────────────────────────────────────────
    call_by_exp = call_grid.sum(axis=0)
    put_by_exp  = put_grid.sum(axis=0)

    ax_top.bar(x_pos, call_by_exp, color=CALL_COLOR, alpha=0.8, width=0.7)
    ax_top.bar(x_pos, put_by_exp,  color=PUT_COLOR,  alpha=0.8, width=0.7,
               bottom=call_by_exp)
    ax_top.set_xlim(-0.5, n_expiries - 0.5)
    ax_top.set_xticks([])
    ax_top.set_ylabel("OI (BTC)", fontsize=7, color=TEXT_SEC)
    ax_top.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: _fmt_oi(x)))
    ax_top.tick_params(axis="y", labelsize=6.5, colors=TEXT_SEC)
    ax_top.set_facecolor(SURFACE)
    ax_top.spines[:].set_color(GRID_COLOR)
    ax_top.grid(axis="y", color=GRID_COLOR, linewidth=0.3, alpha=0.5)

    # ── right bar: OI per strike ──────────────────────────────────────────
    call_by_strike = call_grid.sum(axis=1)
    put_by_strike  = put_grid.sum(axis=1)

    ax_right.barh(y_pos, call_by_strike, color=CALL_COLOR, alpha=0.8, height=0.7)
    ax_right.barh(y_pos, put_by_strike,  color=PUT_COLOR,  alpha=0.8, height=0.7,
                  left=call_by_strike)
    ax_right.set_ylim(n_strikes - 0.5, -0.5)
    ax_right.set_yticks([])
    ax_right.set_xlabel("OI (BTC)", fontsize=7, color=TEXT_SEC)
    ax_right.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: _fmt_oi(x)))
    ax_right.tick_params(axis="x", labelsize=6.5, colors=TEXT_SEC, rotation=30)
    ax_right.set_facecolor(SURFACE)
    ax_right.spines[:].set_color(GRID_COLOR)
    ax_right.grid(axis="x", color=GRID_COLOR, linewidth=0.3, alpha=0.5)

    # ── legend + title ────────────────────────────────────────────────────
    legend_handles = [
        mpatches.Patch(color=CALL_COLOR, label="Call OI dominant"),
        mpatches.Patch(color=PUT_COLOR,  label="Put OI dominant"),
        mpatches.Patch(color=SPOT_COLOR, label=f"Spot ${spot_price:,.0f}"),
        mpatches.Patch(color=PAIN_COLOR, label=f"Max pain ${max_pain:,.0f}"),
    ]
    ax_heat.legend(handles=legend_handles, loc="lower left", fontsize=7,
                   facecolor="#1A1A22", edgecolor=GRID_COLOR,
                   labelcolor=TEXT_PRIMARY, framealpha=0.9)

    total_oi = total_grid.sum()
    call_pct = call_grid.sum() / total_oi * 100 if total_oi > 0 else 50

    fig.suptitle(
        f"{currency} Options OI Heatmap  ·  Strike × Expiry  ·  "
        f"Strikes within 30% of spot",
        fontsize=12, fontweight="bold", color=TEXT_PRIMARY, y=0.96,
    )
    fig.text(
        0.5, 0.925,
        f"Total OI: {_fmt_oi(total_oi)} BTC  ·  "
        f"Calls {call_pct:.0f}% / Puts {100-call_pct:.0f}%  ·  "
        f"Source: Deribit public API",
        ha="center", fontsize=8, color=TEXT_SEC,
    )

    if output:
        plt.savefig(output, dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
        print(f"[viz] Saved → {output}")
    else:
        plt.show()

    plt.close(fig)
