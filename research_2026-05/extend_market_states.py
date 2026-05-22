#!/usr/bin/env python3
"""Extend market_states_historical.json back to 2025-09-02 (improvement lever #2).

The sim window is only 57 days (2026-03-02..05-21). To test whether the edge
holds across more market conditions, this backfills the market-state file for
every trading day from 2025-09-02 up to the current window, using the same
market_check.py formula (cross-checked exact in the 2026-05-22 backfill).

Trading days are taken from SPY daily bars. market_check writes market_state.json
as a side effect, so its BASE_DIR is repointed at a temp dir — the live file is
never touched.
"""
import os, sys, json, shutil, tempfile, time
from datetime import datetime, timezone
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
HIST = os.path.join(SIGNAL_DIR, "market_states_historical.json")
EXT_START, EXT_END = "2025-09-02", "2026-03-01"

cfg = {}
for line in open(os.path.join(SIGNAL_DIR, ".env")):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        cfg[k.strip()] = v.strip()
client = StockHistoricalDataClient(api_key=cfg["ALPACA_API_KEY"], secret_key=cfg["ALPACA_API_SECRET"])

# --- trading days from SPY daily bars ------------------------------------
bars = client.get_stock_bars(StockBarsRequest(
    symbol_or_symbols="SPY", timeframe=TimeFrame.Day,
    start=datetime.fromisoformat(EXT_START).replace(tzinfo=timezone.utc),
    end=datetime.fromisoformat(EXT_END).replace(tzinfo=timezone.utc), feed="iex"))
trading_days = sorted({b.timestamp.strftime("%Y-%m-%d") for b in bars.data.get("SPY", [])})
trading_days = [d for d in trading_days if EXT_START <= d <= EXT_END]
print(f"{len(trading_days)} trading days {trading_days[0]}..{trading_days[-1]}", flush=True)

hist = json.load(open(HIST))
have = {e["date"] for e in hist}
missing = [d for d in trading_days if d not in have]
print(f"{len(missing)} need a market-state backfill\n", flush=True)

# --- redirect market_check file I/O into a temp dir ----------------------
tmp = tempfile.mkdtemp(prefix="mc_extend_")
shutil.copy(os.path.join(SIGNAL_DIR, ".env"), os.path.join(tmp, ".env"))
import market_check
market_check.BASE_DIR = tmp

new = []
for i, d in enumerate(missing, 1):
    try:
        r = market_check.run(d)
        new.append({"date": d, "spy_gap_pct": r["spy_gap_pct"],
                    "vixy_trend_pct": r["vixy_trend_pct"]})
        if i % 20 == 0 or i == len(missing):
            print(f"  [{i}/{len(missing)}] {d}  gap={r['spy_gap_pct']:+.2f}%", flush=True)
    except Exception as e:
        print(f"  {d}  ERROR {e!r}", flush=True)
    time.sleep(0.4)
shutil.rmtree(tmp, ignore_errors=True)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy(HIST, os.path.join(SIGNAL_DIR, "backups", f"market_states_historical.json.pre-extend-{stamp}"))
merged = sorted(hist + new, key=lambda e: e["date"])
with open(HIST, "w") as f:
    json.dump(merged, f, indent=2)
print(f"\nmarket_states_historical.json: {len(hist)} -> {len(merged)} entries "
      f"({merged[0]['date']}..{merged[-1]['date']})")
