#!/usr/bin/env python3
"""H1 (catalyst test) — watchlist = the day's biggest opening gappers.

A gap (Open[D] vs Close[D-1]) is the market's own "something happened" flag —
earnings, news. It is known at 09:30, before the GAP_GO entry window
(09:30-09:39), so selecting on it is NOT lookahead. Tests whether trading the
day's event-driven gappers beats the curated-17 baseline. Chronological
2026-03-02 -> 05-21. Scratch output only.

Usage: h1_catalyst.py [N]
  (no arg)  full run
  0         build watchlists + diagnostics, no simulation
  N         simulate first N dates (smoke)
"""
import os, sys, glob, json, time, pickle, contextlib, re, urllib.request
from datetime import datetime, timezone

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import pandas as pd
import ex1
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

SCRATCH      = "scratch_h1_catalyst_5821.json"
scratch_path = os.path.join(SIGNAL_DIR, SCRATCH)
DAILY_CACHE  = "/tmp/rotation_daily_5821.pkl"
WIN_START, WIN_END = "2026-03-02", "2026-05-21"
LIVE_START   = "2026-04-13"
GAP_MIN      = 0.03
GAP_MAX      = 0.15      # cap — bigger gaps are binary-event lottery, not tradeable catalysts
DV_MIN       = 25e6      # min avg daily DOLLAR volume — real liquidity, not microcap pumps
MIN_PRICE    = 3.0
TOP_N        = 17
BASELINE     = 1134.81
mode = sys.argv[1] if len(sys.argv) > 1 else None

def yf_to_alpaca(t):
    return t.replace("-", ".") if "-" in t else t

