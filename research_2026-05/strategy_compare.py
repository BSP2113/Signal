#!/usr/bin/env python3
"""Strategy comparison — does the day-trade picker actually beat simpler things?

The day-trade picker walk-forward returned +$735 on $5K over 181 days
(2025-09-02..2026-05-21) = +14.7%. This tests whether dead-simple
alternatives on the same window beat it:

  A: Picker monthly buy-and-hold  - equal-weight top-15 each month, hold
                                    to month-end, rebalance.
  B: A + SPY 200d trend filter    - sit in cash when SPY < 200d SMA.
  C: SPY buy-and-hold             - hold SPY the whole 181 days.
  D: QQQ buy-and-hold             - hold QQQ the whole 181 days.
  E: Picker Sept picks, held all  - never rebalance, just hold initial picks.

Single yfinance fetch + arithmetic. Honest benchmark of "is our complexity
earning its keep."
"""
import os, sys, re, json
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd

SIGNAL_DIR = "/home/ben/Signal"
WIN_START, WIN_END = "2025-09-02", "2026-05-21"
N_HOLD = 15
START_CASH = 5000.0

# --- monthly picks (from walk-forward log) ------------------------------
picks = {}
for line in open(os.path.join(SIGNAL_DIR, "research_2026-05/picker_wf.log")):
    m = re.match(r"\s+(\d{4}-\d{2}):\s+(\[.*\])\s*$", line)
    if m:
        picks[m.group(1)] = [t.strip(" '\"") for t in m.group(2).strip("[]").split(",")][:N_HOLD]
months = sorted(picks)
all_tickers = sorted({t for lst in picks.values() for t in lst} | {"SPY", "QQQ"})
print(f"{len(months)} months, {len(all_tickers)} unique symbols", flush=True)

print("fetching daily bars...", flush=True)
end_dt   = (datetime.fromisoformat(WIN_END)   + timedelta(days=2)).strftime("%Y-%m-%d")
start_dt = (datetime.fromisoformat(WIN_START) - timedelta(days=300)).strftime("%Y-%m-%d")
raw = yf.download(all_tickers, start=start_dt, end=end_dt, interval="1d",
                  group_by="ticker", auto_adjust=True, progress=False, threads=True)
bars = {}
for t in all_tickers:
    try:
        df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        bars[t] = df[["Close"]].dropna()
    except Exception:
        pass

spy = bars["SPY"]
trading_days = [d.strftime("%Y-%m-%d") for d in spy.index
                if WIN_START <= d.strftime("%Y-%m-%d") <= WIN_END]


def close_on(t, date):
    df = bars.get(t)
    if df is None or df.empty: return None
    sub = df[df.index >= date]
    if sub.empty: return None
    return (sub.index[0].strftime("%Y-%m-%d"), float(sub["Close"].iloc[0]))


def close_at_or_before(t, date):
    df = bars.get(t)
    if df is None or df.empty: return None
    sub = df[df.index <= date]
    if sub.empty: return None
    return (sub.index[-1].strftime("%Y-%m-%d"), float(sub["Close"].iloc[-1]))


def picker_monthly(use_spy_filter=False):
    cash = START_CASH
    months_in_cash = 0
    months_in_market = 0
    for mo in months:
        mds = [d for d in trading_days if d.startswith(mo)]
        if not mds: continue
        m_start, m_end = mds[0], mds[-1]
        if use_spy_filter:
            priors = spy[spy.index < m_start]["Close"]
            if len(priors) >= 200:
                sma200 = priors.iloc[-200:].mean()
                spy_at = close_at_or_before("SPY", m_start)
                if spy_at and spy_at[1] < sma200:
                    months_in_cash += 1
                    continue
        rets = []
        for tk in picks[mo]:
            a = close_on(tk, m_start)
            b = close_at_or_before(tk, m_end)
            if a and b and a[1] > 0:
                rets.append((b[1] - a[1]) / a[1])
        if not rets: continue
        cash *= (1 + sum(rets) / len(rets))
        months_in_market += 1
    return cash, months_in_market, months_in_cash


def hold_one(t):
    a = close_on(t, trading_days[0])
    b = close_at_or_before(t, trading_days[-1])
    if not (a and b): return None
    return START_CASH * (1 + (b[1] - a[1]) / a[1])


def picker_sept_hold():
    sept = picks.get(months[0], [])
    rets = []
    for tk in sept:
        a = close_on(tk, trading_days[0])
        b = close_at_or_before(tk, trading_days[-1])
        if a and b and a[1] > 0:
            rets.append((b[1] - a[1]) / a[1])
    return START_CASH * (1 + sum(rets) / len(rets)) if rets else 0


A_cash, A_in, A_cash_mos = picker_monthly(False)
B_cash, B_in, B_cash_mos = picker_monthly(True)
C_cash = hold_one("SPY")
D_cash = hold_one("QQQ")
E_cash = picker_sept_hold()

DAY = 5000 + 735.20   # known from the day-trade walk-forward

print("\n" + "=" * 78)
print("STRATEGY COMPARISON — 181 days, 2025-09-02..2026-05-21, start $5,000")
print("=" * 78)


def line(label, final, extra=""):
    delta = final - START_CASH
    pct = (final / START_CASH - 1) * 100
    print(f"  {label:48} ${final:>8,.0f}   {delta:>+8.0f}   {pct:>+6.2f}%   {extra}")


line("Day-trade picker (the bot we built)", DAY)
line("A: Picker MONTHLY buy-and-hold", A_cash, f"{A_in} months in market")
line("B: A + SPY 200d trend filter", B_cash, f"{B_in} in market, {B_cash_mos} in cash")
line("C: SPY buy-and-hold (benchmark)", C_cash)
line("D: QQQ buy-and-hold (benchmark)", D_cash)
line("E: Picker Sept picks, held all 181d", E_cash)
print("=" * 78)
