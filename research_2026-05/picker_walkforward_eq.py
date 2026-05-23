#!/usr/bin/env python3
"""Scorer integrity check — walk-forward picker with EQUAL weights.

picker-short's scorer uses weights gap:0.30, orb:0.35, momentum:0.35.
If those specific weights were tuned on recent data, the +$542 OOS picker
result has residual overfit hiding inside the scorer. This re-runs the
identical walk-forward but with equal 1/3 weights — if equal-weight picks
perform comparably, the scorer isn't fragile. Big gap either way is a flag.

Reuses picker_walkforward.py exactly except for the WEIGHTS monkey-patch.
Scratch output only.
"""
import os, sys, json, time, contextlib
from datetime import datetime, timedelta

SIGNAL_DIR = "/home/ben/Signal"
PICKER_DIR = "/home/ben/picker-short"
sys.path.insert(0, PICKER_DIR)
sys.path.insert(0, SIGNAL_DIR)

import ex1
import yfinance as yf
import pandas as pd
import screener.score as scorer
from screener.universe import _sp500, _nasdaq100
from config.settings import NO_FLY, LOOKBACK_DAYS, MIN_PRICE, MAX_PRICE, MIN_AVG_VOLUME

# --- the integrity test: replace picker-short's weights with equal 1/3 ---
scorer.WEIGHTS = {"gap": 0.333, "orb": 0.334, "momentum": 0.333}
print(f"WEIGHTS override -> {scorer.WEIGHTS}", flush=True)

N_PICKS = 15
IS_START = "2026-03-02"
WIN_START, WIN_END = "2025-09-02", "2026-05-21"

all_dates = sorted(e["date"] for e in
                   json.load(open(os.path.join(SIGNAL_DIR, "market_states_historical.json"))))
all_dates = [d for d in all_dates if WIN_START <= d <= WIN_END]
months = sorted({d[:7] for d in all_dates})
print(f"{len(all_dates)} trading days, {len(months)} months", flush=True)

sp, _ = _sp500()
ndx = _nasdaq100()
universe = sorted(set(sp + ndx) - set(NO_FLY))
print(f"universe: {len(universe)} tickers", flush=True)


def fetch_as_of(tickers, as_of):
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


scratch = os.path.join(SIGNAL_DIR, "scratch_picker_wf_eq.json")
if os.path.exists(scratch):
    os.remove(scratch)
ex1.TICKER_START = {}

picks_log = {}
for mo in months:
    mo_dates = [d for d in all_dates if d.startswith(mo)]
    as_of = mo_dates[0]
    print(f"\n=== {mo}  pick as-of {as_of} (equal weights) ===", flush=True)
    picks = []
    try:
        data = fetch_as_of(universe, as_of)
        ranked = scorer.score_tickers(data, None)
        if not ranked.empty:
            picks = list(ranked["ticker"].head(N_PICKS))
        print(f"  picks: {picks}", flush=True)
    except Exception as e:
        print(f"  PICKER ERROR: {e!r}", flush=True)
    picks_log[mo] = picks
    if not picks:
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

entries = [x for x in json.load(open(scratch)) if "Exercise 1" in x["title"]]


def rep(label, ents):
    if not ents:
        print(f"{label}: (no data)")
        return
    tr = [t for e in ents for t in (e.get("trades") or [])]
    w = [t for t in tr if t["pnl"] > 0]
    days = [e["total_pnl"] for e in ents]
    wr = 100 * len(w) / len(tr) if tr else 0
    exp = sum(t["pnl"] for t in tr) / len(tr) if tr else 0
    print(f"{label}")
    print(f"   {len(ents)}d {len(tr)}tr  WR {wr:.0f}%  total ${sum(days):+,.2f}  "
          f"exp ${exp:+.2f}/tr")


print("\n" + "=" * 72)
print("SCORER INTEGRITY — picker walk-forward with EQUAL weights")
print(" (compare to picker_walkforward.py: full +$735, OOS +$542 / 37%)")
rep("EQ-weights  FULL          2025-09..2026-05", entries)
rep("EQ-weights  OUT-OF-SAMPLE 2025-09..2026-02", [e for e in entries if e["date"] < IS_START])
rep("EQ-weights  in-sample     2026-03..2026-05", [e for e in entries if e["date"] >= IS_START])
print("=" * 72)