dates = sorted(os.path.basename(f)[:-5]
               for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json")))
dates = [d for d in dates if WIN_START <= d <= WIN_END]
dateset = set(dates)
print(f"{len(dates)} trading dates: {dates[0]} -> {dates[-1]}")

with open(DAILY_CACHE, "rb") as f:
    daily = pickle.load(f)
daily["Date"] = pd.to_datetime(daily["Date"], utc=True).dt.tz_localize(None)
daily = daily.sort_values(["ticker", "Date"])

# Exclude ETFs/ETNs — leveraged & commodity funds are liquid and gappy, so they
# slip through any liquidity screen. Authoritative ETF flags from Nasdaq Trader.
def load_etf_set():
    etfs = set()
    for url in ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"):
        try:
            txt = urllib.request.urlopen(url, timeout=25).read().decode()
        except Exception as e:
            print(f"  WARNING: ETF list fetch failed ({e}) — ETFs NOT excluded")
            continue
        lines  = txt.splitlines()
        header = lines[0].split("|")
        if "ETF" not in header:
            continue
        ei = header.index("ETF")
        for ln in lines[1:]:
            p = ln.split("|")
            if len(p) > ei and p[ei].strip() == "Y":
                etfs.add(p[0].strip())
    return etfs
etf_set = load_etf_set()
print(f"ETF/ETN exclusion list: {len(etf_set)} symbols")

# per-day gapper candidates: (ticker, gap, followed_through)
gap_by_date = {d: [] for d in dates}
for tk, g in daily.groupby("ticker", sort=False):
    if tk in etf_set:
        continue
    g = g.reset_index(drop=True)
    if len(g) < 25:
        continue
    prev_close = g.Close.shift(1)
    avgvol20   = g.Volume.rolling(20).mean().shift(1)            # prior 20d, no lookahead
    cand = pd.DataFrame({
        "d"         : g.Date.dt.strftime("%Y-%m-%d"),
        "gap"       : g.Open / prev_close - 1,
        "dollar_vol": avgvol20 * prev_close,
        "prev_close": prev_close,
        "follow"    : g.Close > g.Open,                          # diagnostic only
    })
    q = cand[(cand.gap >= GAP_MIN) & (cand.gap <= GAP_MAX)
             & (cand.dollar_vol >= DV_MIN) & (cand.prev_close >= MIN_PRICE)
             & cand.d.isin(dateset)]
    for r in q.itertuples():
        gap_by_date[r.d].append((tk, float(r.gap), bool(r.follow)))

picks_by_date, follow_by_date = {}, {}
for d in dates:
    ranked = sorted(gap_by_date[d], key=lambda x: -x[1])[:TOP_N]
    picks_by_date[d]  = [yf_to_alpaca(t) for t, _, _ in ranked]
    follow_by_date[d] = [f for _, _, f in ranked]

# validate picks against Alpaca
all_picks = sorted(set(t for ps in picks_by_date.values() for t in ps))
key, secret = ex1._load_creds()
client = StockHistoricalDataClient(api_key=key, secret_key=secret)
ps_, pe_ = datetime(2026,5,1,tzinfo=timezone.utc), datetime(2026,5,20,tzinfo=timezone.utc)
def probe(syms):
    """Return the syms Alpaca accepts. Retries once on a transient error, then
    splits a still-failing batch in half to isolate the genuinely-bad symbol(s)
    instead of discarding the whole batch."""
    syms = list(syms)
    if not syms:
        return set()
    for attempt in range(2):
        try:
            client.get_stock_bars(StockBarsRequest(symbol_or_symbols=syms,
                    timeframe=TimeFrame.Day, start=ps_, end=pe_, feed="iex"))
            return set(syms)                       # batch accepted -> all valid
        except Exception:
            if attempt == 0:
                time.sleep(2)
    if len(syms) == 1:
        return set()                               # this single symbol is bad
    mid = len(syms) // 2
    return probe(syms[:mid]) | probe(syms[mid:])
valid = set()
for i in range(0, len(all_picks), 200):
    valid |= probe(all_picks[i:i+200])
invalid = [t for t in all_picks if t not in valid]
print(f"Validated: {len(valid)}/{len(all_picks)} tradable on Alpaca"
      + (f"  | dropped: {', '.join(invalid)}" if invalid else ""))

counts    = [len(gap_by_date[d]) for d in dates]
allfollow = [f for d in dates for f in follow_by_date[d]]
print(f"\nGappers/day ({GAP_MIN*100:.0f}-{GAP_MAX*100:.0f}% gap, >=${DV_MIN/1e6:.0f}M/day): "
      f"min {min(counts)}, median {sorted(counts)[len(counts)//2]}, max {max(counts)}")
print(f"Follow-through (picked gappers that closed above their open): "
      f"{sum(allfollow)/len(allfollow)*100:.0f}%  ({len(allfollow)} gapper-days)")

if mode == "0":
    print("\nSample watchlists (top gappers, gap %):")
    for d in (dates[0], dates[len(dates)//2], dates[-1]):
        r = sorted(gap_by_date[d], key=lambda x: -x[1])[:TOP_N]
        print(f"  {d}: " + ", ".join(f"{t}({g*100:.0f}%)" for t, g, _ in r[:12]))
    sys.exit(0)

sim_dates = dates[:int(mode)] if mode is not None else dates
verbose   = mode is not None
if os.path.exists(scratch_path):
    os.remove(scratch_path)
print(f"\nSimulating {len(sim_dates)} dates -> {SCRATCH}\n")
orig_TS, failed = ex1.TICKER_START, []
for i, d in enumerate(sim_dates, 1):
    picks = [t for t in picks_by_date[d] if t in valid]
    if not picks:
        print(f"[{i:2}/{len(sim_dates)}] {d}  no gappers"); continue
    try:
        ex1.TICKERS, ex1.TICKER_START = picks, {}
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
    print("No scratch file written."); sys.exit(1)
data = [e for e in json.load(open(scratch_path)) if "Exercise 1" in e["title"]]
def slice_stats(entries, label):
    pnl    = sum(e["total_pnl"] for e in entries)
    trades = [t for e in entries for t in e["trades"]]
    wins   = sum(1 for t in trades if t.get("pnl", 0) > 0)
    wr     = (wins / len(trades) * 100) if trades else 0.0
    print(f"  {label:10} days={len(entries):2}  trades={len(trades):3}  "
          f"WR={wr:5.1f}%  P&L=${pnl:+,.2f}")
    return pnl
print("H1 — CATALYST / GAPPER WATCHLIST")
total = slice_stats(data, "ALL")
slice_stats([e for e in data if e["date"] <  LIVE_START], "backfill")
slice_stats([e for e in data if e["date"] >= LIVE_START], "live")
print(f"\n  Final wallet: ${5000 + total:,.2f}")
if mode is None:
    print(f"  Pass 1 baseline: ${BASELINE:+,.2f}   ->   H1 delta: ${total - BASELINE:+,.2f}")
if failed:
    print(f"  {len(failed)} FAILED: " + ", ".join(d for d, _ in failed))
print("=" * 64)
