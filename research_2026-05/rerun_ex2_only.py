#!/usr/bin/env python3
"""Re-run ONLY Exercise 2 in exercises.json.

The -2.0% stop helps EX1 but cost EX2 -$55 (re-entry/realloc cascade), so
ex2.py was reverted to -1.5%. EX1 (already at -2.0%) and EX3 stay as-is;
this regenerates just the EX2 record to match the reverted ex2.py.
"""
import os, sys, json, time, shutil, contextlib
from datetime import datetime

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex2

EXJSON = os.path.join(SIGNAL_DIR, "exercises.json")
stamp  = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = os.path.join(SIGNAL_DIR, "backups", f"exercises.json.pre-ex2rerun-{stamp}")
shutil.copy(EXJSON, backup)
print(f"backed up exercises.json -> {backup}", flush=True)

data = json.load(open(EXJSON))
def kind(e):
    t = e.get("title", "")
    for n in (1, 2, 3):
        if f"Exercise {n}" in t:
            return n
    return 0
ex2_entries = [e for e in data if kind(e) == 2]
keep        = [e for e in data if kind(e) != 2]   # EX1 + EX3 + other
ex2_dates   = sorted(e["date"] for e in ex2_entries)
old2        = sum(e["total_pnl"] for e in ex2_entries)
print(f"current: {len(ex2_entries)} EX2 entries; keeping {len(keep)} (EX1+EX3)", flush=True)

with open(EXJSON, "w") as f:
    json.dump(keep, f, indent=2)
print(f"stripped EX2 — re-running {len(ex2_dates)} dates "
      f"({ex2_dates[0]}..{ex2_dates[-1]})\n", flush=True)

for i, d in enumerate(ex2_dates, 1):
    try:
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            r = ex2.run_ex2(trade_date=d, backfill=False, save=True)
        print(f"  [{i:2}/{len(ex2_dates)}] EX2 {d}  P&L ${r['total_pnl']:+8.2f}  "
              f"wallet ${r['portfolio_eod']:,.2f}", flush=True)
    except Exception as e:
        print(f"  [{i:2}/{len(ex2_dates)}] EX2 {d}  ERROR: {e!r}", flush=True)
    time.sleep(1.5)

final = json.load(open(EXJSON))
n1 = sum(1 for e in final if kind(e) == 1)
n2 = sum(1 for e in final if kind(e) == 2)
n3 = sum(1 for e in final if kind(e) == 3)
new2 = sum(e["total_pnl"] for e in final if kind(e) == 2)
print("\n" + "=" * 60)
print(f"exercises.json: {len(final)} entries  ({n1} EX1, {n2} EX2, {n3} EX3)")
print(f"EX2 total:  ${old2:+,.2f}  ->  ${new2:+,.2f}   ({new2 - old2:+,.2f})")
print("EX2 RERUN RESULT: " + ("OK — counts match"
                              if n2 == len(ex2_dates) else f"** MISMATCH — restore {backup} **"))
print("=" * 60)
