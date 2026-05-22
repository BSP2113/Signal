#!/usr/bin/env python3
"""Pass 2 — Full daily rotation on the lookahead-fixed sim.

Each morning, picker-short scores the whole universe (incumbents eligible,
only the crypto/HOOD no-fly list excluded) using ONLY daily bars through the
PRIOR day's close, and the top 17 by score become that day's ticker list.
The lookahead-fixed ex1.run_ex1 then trades that list. Chronological,
2026-03-02 -> 2026-05-21. Scratch output only — never exercises.json.

Usage: rotation_pass2.py [N]
  (no arg)  full run
  0         setup + ranking + validation only (diagnostics, no simulation)
  N         simulate only the first N dates (smoke test)
"""
import os, sys, glob, json, time, pickle, contextlib
from datetime import datetime, timedelta, timezone

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
sys.path.insert(0, "/home/ben/picker-short")

# picker-short normally excludes the current 17 from its universe. For a
# rotation system we want them eligible — keep ONLY the no-fly exclusion.
from config import settings as ps_settings
ps_settings.EXCLUDED = set(ps_settings.NO_FLY)
from config.settings import MIN_PRICE, MAX_PRICE, MIN_AVG_VOLUME, LOOKBACK_DAYS
from screener.universe import get_raw_universe
from screener import score as picker_score

import pandas as pd
import yfinance as yf
import ex1
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

SCRATCH      = "scratch_rotation_5821.json"
scratch_path = os.path.join(SIGNAL_DIR, SCRATCH)
DAILY_CACHE  = "/tmp/rotation_daily_5821.pkl"
WIN_START, WIN_END = "2026-03-02", "2026-05-21"
LIVE_START   = "2026-04-13"
TOP_N        = 17
BASELINE     = 1134.81          # Pass 1 total, for reference

ORIGINAL_17 = list(ex1.TICKERS)
mode = sys.argv[1] if len(sys.argv) > 1 else None

def yf_to_alpaca(t):
    return t.replace("-", ".") if "-" in t else t

