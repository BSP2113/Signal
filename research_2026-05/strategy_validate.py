#!/usr/bin/env python3
"""Validate Strategy A (picker monthly buy-and-hold) — is it real or a tailwind?

Splits A's +73.9% by:
  - in-sample (2026-03..05) vs out-of-sample (2025-09..2026-02)
  - per-month contribution (find runaway months)
  - contribution of top-3 winners — if they drive most of it, fragile
  - max drawdown along the way
  - vs a random-15 baseline (does the picker beat random picks?)
"""
import os, sys, re, json, random
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd

SIGNAL_DIR = "/home/ben/Signal"
WIN_START, WIN_END = "2025-09-02", "2026-05-21"
IS_START = "2026-03-02"
N_HOLD = 15
START_CASH = 5000.0
random.seed(20260522)

picks = {}
for line in open(os.path.join(SIGNAL_DIR, "research_2026-05/picker_wf.log")):
    m = re.match(r"\s+(\d{4}-\d{2}):\s+(\[.*\])\s*$", line)
    if m:
        picks[m.group(1)] = [t.strip(" '\"") for t in m.group(2).strip("[]").split(",")][:N_HOLD]
months = sorted(picks)

# universe for random baseline: same S&P 500 + NASDAQ 100 the picker used
sys.path.insert(0, "/home/ben/picker-short")
from screener.universe import _sp500, _nasdaq100
from config.settings import NO_FLY
sp, _ = _sp500(); ndx = _nasdaq100()
universe = sorted(set(sp + ndx) - set(NO_FLY))

all_tickers = sorted({t for lst in picks.values() for t in lst} | {"SPY"} | set(universe))
print(f"fetching {len(all_tickers)} symbols...", flush=True)
end_dt = (datetime.fromisoformat(WIN_END) + timedelta(days=2)).strftime("%Y-%m-%d")
start_dt = (datetime.fromisoformat(WIN_START) - timedelta(days=5)).strftime("%Y-%m-%d")
raw = yf.download(all_tickers, start=start_dt, end=end_dt, interval="1d",
                  group_by="ticker", auto_adjust=True, progress=False, threads=True)
bars = {}
for t in all_tickers:
    try:
        df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        df = df[["Close"]].dropna()
        if not df.empty:
            bars[t] = df
    except Exception:
        pass

spy = bars["SPY"]
trading_days = [d.strftime("%Y-%m-%d") for d in spy.index
                if WIN_START <= d.strftime("%Y-%m-%d") <= WIN_END]


def close_on(t, date):
    df = bars.get(t)
    if df is None or df.empty: return None
    sub = df[df.index >= date]
    return float(sub["Close"].iloc[0]) if not sub.empty else None


def close_at_or_before(t, date):
    df = bars.get(t)
    if df is None or df.empty: return None
    sub = df[df.index <= date]
    return float(sub["Close"].iloc[-1]) if not sub.empty else None


def run_monthly(tickers_per_month, exclude=()):
    """Equal-weight monthly buy-and-hold; returns (final_cash, [(mo, ret_pct)], per_ticker_total_$_contrib)."""
    cash = START_CASH
    monthly = []
    contrib = {}
    for mo in months:
        mds = [d for d in trading_days if d.startswith(mo)]
        if not mds: continue
        m_start, m_end = mds[0], mds[-1]
        these = [t for t in tickers_per_month.get(mo, []) if t not in exclude]
        rets = []
        for tk in these:
            a, b = close_on(tk, m_start), close_at_or_before(tk, m_end)
            if a and b and a > 0:
                r = (b - a) / a
                rets.append((tk, r))
        if not rets: continue
        port_ret = sum(r for _, r in rets) / len(rets)
        for tk, r in rets:
            # rough dollar contribution: this position was (cash / N) * r
            contrib[tk] = contrib.get(tk, 0.0) + (cash / len(rets)) * r
        cash *= (1 + port_ret)
        monthly.append((mo, port_ret * 100, cash))
    return cash, monthly, contrib


