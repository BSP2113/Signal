"""
test_top20_rotation.py — Backtest using picker-short's daily-rotating top-20
ticker list instead of the fixed Signal Reader 17.

For each historical date (live + backfill), compute what picker-short would
have ranked as top-20 *as of that morning* (no look-ahead), then run the
existing simulate logic with that ticker set.

Universe: S&P 500 + NASDAQ 100 (picker-short's current universe).
Missing intraday data: skip the ticker, keep the rest.
Exit logic: current production (TAKE = no cap, MAYBE = +3% cap, shipped 2026-05-08).
"""

import os, sys, json, statistics as _stats
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/ben/picker-short")

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

import ex1
# IMPORTANT: picker-short's settings.py auto-excludes the current 17 Signal Reader
# tickers from its universe. For this fairness test we want them eligible — so
# override EXCLUDED before importing universe.
from config import settings as _ps_settings
_ps_settings.EXCLUDED = set(_ps_settings.NO_FLY)  # keep no-fly only

from screener.universe import get_raw_universe
from screener import score as picker_score

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ET = "America/New_York"
TOP_N = 20
LOOKBACK = 45  # daily bars needed for scoring (30-day window + buffer)


# ── Load test dates (same setup as test_take_profit.py) ───────────────────────
def _classify(spy_gap_pct, vixy_trend_pct):
    if spy_gap_pct / 100 <= ex1.SPY_BEAR or vixy_trend_pct / 100 >= ex1.VIXY_SURGE:
        return "bearish"
    if spy_gap_pct / 100 >= ex1.SPY_BULL and vixy_trend_pct / 100 < ex1.VIXY_SURGE:
        return "bullish"
    return "neutral"

hist_states = {}
date_source = {}

with open(os.path.join(BASE_DIR, "exercises.json")) as f:
    for d in json.load(f):
        if "Exercise 1" in d["title"]:
            hist_states[d["date"]] = d["market_state"]
            date_source[d["date"]] = "live"

with open(os.path.join(BASE_DIR, "market_states_historical.json")) as f:
    _msh = {row["date"]: row for row in json.load(f)}

with open(os.path.join(BASE_DIR, "backfill.json")) as f:
    for d in json.load(f):
        date = d["date"]
        if date in hist_states:
            continue
        row = _msh.get(date)
        if row:
            hist_states[date] = _classify(row["spy_gap_pct"], row["vixy_trend_pct"])
        else:
            hist_states[date] = d.get("market_state", "neutral")
        date_source[date] = "backfill"

DATES = sorted(hist_states.keys())
print(f"Loaded {len(DATES)} dates ({sum(1 for d in DATES if date_source[d]=='live')} live, "
      f"{sum(1 for d in DATES if date_source[d]=='backfill')} backfill)")


# ── Step 1: Get universe and bulk-download daily bars via yfinance ────────────
print("\n[1/4] Building universe from S&P 500 + NDX 100...")
universe, _sector_map = get_raw_universe()
universe = sorted(set(universe) | {"SPY"})
print(f"  Universe: {len(universe)} tickers")

