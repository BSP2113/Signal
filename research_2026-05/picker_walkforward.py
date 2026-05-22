#!/usr/bin/env python3
"""Walk-forward picker backtest — decisive test of the dynamic-picker hypothesis.

The static 17-ticker list was hand-picked for Mar-May 2026 and is overfit
(out-of-sample: 32% WR, -$479). This tests whether a DYNAMIC picker fixes it:
at the start of each month, pick tickers using ONLY prior daily data
(picker-short's own scorer), then run the breakout sim on those names for that
month. Chained month-by-month -> a no-lookahead out-of-sample track record.

  Universe : current S&P 500 + NASDAQ 100 (mild membership-survivorship caveat).
  Picker   : picker-short's score_tickers — gap frequency + ATR-fit + RS-vs-SPY.
  Sim      : current ex1.py (post-revert, -2.0% stop).
  Compared : against the static-list extended run (scratch_extended.json),
             same 181-day window.
Scratch output only — exercises.json untouched.
"""
import os, sys, json, time, contextlib
from datetime import datetime, timedelta
from collections import defaultdict

SIGNAL_DIR = "/home/ben/Signal"
PICKER_DIR = "/home/ben/picker-short"
sys.path.insert(0, PICKER_DIR)
sys.path.insert(0, SIGNAL_DIR)

import ex1
import yfinance as yf
import pandas as pd
from screener.score import score_tickers
from screener.universe import _sp500, _nasdaq100
from config.settings import NO_FLY, LOOKBACK_DAYS, MIN_PRICE, MAX_PRICE, MIN_AVG_VOLUME

N_PICKS = 15
IS_START = "2026-03-02"
WIN_START, WIN_END = "2025-09-02", "2026-05-21"

all_dates = sorted(e["date"] for e in
                   json.load(open(os.path.join(SIGNAL_DIR, "market_states_historical.json"))))
all_dates = [d for d in all_dates if WIN_START <= d <= WIN_END]
months = sorted({d[:7] for d in all_dates})
print(f"{len(all_dates)} trading days across {len(months)} months", flush=True)

print("building universe (S&P 500 + NASDAQ 100)...", flush=True)
sp, _ = _sp500()
ndx = _nasdaq100()
universe = sorted(set(sp + ndx) - set(NO_FLY))
print(f"  {len(universe)} tickers", flush=True)


def fetch_as_of(tickers, as_of):
    """Daily bars ending strictly before `as_of` (no lookahead). ticker -> df."""
    start = (datetime.fromisoformat(as_of) - timedelta(days=LOOKBACK_DAYS + 30)).strftime("%Y-%m-%d")
    syms = sorted(set(tickers) | {"SPY"})
    frames = {}
    for i in range(0, len(syms), 120):
        batch = syms[i:i + 120]
        try:
            r = yf.download(batch, start=start, end=as_of, interval="1d",
                            group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception:
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
    return data


scratch = os.path.join(SIGNAL_DIR, "scratch_picker_wf.json")
if os.path.exists(scratch):
    os.remove(scratch)
ex1.TICKER_START = {}          # the picker's selection IS the start decision

picks_log = {}
for mo in months:
    mo_dates = [d for d in all_dates if d.startswith(mo)]
    as_of = mo_dates[0]
    print(f"\n=== {mo}  pick as-of {as_of} ===", flush=True)
    picks = []
    try:
        data = fetch_as_of(universe, as_of)
        ranked = score_tickers(data, None)
        if not ranked.empty:
            picks = list(ranked["ticker"].head(N_PICKS))
        print(f"  {len(data)} tickers scored | picks: {picks}", flush=True)
    except Exception as e:
        print(f"  PICKER ERROR: {e!r}", flush=True)
    picks_log[mo] = picks
    if not picks:
        print(f"  {mo}: no picks — month skipped", flush=True)
        continue
    ex1.TICKERS = picks
    for d in mo_dates:
        try:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                e = ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=scratch)
            print(f"  {d}  P&L ${e['total_pnl']:+8.2f}  wallet ${e['portfolio_eod']:,.2f}", flush=True)
        except Exception as err:
            print(f"  {d}  ERROR {err!r}", flush=True)
        time.sleep(1.0)

# --- analysis ------------------------------------------------------------
entries = [x for x in json.load(open(scratch)) if "Exercise 1" in x["title"]]
static = [x for x in json.load(open(os.path.join(SIGNAL_DIR, "scratch_extended.json")))
          if "Exercise 1" in x["title"]]


def rep(label, ents):
    if not ents:
        print(f"{label}\n   (no data)")
        return
    tr = [t for e in ents for t in (e.get("trades") or [])]
    w = [t for t in tr if t["pnl"] > 0]
    days = [e["total_pnl"] for e in ents]
    wr = 100 * len(w) / len(tr) if tr else 0
    exp = sum(t["pnl"] for t in tr) / len(tr) if tr else 0
    print(f"{label}")
    print(f"   {len(ents)}d  {len(tr)}tr  WR {wr:.0f}%  total ${sum(days):+,.2f}  "
          f"exp ${exp:+.2f}/tr  worst-day ${min(days):+.2f}")


print("\n" + "=" * 74)
print("WALK-FORWARD PICKER BACKTEST  vs  static hand-picked list")
print("\nDYNAMIC PICKER (monthly, no-lookahead):")
rep("  FULL          2025-09..2026-05", entries)
rep("  OUT-OF-SAMPLE 2025-09..2026-02", [e for e in entries if e["date"] < IS_START])
rep("  in-sample     2026-03..2026-05", [e for e in entries if e["date"] >= IS_START])
print("\nSTATIC LIST (same window, for comparison):")
rep("  FULL          2025-09..2026-05", static)
rep("  OUT-OF-SAMPLE 2025-09..2026-02", [e for e in static if e["date"] < IS_START])
print("\nmonthly picks:")
for mo in months:
    print(f"  {mo}: {picks_log.get(mo)}")
print("=" * 74)
