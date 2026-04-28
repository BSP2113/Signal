"""
market_check.py — pre-market assessment, runs at 9:20 AM via cron

Fetches SPY pre-market gap vs previous close and VIXY trend (VIX proxy),
then writes market_state.json with the day's allocation tier.

Run manually:  venv/bin/python3 market_check.py [YYYY-MM-DD]
Cron calls it: venv/bin/python3 market_check.py  (defaults to today)
"""

import json
import os
import sys
import pandas as pd
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ET       = "America/New_York"

SPY_BULL       =  0.005   # SPY gap > +0.5% = bullish
SPY_BEAR       = -0.005   # SPY gap < -0.5% = bearish
VIXY_SURGE     =  0.03    # VIXY pre-market up >3% = fear rising, adds bearish weight


def _load_creds():
    path  = os.path.join(BASE_DIR, ".env")
    creds = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    return creds["ALPACA_API_KEY"], creds["ALPACA_API_SECRET"]


def run(trade_date=None):
    if trade_date is None:
        trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Market Check — {trade_date}")

    key, secret = _load_creds()
    client      = StockHistoricalDataClient(api_key=key, secret_key=secret)

    trade_dt = datetime.strptime(trade_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    next_dt  = trade_dt + timedelta(days=1)

    # --- Previous close: last daily bar before trade_date ---
    lookback = trade_dt - timedelta(days=5)
    daily_bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=["SPY", "VIXY"],
        timeframe=TimeFrame.Day,
        start=lookback,
        end=trade_dt,
        feed="iex",
    ))

    spy_prev_close  = None
    vixy_trend      = 0.0
    vixy_level      = 0.0
    for sym, bars in daily_bars.data.items():
        if not bars:
            continue
        if sym == "SPY":
            spy_prev_close = bars[-1].close
        if sym == "VIXY" and len(bars) >= 2:
            vixy_level = bars[-1].close
            vixy_trend = (bars[-1].close - bars[-2].close) / bars[-2].close if bars[-2].close else 0.0

    # --- Pre-market bars: 4 AM – 9:29 AM on trade_date ---
    premarket_start = trade_dt.replace(hour=9, minute=0)   # 9 AM UTC covers 4 AM ET + buffer
    premarket_end   = trade_dt.replace(hour=13, minute=29)  # 9:29 AM ET = 13:29 UTC

    pm_bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=["SPY", "VIXY"],
        timeframe=TimeFrame.Minute,
        start=premarket_start,
        end=premarket_end,
        feed="iex",
    ))

    spy_premarket = None
    spy_gap       = 0.0

    if "SPY" in pm_bars.data and pm_bars.data["SPY"]:
        spy_premarket = pm_bars.data["SPY"][-1].close
        if spy_prev_close:
            spy_gap = (spy_premarket - spy_prev_close) / spy_prev_close

    # --- Determine state ---
    if spy_gap <= SPY_BEAR or vixy_trend >= VIXY_SURGE:
        state = "bearish"
    elif spy_gap >= SPY_BULL and vixy_trend < VIXY_SURGE:
        state = "bullish"
    else:
        state = "neutral"

    result = {
        "date":           trade_date,
        "state":          state,
        "spy_prev_close": round(spy_prev_close, 2) if spy_prev_close else None,
        "spy_premarket":  round(spy_premarket,  2) if spy_premarket  else None,
        "vixy_level":     round(vixy_level, 2),
        "spy_gap_pct":    round(spy_gap    * 100, 3),
        "vixy_trend_pct": round(vixy_trend * 100, 3),
        "generated":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    path = os.path.join(BASE_DIR, "market_state.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)

    spy_str   = f"${spy_prev_close:.2f} → ${spy_premarket:.2f} ({spy_gap*100:+.2f}%)" \
                if spy_prev_close and spy_premarket else "no data"
    vixy_str  = f"{vixy_trend*100:+.2f}%" if vixy_trend else "no data"

    print(f"  SPY:   {spy_str}")
    print(f"  VIXY:  {vixy_str}")
    print(f"  State: {state.upper()}")
    print(f"  Saved to market_state.json")

    return result


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(date_arg)
