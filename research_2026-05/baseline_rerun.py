#!/usr/bin/env python3
"""Pass 1 — Fixed-17 baseline re-run on the lookahead-fixed sim.
Chronological, 2026-03-02 -> 2026-05-21. Writes to a SCRATCH file only —
never exercises.json / backfill.json.
Usage: python baseline_rerun.py [N]   (N = run only first N dates = smoke test)
"""
import sys, os, glob, json, time, contextlib

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1

SCRATCH      = "scratch_baseline_5821.json"          # relative -> Signal/
scratch_path = os.path.join(SIGNAL_DIR, SCRATCH)
WIN_START, WIN_END = "2026-03-02", "2026-05-21"
LIVE_START   = "2026-04-13"                          # exercises.json live record begins here

if os.path.exists(scratch_path):                     # fresh start
    os.remove(scratch_path)

dates = sorted(
    os.path.basename(f)[:-5]
    for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json"))
)
dates = [d for d in dates if WIN_START <= d <= WIN_END]

limit   = int(sys.argv[1]) if len(sys.argv) > 1 else None
verbose = limit is not None
if limit:
    dates = dates[:limit]

print("=== Pass 1: Fixed-17 baseline (lookahead-fixed sim) ===")
print(f"{len(dates)} trading days, {dates[0]} -> {dates[-1]}")
print(f"Output: {scratch_path}  (scratch only)\n")

failed = []
for i, d in enumerate(dates, 1):
    try:
        if verbose:
            ex = ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=SCRATCH)
        else:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                ex = ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=SCRATCH)
        print(f"[{i:2}/{len(dates)}] {d}  {ex['market_state']:>7}  "
              f"trades={ex['total_trades']:2}  P&L=${ex['total_pnl']:+8.2f}  "
              f"wallet=${ex['portfolio_eod']:,.2f}")
    except Exception as e:
        failed.append((d, repr(e)))
        print(f"[{i:2}/{len(dates)}] {d}  ERROR: {e!r}")
    if i < len(dates):
        time.sleep(2)

print("\n" + "=" * 62)
if not os.path.exists(scratch_path):
    print("No scratch file written — every date failed or produced no trades.")
    sys.exit(1)
with open(scratch_path) as f:
    data = json.load(f)
e1 = [e for e in data if "Exercise 1" in e["title"]]

def slice_stats(entries, label):
    pnl    = sum(e["total_pnl"] for e in entries)
    trades = [t for e in entries for t in e["trades"]]
    wins   = sum(1 for t in trades if t.get("pnl", t.get("dollar_pnl", 0)) > 0)
    wr     = (wins / len(trades) * 100) if trades else 0.0
    print(f"  {label:10} days={len(entries):2}  trades={len(trades):3}  "
          f"WR={wr:5.1f}%  P&L=${pnl:+,.2f}")
    return pnl

print("FIXED-17 BASELINE")
total = slice_stats(e1, "ALL")
slice_stats([e for e in e1 if e["date"] <  LIVE_START], "backfill")
slice_stats([e for e in e1 if e["date"] >= LIVE_START], "live")
print(f"\n  Final wallet: ${5000 + total:,.2f}")
if failed:
    print(f"  {len(failed)} date(s) FAILED: " + ", ".join(d for d, _ in failed))
print("=" * 62)
