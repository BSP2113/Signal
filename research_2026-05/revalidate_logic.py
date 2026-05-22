#!/usr/bin/env python3
"""Re-validation Phase B2 — the 7 logic-driven shipped rules, on the
lookahead-fixed sim.

Leave-one-out: each rule flipped OFF in turn (every other rule left shipped),
57-day fixed sim (2026-03-02..05-21), compared to the all-shipped run.
Value of rule = all-shipped - rule-off.  The first config is an all-shipped
sanity check — it MUST reproduce ~+$1,134.81 or the guarded copy is broken.
Scratch output only — never exercises.json.
"""
import os, sys, glob, json, time, contextlib

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1_reval as ex

WIN_START, WIN_END = "2026-03-02", "2026-05-21"
BASELINE = 1134.81

dates = sorted(os.path.basename(f)[:-5]
               for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json")))
dates = [d for d in dates if WIN_START <= d <= WIN_END]
print(f"{len(dates)} dates {dates[0]} -> {dates[-1]}", flush=True)

FLAGS = ["confirm_bar", "two_bar_trail", "take_no_cap", "no_progress",
         "early_weak", "pre10_take_block", "post11_take_block"]
CONFIGS = [("ALL SHIPPED (sanity check)", None)] + [(f"{f} OFF", f) for f in FLAGS]

results = {}
for name, off in CONFIGS:
    for k in FLAGS:
        ex.REVAL_FLAGS[k] = True
    if off:
        ex.REVAL_FLAGS[off] = False
    scratch = f"scratch_revb2_{off or 'sanity'}.json"
    spath = os.path.join(SIGNAL_DIR, scratch)
    if os.path.exists(spath):
        os.remove(spath)
    print(f"\n=== {name}  ->  {scratch} ===", flush=True)
    for i, d in enumerate(dates, 1):
        try:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                e = ex.run_ex1(trade_date=d, backfill=False, save=True, result_file=scratch)
            print(f"  [{i:2}/{len(dates)}] {d}  P&L=${e['total_pnl']:+8.2f}  "
                  f"wallet=${e['portfolio_eod']:,.2f}", flush=True)
        except Exception as err:
            print(f"  [{i:2}/{len(dates)}] {d}  ERROR: {err!r}", flush=True)
        time.sleep(1.5)
    data = [x for x in json.load(open(spath)) if "Exercise 1" in x["title"]]
    results[name] = sum(x["total_pnl"] for x in data)
    print(f"  total = ${results[name]:+,.2f}", flush=True)

print("\n" + "=" * 70)
print("RE-VALIDATION B2 — logic-driven shipped rules (57-day fixed sim)")
sanity = results.get("ALL SHIPPED (sanity check)")
ok = "OK" if abs(sanity - BASELINE) < 5 else "** MISMATCH — copy is NOT faithful **"
print(f"All-shipped sanity: ${sanity:+,.2f}  (expect ~${BASELINE:+,.2f})  [{ok}]")
print("-" * 70)
for name, total in results.items():
    if name.startswith("ALL SHIPPED"):
        continue
    value = sanity - total
    tag = "REAL - keep" if value >= 25 else ("ARTIFACT - revert?" if value <= 0 else "marginal")
    print(f"  {name}")
    print(f"    rule OFF total ${total:+,.2f}   |   value of rule ${value:+,.2f}   [{tag}]")
print("=" * 70)