# Need data from earliest_date - LOOKBACK to latest_date
earliest = (datetime.strptime(DATES[0], "%Y-%m-%d") - timedelta(days=LOOKBACK + 30)).strftime("%Y-%m-%d")
latest   = (datetime.strptime(DATES[-1], "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")

import pickle
DAILY_CACHE_FILE = os.path.join(BASE_DIR, "data_cache", "top20_yf_daily.pkl")
os.makedirs(os.path.dirname(DAILY_CACHE_FILE), exist_ok=True)

def _fetch_yfinance_bulk():
    print(f"  Downloading yfinance daily bars {earliest} → {latest} ({len(universe)} tickers)...")
    BATCH = 100
    all_frames = []
    for i in range(0, len(universe), BATCH):
        batch = universe[i:i+BATCH]
        print(f"    batch {i//BATCH + 1}/{(len(universe)+BATCH-1)//BATCH}...", flush=True)
        try:
            raw = yf.download(batch, start=earliest, end=latest,
                              interval="1d", group_by="ticker",
                              auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print(f"    batch failed: {e}")
            continue
        for t in batch:
            try:
                df = raw[t].dropna() if isinstance(raw.columns, pd.MultiIndex) else raw.dropna()
                if not df.empty:
                    df = df.copy()
                    df["ticker"] = t
                    all_frames.append(df.reset_index())
            except KeyError:
                continue
    return pd.concat(all_frames, ignore_index=True)

if os.path.exists(DAILY_CACHE_FILE):
    print(f"  Using cached daily bars: {DAILY_CACHE_FILE}")
    with open(DAILY_CACHE_FILE, "rb") as f:
        daily_all = pickle.load(f)
else:
    daily_all = _fetch_yfinance_bulk()
    with open(DAILY_CACHE_FILE, "wb") as f:
        pickle.dump(daily_all, f)
    print(f"  Cached to {DAILY_CACHE_FILE}")

daily_all["Date"] = pd.to_datetime(daily_all["Date"]).dt.tz_localize(None)
print(f"  Loaded {len(daily_all):,} daily rows across {daily_all['ticker'].nunique()} tickers")


# ── Step 2: For each test date, compute top-20 using picker-short logic ──────
print("\n[2/4] Computing rotating top-20 per date (no look-ahead)...")

def _slice_as_of(date_str):
    """Return dict of {ticker: DataFrame} with daily bars up to and including date_str."""
    cutoff = pd.to_datetime(date_str)
    sliced = daily_all[daily_all["Date"] <= cutoff].copy()
    out = {}
    for t, df in sliced.groupby("ticker"):
        df = df.sort_values("Date").tail(LOOKBACK)
        if len(df) < 10:
            continue
        df = df.set_index("Date")
        out[t] = df
    return out

def top20_for_date(date_str):
    sliced = _slice_as_of(date_str)
    if "SPY" not in sliced:
        return []
    # Apply picker-short price/volume filters (same as data.py)
    from config.settings import MIN_PRICE, MAX_PRICE, MIN_AVG_VOLUME
    filtered = {}
    for t, df in sliced.items():
        price = float(df["Close"].iloc[-1])
        avg_vol = float(df["Volume"].mean())
        if t == "SPY" or (MIN_PRICE <= price <= MAX_PRICE and avg_vol >= MIN_AVG_VOLUME):
            filtered[t] = df
    ranked = picker_score.score_tickers(filtered)
    if ranked.empty:
        return []
    return ranked.head(TOP_N)["ticker"].tolist()

top20_by_date = {}
for date in DATES:
    top20_by_date[date] = top20_for_date(date)
    print(f"  {date}: {len(top20_by_date[date])} tickers — {','.join(top20_by_date[date][:6])}...")


# ── Step 3: Simulate using existing test_take_profit machinery ────────────────
print("\n[3/4] Fetching Alpaca intraday + simulating per date...")
import test_take_profit as ttp

key, secret = ex1._load_creds()
client = StockHistoricalDataClient(api_key=key, secret_key=secret)


def _yf_to_alpaca(t):
    """yfinance uses 'BRK-B'; Alpaca uses 'BRK.B' for share classes."""
    return t.replace("-", ".") if "-" in t else t


def _safe_get_bars(client, symbols, timeframe, start, end):
    """Try the full batch; if Alpaca rejects on one symbol, drop it and retry."""
    syms = list(symbols)
    while syms:
        try:
            return client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=syms, timeframe=timeframe,
                start=start, end=end, feed="iex",
            ))
        except Exception as e:
            msg = str(e)
            # Alpaca returns {"message":"invalid symbol: XYZ"} — strip and retry
            import re
            m = re.search(r"invalid symbol:\s*([A-Z0-9.\-]+)", msg)
            if m and m.group(1) in syms:
                syms = [s for s in syms if s != m.group(1)]
                continue
            return None
    return None