# --- Strategy A (the picker) -------------------------------------------
A_cash, A_monthly, A_contrib = run_monthly(picks)
print(f"\n=== A: Picker monthly buy-and-hold === final ${A_cash:,.0f}  ({A_cash-START_CASH:+,.0f}, {(A_cash/START_CASH-1)*100:+.1f}%)")
oos_cash = START_CASH
for mo, ret, c in A_monthly:
    if mo < IS_START[:7]:
        oos_cash *= (1 + ret / 100)
ins_cash = A_cash / oos_cash * START_CASH if oos_cash else 0
print(f"  OUT-OF-SAMPLE (Sept..Feb): final ${oos_cash:,.0f}  ({(oos_cash/START_CASH-1)*100:+.1f}%)")
print(f"  IN-SAMPLE (Mar..May):     final ${A_cash:,.0f}  (cumul; in-sample alone {(A_cash/oos_cash-1)*100:+.1f}% on top of OOS)")
print(f"\nPer-month:")
for mo, ret, c in A_monthly:
    print(f"  {mo}  {ret:+7.2f}%   -> ${c:>7,.0f}")

print(f"\nTop-5 dollar contributors (cumulative across months held):")
for tk, c in sorted(A_contrib.items(), key=lambda x: -x[1])[:8]:
    print(f"  {tk:6} ${c:>+8,.0f}")
print(f"Bottom-5 dollar contributors:")
for tk, c in sorted(A_contrib.items(), key=lambda x: x[1])[:5]:
    print(f"  {tk:6} ${c:>+8,.0f}")

# --- A excluding the top-3 winners (fragility check) -------------------
top3 = [tk for tk, _ in sorted(A_contrib.items(), key=lambda x: -x[1])[:3]]
A_no_top3, _, _ = run_monthly(picks, exclude=set(top3))
print(f"\n=== A excluding top-3 winners ({top3}) === final ${A_no_top3:,.0f}  ({A_no_top3-START_CASH:+,.0f}, {(A_no_top3/START_CASH-1)*100:+.1f}%)")

# --- Random-15 baseline (does the picker beat random?) -----------------
liquid_universe = [t for t in universe if t in bars]
print(f"\n=== Random-15 baseline (50 trials, same universe) ===")
random_results = []
for trial in range(50):
    rand_picks = {mo: random.sample(liquid_universe, 15) for mo in months}
    rc, _, _ = run_monthly(rand_picks)
    random_results.append(rc)
random_results.sort()
print(f"  Random-15 distribution over 50 trials:")
print(f"    worst:   ${random_results[0]:,.0f}  ({(random_results[0]/START_CASH-1)*100:+.1f}%)")
print(f"    median:  ${random_results[25]:,.0f}  ({(random_results[25]/START_CASH-1)*100:+.1f}%)")
print(f"    best:    ${random_results[-1]:,.0f}  ({(random_results[-1]/START_CASH-1)*100:+.1f}%)")
beats = sum(1 for r in random_results if A_cash > r)
print(f"  Picker A beats {beats}/50 random trials ({beats*2}th percentile)")

print("\n" + "=" * 70)
print("VERDICT — Strategy A (picker monthly buy-and-hold)")
print(f"  Full window:    ${A_cash:,.0f}  ({(A_cash/START_CASH-1)*100:+.1f}%)")
print(f"  Excl. top-3:    ${A_no_top3:,.0f}  ({(A_no_top3/START_CASH-1)*100:+.1f}%)")
print(f"  OOS only:       ${oos_cash:,.0f}  ({(oos_cash/START_CASH-1)*100:+.1f}%)")
print(f"  vs Random-15 median ${random_results[25]:,.0f}  ({(random_results[25]/START_CASH-1)*100:+.1f}%)")
print(f"  vs Day-trade bot ${5735.20:,.0f}  (+14.7%)")
print(f"  vs SPY hold      ${5849:,.0f}  (+17.0%)")
print("=" * 70)
