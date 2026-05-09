"""
test_take_sizing.py — Backtest TAKE allocation increases against the 48-date
sample (20 live + 28 backfill).

Reuses the simulate_day machinery from test_take_profit.py and monkey-patches
ex1.ALLOC_PCT_* per variant. Fetches each date's data ONCE and replays every
variant in memory.

Variants (BULL / NEUT / BEAR for TAKE; MAYBE held constant at 20/15/10):
  Baseline:   35 / 30 / 10
  Variant A:  40 / 35 / 10
  Variant B:  45 / 40 / 10
  Variant C:  50 / 45 / 10

Exit logic matches current production (TAKE rated → no +3% cap; MAYBE → +3% cap).
"""

import os, sys, json, statistics as _stats
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone
from alpaca.data.historical import StockHistoricalDataClient

import ex1
import test_take_profit as ttp


# ── Date setup (mirrors test_take_profit.py) ──────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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


# Production exit fn (TAKE → no cap; MAYBE → +3% cap). We must pass
# ttp.find_exit_option_c by identity — simulate_day uses `is` to detect this
# variant and pass the rating through. Any other wrapper would silently fall
# back to the +3% baseline.
find_exit_prod = ttp.find_exit_option_c


# ── Variant definitions: (name, BULL_TAKE, NEUT_TAKE) ────────────────────────
# MAYBE allocations stay at production (20% / 15% / 10%).
# BEAR TAKE stays at 10% (low conviction, low size).
VARIANTS = [
    ("Baseline 35/30",  0.35, 0.30),
    ("Variant A 40/35", 0.40, 0.35),
    ("Variant B 45/40", 0.45, 0.40),
    ("Variant C 50/45", 0.50, 0.45),
]


# ── Step 1: fetch each date's data ONCE ──────────────────────────────────────
key, secret = ex1._load_creds()
client = StockHistoricalDataClient(api_key=key, secret_key=secret)

print(f"\nFetching data for {len(DATES)} dates (once per date)...")
day_cache = {}
for date in DATES:
    day_cache[date] = ttp.fetch_day(client, date)


# ── Step 2: simulate each variant ─────────────────────────────────────────────
print("\nRunning simulations (in-memory, no Alpaca calls)...")

# Snapshot original allocations so we can restore.
_orig_bull = dict(ex1.ALLOC_PCT_BULL)
_orig_neut = dict(ex1.ALLOC_PCT_NEUT)
_orig_bear = dict(ex1.ALLOC_PCT_BEAR)

variant_results = {name: [] for name, _, _ in VARIANTS}

for vname, take_bull, take_neut in VARIANTS:
    print(f"\n  --- {vname} ---")
    # Monkey-patch ex1 allocations for this variant
    ex1.ALLOC_PCT_BULL = {"TAKE": take_bull, "MAYBE": _orig_bull["MAYBE"]}
    ex1.ALLOC_PCT_NEUT = {"TAKE": take_neut, "MAYBE": _orig_neut["MAYBE"]}
    ex1.ALLOC_PCT_BEAR = dict(_orig_bear)  # unchanged

    accumulated = []
    for date in DATES:
        dd      = day_cache[date]
        bal     = ttp.wallet_balance(accumulated)
        streak  = ttp.loss_streak(accumulated)
        drawdn  = ttp.in_drawdown(accumulated)
        mstate  = hist_states.get(date, "neutral")

        result = ttp.simulate_day(
            date, dd["ticker_data"], dd["eod_prices"], dd["spy_by_time"],
            dd["atr_modifier"], dd["prior_closes"], mstate,
            bal, streak, drawdn, find_exit_prod,
        )
        accumulated.append(result)
        variant_results[vname].append(result)
        s = "+" if result["total_pnl"] >= 0 else ""
        print(f"    {date}: {s}${result['total_pnl']:>7.2f}  "
              f"({result['total_trades']:>2} trades, "
              f"wallet ${bal + result['total_pnl']:>9,.2f})")