def fetch_day_custom(client, date, tickers):
    """Mirror of ttp.fetch_day, but with a custom ticker list."""
    next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    start_dt = datetime.strptime(date,     "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt   = datetime.strptime(next_day, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if not tickers:
        return None

    # Convert yfinance-style symbols (BRK-B) to Alpaca-style (BRK.B). Track both
    # forms so we can map back when reading bar results.
    alpaca_tickers = [_yf_to_alpaca(t) for t in tickers]

    # EOD prices
    daily = _safe_get_bars(client, alpaca_tickers, TimeFrame.Day, start_dt, end_dt)
    eod_prices = {}
    if daily:
        for t in alpaca_tickers:
            bars = daily.data.get(t, [])
            if bars:
                eod_prices[t] = round(bars[0].close, 2)

    # Prior closes + ATR
    prior_daily = _safe_get_bars(client, alpaca_tickers, TimeFrame.Day,
                                 start_dt - timedelta(days=21), start_dt)
    prior_closes = {}
    atr_pcts     = {}
    if prior_daily:
        for t in alpaca_tickers:
            bars = prior_daily.data.get(t, [])
            if bars:
                prior_closes[t] = bars[-1].close
                val = ex1.calc_atr_pct(bars)
                if val:
                    atr_pcts[t] = val

    if len(atr_pcts) >= 2:
        med = _stats.median(atr_pcts.values())
        atr_modifier = {
            t: round(min(ex1.ATR_MAX_MOD, max(ex1.ATR_MIN_MOD, med / atr_pcts[t])), 3)
            for t in atr_pcts
        }
    else:
        atr_modifier = {}

    # SPY intraday
    spy_by_time = {}
    try:
        spy_intra = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols="SPY", timeframe=TimeFrame.Minute,
            start=start_dt, end=end_dt, feed="iex",
        ))
        df_spy = spy_intra.df
        if isinstance(df_spy.index, pd.MultiIndex):
            df_spy = df_spy.xs("SPY", level=0)
        df_spy    = df_spy.tz_convert(ET)
        spy_today = df_spy.between_time("09:30", "15:59")
        for t, row in spy_today.iterrows():
            spy_by_time[t.strftime("%H:%M")] = row["close"]
    except Exception:
        pass

    # Per-ticker intraday — fetch each individually so a bad symbol can't kill the batch
    ticker_data = {}
    for ticker in alpaca_tickers:
        if ticker not in eod_prices:
            continue
        try:
            intra = client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=ticker, timeframe=TimeFrame.Minute,
                start=start_dt, end=end_dt, feed="iex",
            ))
            df = intra.df
            if df.empty:
                continue
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(ticker, level=0)
            df    = df.tz_convert(ET)
            today = df.between_time("09:30", "15:59")
            if today.empty:
                continue
            ticker_data[ticker] = {
                "closes":  [round(float(v), 2) for v in today["close"].tolist()],
                "highs":   [round(float(v), 2) for v in today["high"].tolist()],
                "lows":    [round(float(v), 2) for v in today["low"].tolist()],
                "volumes": [int(v) for v in today["volume"].tolist()],
                "times":   [t.strftime("%H:%M") for t in today.index],
            }
        except Exception:
            pass

    return {
        "eod_prices":   eod_prices,
        "prior_closes": prior_closes,
        "atr_modifier": atr_modifier,
        "spy_by_time":  spy_by_time,
        "ticker_data":  ticker_data,
    }


# Find_exit that matches current production: TAKE rated → no cap, else +3% cap.
def find_exit_prod(closes, times, entry_price, entry_bar, ticker=None, rating=None):
    fe = ttp.FE_NO_CAP if rating == "TAKE" else ttp.FE_BASELINE
    return fe(closes, times, entry_price, entry_bar, ticker)


# Run BOTH variants: fixed-17 baseline AND rotating top-20.
results_fixed   = []
results_rotated = []