# --- trading dates: identical set to the baseline (data_cache filenames) ---
dates = sorted(os.path.basename(f)[:-5]
               for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json")))
dates = [d for d in dates if WIN_START <= d <= WIN_END]
print(f"{len(dates)} trading dates: {dates[0]} -> {dates[-1]}")

# --- universe ---
universe, _ = get_raw_universe()
universe = sorted(set(universe) | {"SPY"})
print(f"Universe: {len(universe)} tickers (incumbents eligible, no-fly excluded)")

# --- daily-bar history (cached) ---
if os.path.exists(DAILY_CACHE):
    with open(DAILY_CACHE, "rb") as f:
        daily_all = pickle.load(f)
    print(f"Loaded cached daily bars: {len(daily_all):,} rows, {daily_all['ticker'].nunique()} tickers")
else:
    earliest, latest = "2025-12-15", "2026-05-22"
    print(f"Downloading yfinance daily bars {earliest} -> {latest} ...")
    BATCH, frames, failed = 100, [], []
    def grab(batch):
        raw = yf.download(batch, start=earliest, end=latest, interval="1d",
                          group_by="ticker", auto_adjust=True, progress=False, threads=True)
        got = 0
        for t in batch:
            try:
                df = raw[t].dropna() if isinstance(raw.columns, pd.MultiIndex) else raw.dropna()
                if not df.empty:
                    df = df.copy(); df["ticker"] = t
                    frames.append(df.reset_index()); got += 1
            except KeyError:
                continue
        return got
    nb = (len(universe) + BATCH - 1) // BATCH
    for i in range(0, len(universe), BATCH):
        batch = universe[i:i+BATCH]
        try:
            got = grab(batch)
            print(f"  batch {i//BATCH+1}/{nb}: {got}/{len(batch)} ok", flush=True)
        except Exception as e:
            print(f"  batch {i//BATCH+1}/{nb} FAILED ({e}) — will retry", flush=True)
            failed += batch
        time.sleep(1)
    if failed:
        print(f"  retrying {len(failed)} tickers after 10s ...")
        time.sleep(10)
        try:
            grab(failed)
        except Exception as e:
            print(f"  retry failed: {e}")
    daily_all = pd.concat(frames, ignore_index=True)
    with open(DAILY_CACHE, "wb") as f:
        pickle.dump(daily_all, f)
    print(f"Cached {len(daily_all):,} rows, {daily_all['ticker'].nunique()} tickers -> {DAILY_CACHE}")

daily_all["Date"] = pd.to_datetime(daily_all["Date"]).dt.tz_localize(None)

# --- as-of ranking — NO LOOKAHEAD: strictly daily bars BEFORE the trade date ---
def rank_for_date(date_str):
    cutoff = pd.to_datetime(date_str)
    sliced = daily_all[daily_all["Date"] < cutoff]          # strict < : prior close only
    data, last_date = {}, None
    for t, df in sliced.groupby("ticker"):
        df = df.sort_values("Date").tail(LOOKBACK_DAYS)
        if len(df) < 10:
            continue
        df = df.set_index("Date")
        last_date = max(last_date, df.index[-1]) if last_date else df.index[-1]
        price, avg_vol = float(df["Close"].iloc[-1]), float(df["Volume"].mean())
        if t == "SPY" or (MIN_PRICE <= price <= MAX_PRICE and avg_vol >= MIN_AVG_VOLUME):
            data[t] = df
    if "SPY" not in data:
        return [], None, last_date
    ranked = picker_score.score_tickers(data)
    if ranked.empty:
        return [], None, last_date
    return ranked.head(TOP_N)["ticker"].tolist(), ranked, last_date

print("\nComputing as-of rankings (prior-close data only)...")
picks_by_date, lastdate_by_date = {}, {}
for d in dates:
    picks, _, last_date = rank_for_date(d)
    picks_by_date[d]    = [yf_to_alpaca(t) for t in picks]
    lastdate_by_date[d] = last_date
print(f"  done — {sum(len(v) for v in picks_by_date.values())} total ticker-days")

# --- validate picks against Alpaca (so a bad symbol can't crash a sim date) ---
all_picks = sorted(set(t for ps in picks_by_date.values() for t in ps))
key, secret = ex1._load_creds()
client = StockHistoricalDataClient(api_key=key, secret_key=secret)
valid = set()
ps, pe = datetime(2026,5,1,tzinfo=timezone.utc), datetime(2026,5,20,tzinfo=timezone.utc)
def probe(syms):
    while syms:
        try:
            r = client.get_stock_bars(StockBarsRequest(symbol_or_symbols=syms,
                    timeframe=TimeFrame.Day, start=ps, end=pe, feed="iex"))
            return set(r.data.keys())
        except Exception as e:
            import re
            m = re.search(r"invalid symbol:\s*([A-Z0-9.\-]+)", str(e))
            if m and m.group(1) in syms:
                syms = [s for s in syms if s != m.group(1)]; continue
            return set()
    return set()
for i in range(0, len(all_picks), 200):
    valid |= probe(all_picks[i:i+200])
invalid = [t for t in all_picks if t not in valid]
print(f"Validated picks: {len(valid)}/{len(all_picks)} tradable on Alpaca"
      + (f"  | dropped: {', '.join(invalid)}" if invalid else ""))

# ---------------------------------------------------------------- diagnostics
if mode == "0":
    print("\n" + "=" * 64 + "\nDIAGNOSTICS (no simulation)\n" + "=" * 64)
    for d in (dates[0], dates[len(dates)//2], dates[-1]):
        picks, ranked, last_date = rank_for_date(d)
        print(f"\n{d}  — ranking uses bars through {last_date.date()} "
              f"({'OK, no lookahead' if last_date < pd.to_datetime(d) else '** LOOKAHEAD! **'})")
        top = ranked.head(TOP_N)
        print("  top 17: " + ", ".join(f"{r.ticker}({r.score:.0f})" for r in top.itertuples()))
    print("\nOverlap — how often each current-17 ticker lands in the rotated top 17:")
    for t in sorted(ORIGINAL_17, key=lambda t: -sum(t in p for p in picks_by_date.values())):
        n = sum(t in p for p in picks_by_date.values())
        print(f"  {t:6s} {n:2}/{len(dates)} days")
    sys.exit(0)

# ---------------------------------------------------------------- simulation
sim_dates = dates[:int(mode)] if mode is not None else dates
verbose   = mode is not None
if os.path.exists(scratch_path):
    os.remove(scratch_path)
print(f"\nSimulating {len(sim_dates)} dates on the fixed sim -> {SCRATCH}\n")

orig_TS, failed = ex1.TICKER_START, []
for i, d in enumerate(sim_dates, 1):
    picks = [t for t in picks_by_date[d] if t in valid]
    try:
        ex1.TICKERS, ex1.TICKER_START = picks, {}      # rotated list, all active
        if verbose:
            ex = ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=SCRATCH)
        else:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                ex = ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=SCRATCH)
        print(f"[{i:2}/{len(sim_dates)}] {d}  {ex['market_state']:>7}  "
              f"u={len(picks):2}  trades={ex['total_trades']:2}  "
              f"P&L=${ex['total_pnl']:+8.2f}  wallet=${ex['portfolio_eod']:,.2f}")
    except Exception as e:
        failed.append((d, repr(e)))
        print(f"[{i:2}/{len(sim_dates)}] {d}  ERROR: {e!r}")
    if i < len(sim_dates):
        time.sleep(2)
ex1.TICKER_START = orig_TS

print("\n" + "=" * 64)
if not os.path.exists(scratch_path):
    print("No scratch file written.")
    sys.exit(1)
data = [e for e in json.load(open(scratch_path)) if "Exercise 1" in e["title"]]
def slice_stats(entries, label):
    pnl    = sum(e["total_pnl"] for e in entries)
    trades = [t for e in entries for t in e["trades"]]
    wins   = sum(1 for t in trades if t.get("pnl", 0) > 0)
    wr     = (wins / len(trades) * 100) if trades else 0.0
    print(f"  {label:10} days={len(entries):2}  trades={len(trades):3}  "
          f"WR={wr:5.1f}%  P&L=${pnl:+,.2f}")
    return pnl
print("PASS 2 — FULL ROTATION (current scorer)")
total = slice_stats(data, "ALL")
slice_stats([e for e in data if e["date"] <  LIVE_START], "backfill")
slice_stats([e for e in data if e["date"] >= LIVE_START], "live")
print(f"\n  Final wallet: ${5000 + total:,.2f}")
if mode is None:
    print(f"  Pass 1 baseline:  ${BASELINE:+,.2f}   ->   rotation delta: ${total - BASELINE:+,.2f}")
if failed:
    print(f"  {len(failed)} date(s) FAILED: " + ", ".join(d for d, _ in failed))
print("=" * 64)