# Restore originals (good hygiene; doesn't matter at script exit but cleaner)
ex1.ALLOC_PCT_BULL = _orig_bull
ex1.ALLOC_PCT_NEUT = _orig_neut
ex1.ALLOC_PCT_BEAR = _orig_bear


# ── Step 3: comparison report ─────────────────────────────────────────────────
vnames = [n for n, _, _ in VARIANTS]

print(f"\n{'═'*88}")
print(f"  TAKE SIZING COMPARISON — {len(DATES)} dates")
print(f"  (MAYBE allocations held at production: 20% BULL / 15% NEUT / 10% BEAR)")
print(f"{'═'*88}")

# Header
header = f"  {'Date':<12}"
for n in vnames:
    header += f"  {n:>15}"
print(header)
print("  " + "─" * (12 + len(vnames) * 17))

totals = {n: 0.0 for n in vnames}
wins   = {n: 0   for n in vnames}
worsts = {n: ( 0.0, "") for n in vnames}  # (pnl, date)
bests  = {n: ( 0.0, "") for n in vnames}

for date in DATES:
    row = f"  {date:<12}"
    for n in vnames:
        day = next((r for r in variant_results[n] if r["date"] == date), None)
        pnl = day["total_pnl"] if day else 0.0
        totals[n] += pnl
        if pnl > 0:
            wins[n] += 1
        if pnl < worsts[n][0]:
            worsts[n] = (pnl, date)
        if pnl > bests[n][0]:
            bests[n] = (pnl, date)
        row += f"  {pnl:>+14.2f}"
    print(row)

print("  " + "─" * (12 + len(vnames) * 17))

row = f"  {'TOTAL':<12}"
for n in vnames:
    row += f"  {totals[n]:>+14.2f}"
print(row)

row = f"  {'WIN DAYS':<12}"
for n in vnames:
    row += f"  {wins[n]:>11}/{len(DATES):<3}"
print(row)

row = f"  {'BEST DAY':<12}"
for n in vnames:
    row += f"  {bests[n][0]:>+14.2f}"
print(row)

row = f"  {'WORST DAY':<12}"
for n in vnames:
    row += f"  {worsts[n][0]:>+14.2f}"
print(row)

baseline = totals[vnames[0]]
row = f"  {'vs baseline':<12}"
row += f"  {'—':>15}"
for n in vnames[1:]:
    delta = totals[n] - baseline
    row += f"  {delta:>+14.2f}"
print(row)

best_v = max(vnames, key=lambda n: totals[n])
print(f"\n  Best by total: {best_v}  (${totals[best_v]:+.2f})")
print(f"{'═'*88}\n")


# ── Live vs backfill split ────────────────────────────────────────────────────
print(f"  SPLIT: live ({sum(1 for d in DATES if date_source[d]=='live')}d) "
      f"vs backfill ({sum(1 for d in DATES if date_source[d]=='backfill')}d)")
print(f"  {'Variant':<20}  {'live $':>11}  {'live W':>8}  {'back $':>11}  {'back W':>8}")
print("  " + "─" * 66)
for n in vnames:
    l_pnl = sum(r["total_pnl"] for r in variant_results[n]
                if date_source.get(r["date"]) == "live")
    l_wins = sum(1 for r in variant_results[n]
                 if date_source.get(r["date"]) == "live" and r["total_pnl"] > 0)
    l_days = sum(1 for d in DATES if date_source.get(d) == "live")
    b_pnl = sum(r["total_pnl"] for r in variant_results[n]
                if date_source.get(r["date"]) == "backfill")
    b_wins = sum(1 for r in variant_results[n]
                 if date_source.get(r["date"]) == "backfill" and r["total_pnl"] > 0)
    b_days = sum(1 for d in DATES if date_source.get(d) == "backfill")
    print(f"  {n:<20}  {l_pnl:>+11.2f}  {l_wins:>3}/{l_days:<3}  "
          f"{b_pnl:>+11.2f}  {b_wins:>3}/{b_days:<3}")
print()
