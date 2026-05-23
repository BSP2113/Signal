#!/usr/bin/env python3
"""monthly_pick.py — generate the live picker rebalance file.

Picks the top N tickers from S&P 500 + NASDAQ 100 using picker-short's
scorer (gap freq + ATR-fit + RS vs SPY) on daily data ending YESTERDAY,
writes them to picker_picks.json which live_ex1.py reads on startup.

Idempotent: skips if picker_picks.json's month already matches the current
calendar month. Run via cron daily at 5am weekdays; only fires once per
month. Atomic write so live_ex1.py never sees a partial file.

Designed to be safe to deploy: the live bot only adopts the picks if
USE_PICKER is True (see live_ex1.py) AND the file is current-month.
Otherwise live_ex1.py falls back to the static ex1.TICKERS unchanged.
"""
import os, sys, json, time, tempfile
from datetime import datetime, timedelta

SIGNAL_DIR = "/home/ben/Signal"
PICKER_DIR = "/home/ben/picker-short"
sys.path.insert(0, PICKER_DIR)

import yfinance as yf
import pandas as pd
from screener.score import score_tickers
from screener.universe import _sp500, _nasdaq100
from config.settings import (NO_FLY, LOOKBACK_DAYS, MIN_PRICE, MAX_PRICE,
                             MIN_AVG_VOLUME, WEIGHTS as SCORER_WEIGHTS)

PICKS_PATH = os.path.join(SIGNAL_DIR, "picker_picks.json")
N_PICKS = 15
TODAY = datetime.now()
CUR_MONTH = TODAY.strftime("%Y-%m")

# --- idempotency: skip if already done this month ------------------------
if os.path.exists(PICKS_PATH):
    try:
        existing = json.load(open(PICKS_PATH))
        if existing.get("month") == CUR_MONTH:
            print(f"[monthly_pick] picker_picks.json already current for {CUR_MONTH} "
                  f"({len(existing.get('tickers', []))} tickers) — no-op")
            sys.exit(0)
    except Exception:
        pass

print(f"[monthly_pick] generating picks for {CUR_MONTH}", flush=True)

# --- universe ------------------------------------------------------------
sp, _ = _sp500()
ndx = _nasdaq100()
universe = sorted(set(sp + ndx) - set(NO_FLY))
print(f"[monthly_pick] universe: {len(universe)} tickers (S&P 500 + NASDAQ 100 − NO_FLY)", flush=True)

# --- fetch daily bars through yesterday (end is exclusive) --------------
end = (TODAY + timedelta(days=1)).strftime("%Y-%m-%d")
start = (TODAY - timedelta(days=LOOKBACK_DAYS + 30)).strftime("%Y-%m-%d")
syms = sorted(set(universe) | {"SPY"})
print(f"[monthly_pick] fetching daily bars {start}..{end} for {len(syms)} symbols", flush=True)

frames = {}
for i in range(0, len(syms), 120):
    batch = syms[i:i + 120]
    try:
        r = yf.download(batch, start=start, end=end, interval="1d",
                        group_by="ticker", auto_adjust=True, progress=False, threads=True)
    except Exception as e:
        print(f"[monthly_pick] batch {i}: {e!r}", flush=True)
        continue
    for t in batch:
        try:
            df = r[t] if isinstance(r.columns, pd.MultiIndex) else r
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna().tail(LOOKBACK_DAYS)
            if len(df) >= 10:
                frames[t] = df
        except Exception:
            continue
    time.sleep(1.5)

data = {}
for t, df in frames.items():
    price = float(df["Close"].iloc[-1])
    vol = float(df["Volume"].mean())
    if t == "SPY" or (MIN_PRICE <= price <= MAX_PRICE and vol >= MIN_AVG_VOLUME):
        data[t] = df

print(f"[monthly_pick] {len(data)} tickers passed filters", flush=True)
if "SPY" not in data:
    print("[monthly_pick] FATAL: SPY missing — keeping previous picks_file unchanged", flush=True)
    sys.exit(1)

# --- score + write -------------------------------------------------------
ranked = score_tickers(data, None)
picks = list(ranked["ticker"].head(N_PICKS))
as_of_close = max(df.index[-1] for df in data.values()).strftime("%Y-%m-%d")
print(f"[monthly_pick] picks as-of {as_of_close}: {picks}", flush=True)

payload = {
    "month":          CUR_MONTH,
    "as_of":          as_of_close,
    "generated":      TODAY.strftime("%Y-%m-%d %H:%M:%S"),
    "n_picks":        len(picks),
    "scorer_weights": dict(SCORER_WEIGHTS),
    "universe_size":  len(universe),
    "tickers":        picks,
}

# atomic write: live_ex1.py concurrent reads never see a partial file
fd, tmp = tempfile.mkstemp(prefix="picker_picks.", suffix=".json.tmp", dir=SIGNAL_DIR)
try:
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, PICKS_PATH)
    print(f"[monthly_pick] wrote {PICKS_PATH}", flush=True)
except Exception:
    if os.path.exists(tmp):
        os.remove(tmp)
    raise
