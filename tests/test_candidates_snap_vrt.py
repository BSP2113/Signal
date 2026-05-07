"""
test_candidates_snap_vrt.py — Backtest candidate tickers in isolation.

Runs SNAP, VRT, CRWV, MU, PALAF, UEC, AZURF, JNUG through the EX1 sim
for the past 18 trading days. Reports per-ticker stats and a daily P&L table.
Does NOT modify exercises.json.

Run: venv/bin/python3 tests/test_candidates_snap_vrt.py
"""

import json, os, sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import ex1

CANDIDATES = ["SNAP", "VRT", "CRWV", "MU", "PALAF", "UEC", "AZURF", "JNUG"]
RESULT_FILE = os.path.join(BASE_DIR, "_test_candidates.json")

def get_live_dates():
    path = os.path.join(BASE_DIR, "exercises.json")
    data = json.load(open(path))
    dates = sorted({e["date"] for e in data if "Exercise 1" in e["title"]})
    return dates[-18:]

def ticker_stats(trades, label):
    if not trades:
        return f"  {label:<22} —  no trades (no IEX data or no signal fired)"
    wins   = [t for t in trades if t["pnl"] >= 0]
    losses = [t for t in trades if t["pnl"] <  0]
    total  = sum(t["pnl"] for t in trades)
    wr     = 100 * len(wins) // len(trades)
    avg_w  = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
    avg_l  = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    return (f"  {label:<22} {len(trades):>3} trades  {len(wins)}W/{len(losses)}L "
            f"({wr}% WR)  total ${total:+.2f}  avg_win ${avg_w:+.2f}  avg_loss ${avg_l:+.2f}")

def run():
    dates = get_live_dates()
    print(f"\nCandidate ticker test — {dates[0]} → {dates[-1]}  ({len(dates)} days)")
    print(f"Tickers: {', '.join(CANDIDATES)}\n")

    # Override TICKERS in ex1 for the test run
    original_tickers = ex1.TICKERS
    ex1.TICKERS = CANDIDATES
    # No TICKER_START restrictions for these candidates
    original_start = ex1.TICKER_START
    ex1.TICKER_START = {}

    results = []
    streak  = 0
    done    = []

    for date in dates:
        print(f"Running {date}...", flush=True)
        result = ex1.run_ex1(
            trade_date=date,
            backfill=False,
            save=False,
            result_file=RESULT_FILE,
            title="Candidate Test",
        )
        if result:
            results.append(result)
            day_pnl = result.get("total_pnl", 0)
            streak  = streak + 1 if day_pnl < 0 else 0
            done.append(date)

    # Restore
    ex1.TICKERS      = original_tickers
    ex1.TICKER_START = original_start

    if not results:
        print("No results returned.")
        return

    # Per-ticker stats
    print("\n" + "="*80)
    print("PER-TICKER STATS")
    print("="*80)
    ticker_trades = {t: [] for t in CANDIDATES}
    for r in results:
        for trade in r.get("trades", []):
            tk = trade["ticker"]
            if tk in ticker_trades:
                ticker_trades[tk].append(trade)

    ranked = sorted(CANDIDATES, key=lambda t: sum(x["pnl"] for x in ticker_trades[t]), reverse=True)
    for tk in ranked:
        print(ticker_stats(ticker_trades[tk], tk))

    # Day-by-day table
    print("\n" + "="*80)
    print("DAY-BY-DAY  (candidates only, EX1 rules, $5k budget)")
    print("="*80)
    print(f"\n  {'Date':<12} {'P&L':>9}   Tickers that traded")
    print("  " + "-"*60)
    total = 0.0
    for r in results:
        day_pnl = r.get("total_pnl", 0)
        tickers  = sorted({t["ticker"] for t in r.get("trades", [])})
        total   += day_pnl
        flag     = " ◄" if abs(day_pnl) > 30 else ""
        print(f"  {r['date']:<12} ${day_pnl:>+8.2f}   {', '.join(tickers) if tickers else '—'}{flag}")
    print("  " + "-"*60)
    print(f"  {'TOTAL':<12} ${total:>+8.2f}")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY — ranked by total P&L")
    print("="*80)
    for tk in ranked:
        trades = ticker_trades[tk]
        if not trades:
            print(f"  {tk:<8} — no data")
            continue
        wins  = sum(1 for t in trades if t["pnl"] >= 0)
        total_tk = sum(t["pnl"] for t in trades)
        wr    = 100 * wins // len(trades)
        print(f"  {tk:<8}  {wr}% WR  ${total_tk:+.2f}  ({len(trades)} trades)")

    days_w = sum(1 for r in results if r.get("total_pnl", 0) > 0)
    print(f"\n  Days profitable: {days_w}/{len(results)}")
    print()

if __name__ == "__main__":
    run()
