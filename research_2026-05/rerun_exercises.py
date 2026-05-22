#!/usr/bin/env python3
"""Chronologically re-run EX1 + EX2 in exercises.json with the 4 reverted rules.

The 4 reverts (pre-09:50 MAYBE block, TAKE no-cap, pre-10:00 TAKE block,
post-11:00 TAKE block) are now live in ex1.py / ex2.py. This regenerates the
Exercise 1 and Exercise 2 records so the live exercise log reflects them.

  - Exercise 3 (hybrid.py — not changed in this work) is preserved untouched.
  - backfill.json / backfill2.json (deep-history streak context, end 04-24 /
    04-10) are left as-is — that matches how the re-validation was computed.
  - A fresh timestamped backup is taken before the strip.

Each date is run chronologically with backfill=False so the wallet compounds
from $5,000, exactly per the project's re-run procedure.
"""
import os, sys, json, time, shutil, contextlib
from datetime import datetime

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1, ex2

EXJSON = os.path.join(SIGNAL_DIR, "exercises.json")

# --- fresh backup right before the destructive strip ---------------------
stamp  = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = os.path.join(SIGNAL_DIR, "backups", f"exercises.json.pre-rerun-{stamp}")
shutil.copy(EXJSON, backup)
print(f"backed up exercises.json -> {backup}", flush=True)

data = json.load(open(EXJSON))
def kind(e):
    t = e.get("title", "")
    for n in (1, 2, 3):
        if f"Exercise {n}" in t:
            return n
    return 0
ex1_entries = [e for e in data if kind(e) == 1]
ex2_entries = [e for e in data if kind(e) == 2]
ex3_entries = [e for e in data if kind(e) == 3]
other       = [e for e in data if kind(e) == 0]
print(f"current exercises.json: {len(ex1_entries)} EX1, {len(ex2_entries)} EX2, "
      f"{len(ex3_entries)} EX3, {len(other)} other", flush=True)

ex1_dates = sorted(e["date"] for e in ex1_entries)
ex2_dates = sorted(e["date"] for e in ex2_entries)
old1 = sum(e["total_pnl"] for e in ex1_entries)
old2 = sum(e["total_pnl"] for e in ex2_entries)

# --- strip EX1 + EX2, keep EX3 (+ other) ---------------------------------
kept = ex3_entries + other
with open(EXJSON, "w") as f:
    json.dump(kept, f, indent=2)
print(f"stripped EX1+EX2 — exercises.json now holds {len(kept)} entries\n", flush=True)

# --- re-run EX1 chronologically ------------------------------------------
print(f"=== re-running {len(ex1_dates)} EX1 dates ({ex1_dates[0]}..{ex1_dates[-1]}) ===", flush=True)
for i, d in enumerate(ex1_dates, 1):
    try:
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            r = ex1.run_ex1(trade_date=d, backfill=False, save=True)
        print(f"  [{i:2}/{len(ex1_dates)}] EX1 {d}  P&L ${r['total_pnl']:+8.2f}  "
              f"wallet ${r['portfolio_eod']:,.2f}", flush=True)
    except Exception as e:
        print(f"  [{i:2}/{len(ex1_dates)}] EX1 {d}  ERROR: {e!r}", flush=True)
    time.sleep(1.5)

# --- re-run EX2 chronologically ------------------------------------------
print(f"\n=== re-running {len(ex2_dates)} EX2 dates ({ex2_dates[0]}..{ex2_dates[-1]}) ===", flush=True)
for i, d in enumerate(ex2_dates, 1):
    try:
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            r = ex2.run_ex2(trade_date=d, backfill=False, save=True)
        print(f"  [{i:2}/{len(ex2_dates)}] EX2 {d}  P&L ${r['total_pnl']:+8.2f}  "
              f"wallet ${r['portfolio_eod']:,.2f}", flush=True)
    except Exception as e:
        print(f"  [{i:2}/{len(ex2_dates)}] EX2 {d}  ERROR: {e!r}", flush=True)
    time.sleep(1.5)

# --- verify --------------------------------------------------------------
final = json.load(open(EXJSON))
n1 = sum(1 for e in final if kind(e) == 1)
n2 = sum(1 for e in final if kind(e) == 2)
n3 = sum(1 for e in final if kind(e) == 3)
new1 = sum(e["total_pnl"] for e in final if kind(e) == 1)
new2 = sum(e["total_pnl"] for e in final if kind(e) == 2)
print("\n" + "=" * 66)
print(f"exercises.json: {len(final)} entries  ({n1} EX1, {n2} EX2, {n3} EX3)")
print(f"EX1 total:  ${old1:+,.2f}  ->  ${new1:+,.2f}   ({new1 - old1:+,.2f})")
print(f"EX2 total:  ${old2:+,.2f}  ->  ${new2:+,.2f}   ({new2 - old2:+,.2f})")
counts_ok = (n1 == len(ex1_dates) and n2 == len(ex2_dates) and n3 == len(ex3_entries))
print("RERUN RESULT: " + ("OK — entry counts match the original"
                           if counts_ok else f"** COUNT MISMATCH — restore from {backup} **"))
print("=" * 66)
