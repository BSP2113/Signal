#!/usr/bin/env python3
"""Regime-filter first-order screen — lever #2 follow-up (2026-05-22).

The extended sim showed the edge is regime-dependent. This screens SPY-trend
gates: for each 'only trade market-uptrend days' rule, sum the uptrend days'
P&L from the completed 181-day run (scratch_extended.json). The current
BULL/NEUT/BEAR state is a one-day pre-market gap; this instead tests a
multi-day SPY TREND, which is what a breakout strategy actually depends on.

First-order only (compounding ignored) — picks the gate; the winner then gets
a proper chronological re-run.
"""
import os, json
from datetime import datetime, timezone
from statistics import mean
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

SIGNAL_DIR = "/home/ben/Signal"
IS_START = "2026-03-02"

cfg = {}
for line in open(os.path.join(SIGNAL_DIR, ".env")):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        cfg[k.strip()] = v.strip()
client = StockHistoricalDataClient(api_key=cfg["ALPACA_API_KEY"], secret_key=cfg["ALPACA_API_SECRET"])

bars = client.get_stock_bars(StockBarsRequest(
    symbol_or_symbols="SPY", timeframe=TimeFrame.Day,
    start=datetime(2025, 6, 1, tzinfo=timezone.utc),
    end=datetime(2026, 5, 22, tzinfo=timezone.utc), feed="iex"))
spy = sorted((b.timestamp.strftime("%Y-%m-%d"), b.close) for b in bars.data["SPY"])
print(f"SPY daily bars: {len(spy)}  {spy[0][0]}..{spy[-1][0]}")

entries = [x for x in json.load(open(os.path.join(SIGNAL_DIR, "scratch_extended.json")))
           if "Exercise 1" in x["title"]]


def uptrend(date, mode):
    """Uptrend decision for `date`, using only SPY closes strictly before it."""
    pc = [c for d, c in spy if d < date]
    if len(pc) < 50:
        return True                       # insufficient history — don't filter
    prev, sma20, sma50 = pc[-1], mean(pc[-20:]), mean(pc[-50:])
    if mode == "sma20":         return prev > sma20
    if mode == "sma50":         return prev > sma50
    if mode == "mom10":         return prev > pc[-11]
    if mode == "sma20_aligned": return prev > sma20 and sma20 > sma50
    return True


def stats(ents):
    trades = [t for e in ents for t in (e.get("trades") or [])]
    wins = [t for t in trades if t["pnl"] > 0]
    return (len(ents), len(trades),
            100 * len(wins) / len(trades) if trades else 0,
            sum(e["total_pnl"] for e in ents))


VARIANTS = [
    ("V0 no filter",            "none"),
    ("VA SPY > 20-day SMA",     "sma20"),
    ("VB SPY > 50-day SMA",     "sma50"),
    ("VC SPY 10-day mom > 0",   "mom10"),
    ("VD SPY>20SMA & 20>50",    "sma20_aligned"),
]

print("\nREGIME-FILTER SCREEN — first-order, from the 181-day extended run")
print(f"{'variant':24}{'days':>6}{'trades':>8}{'WR':>6}{'total':>11}"
      f"{'OOS WR':>9}{'OOS total':>12}")
print("-" * 76)
for name, mode in VARIANTS:
    kept = entries if mode == "none" else [e for e in entries if uptrend(e["date"], mode)]
    d, t, wr, tot = stats(kept)
    od, ot, owr, otot = stats([e for e in kept if e["date"] < IS_START])
    print(f"{name:24}{d:>6}{t:>8}{wr:>5.0f}%{tot:>+11.2f}{owr:>8.0f}%{otot:>+12.2f}")
print("-" * 76)
print("OOS = out-of-sample 2025-09..2026-02 (lost -$479 / 32% WR unfiltered)")