for date in DATES:
    mstate = hist_states.get(date, "neutral")

    # Fixed-17 (current production)
    bal_fixed   = ttp.wallet_balance(results_fixed)
    streak_f    = ttp.loss_streak(results_fixed)
    drawdn_f    = ttp.in_drawdown(results_fixed)
    dd_fixed    = ttp.fetch_day(client, date)
    res_fixed   = ttp.simulate_day(
        date, dd_fixed["ticker_data"], dd_fixed["eod_prices"], dd_fixed["spy_by_time"],
        dd_fixed["atr_modifier"], dd_fixed["prior_closes"], mstate,
        bal_fixed, streak_f, drawdn_f, find_exit_prod,
    )
    results_fixed.append(res_fixed)

    # Rotating top-20
    bal_rot   = ttp.wallet_balance(results_rotated)
    streak_r  = ttp.loss_streak(results_rotated)
    drawdn_r  = ttp.in_drawdown(results_rotated)
    top20     = top20_by_date[date]
    dd_rot    = fetch_day_custom(client, date, top20)
    if dd_rot is None or not dd_rot["ticker_data"]:
        res_rot = {"date": date, "total_pnl": 0.0, "total_trades": 0, "trades": [],
                   "starting_cap": bal_rot, "market_state": mstate}
    else:
        res_rot = ttp.simulate_day(
            date, dd_rot["ticker_data"], dd_rot["eod_prices"], dd_rot["spy_by_time"],
            dd_rot["atr_modifier"], dd_rot["prior_closes"], mstate,
            bal_rot, streak_r, drawdn_r, find_exit_prod,
        )
    results_rotated.append(res_rot)

    f_pnl = res_fixed["total_pnl"]; r_pnl = res_rot["total_pnl"]
    delta = r_pnl - f_pnl
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "·")
    print(f"  {date}: fixed {f_pnl:+8.2f} ({res_fixed['total_trades']:>2}t)  "
          f"rotated {r_pnl:+8.2f} ({res_rot['total_trades']:>2}t/{len(top20_by_date[date]):>2}u)  "
          f"{arrow} {delta:+7.2f}")


# ── Step 4: Comparison report ────────────────────────────────────────────────
print("\n[4/4] Summary")

def _stats_for(results):
    total = sum(r["total_pnl"] for r in results)
    wins  = sum(1 for r in results if r["total_pnl"] > 0)
    return total, wins

f_total, f_wins = _stats_for(results_fixed)
r_total, r_wins = _stats_for(results_rotated)

print(f"\n{'═'*68}")
print(f"  TICKER ROTATION COMPARISON — {len(DATES)} dates")
print(f"{'═'*68}")
print(f"  {'Variant':<24}  {'Total $':>12}  {'Win Days':>10}  {'vs base':>10}")
print(f"  {'-'*22}    {'-'*12}  {'-'*10}  {'-'*10}")
print(f"  {'Fixed 17 (production)':<24}  {f_total:>+12.2f}  {f_wins:>4}/{len(DATES):<4}  {'—':>10}")
print(f"  {'Rotated top-20':<24}  {r_total:>+12.2f}  {r_wins:>4}/{len(DATES):<4}  {r_total-f_total:>+10.2f}")

# Live vs backfill split
live_dates = [d for d in DATES if date_source[d] == "live"]
back_dates = [d for d in DATES if date_source[d] == "backfill"]

def _split_stats(results, dates_subset):
    sub = [r for r in results if r["date"] in dates_subset]
    return sum(r["total_pnl"] for r in sub), sum(1 for r in sub if r["total_pnl"] > 0)

print(f"\n  SPLIT: live ({len(live_dates)}d) vs backfill ({len(back_dates)}d)")
print(f"  {'Variant':<24}  {'live $':>10}  {'live W':>8}  {'back $':>10}  {'back W':>8}")
print(f"  {'-'*22}    {'-'*10}  {'-'*8}  {'-'*10}  {'-'*8}")
fl, flw = _split_stats(results_fixed, live_dates)
fb, fbw = _split_stats(results_fixed, back_dates)
rl, rlw = _split_stats(results_rotated, live_dates)
rb, rbw = _split_stats(results_rotated, back_dates)
print(f"  {'Fixed 17':<24}  {fl:>+10.2f}  {flw:>3}/{len(live_dates):<3}  {fb:>+10.2f}  {fbw:>3}/{len(back_dates):<3}")
print(f"  {'Rotated top-20':<24}  {rl:>+10.2f}  {rlw:>3}/{len(live_dates):<3}  {rb:>+10.2f}  {rbw:>3}/{len(back_dates):<3}")

# Top-ticker overlap analysis
overlap_counts = {t: 0 for t in ex1.TICKERS}
total_top20 = 0
for date in DATES:
    top = set(top20_by_date[date])
    total_top20 += len(top)
    for t in ex1.TICKERS:
        if t in top:
            overlap_counts[t] += 1

print(f"\n  TOP-20 OVERLAP WITH FIXED 17:")
for t, count in sorted(overlap_counts.items(), key=lambda x: -x[1]):
    print(f"    {t:6s} appeared in top-20 on {count:>2}/{len(DATES)} days")
print()
