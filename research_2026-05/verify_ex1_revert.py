#!/usr/bin/env python3
"""Verify the 4-revert edits to ex1.py are correct.

Edited ex1.py must behave IDENTICALLY to ex1_reval.py configured to the
validated 4-revert state (pre-09:50 block off, take_no_cap off, pre-10:00 TAKE
block off, post-11:00 TAKE block off; everything else shipped — confirm_bar,
two_bar_trail, early_weak, no_progress, SPY-gap skip, alloc 50/45 all kept).

Runs both over the 57-day window and compares per-date P&L. Any mismatch means
the hand edit diverged from the validated config. Scratch output only.
"""
import os, sys, glob, json, time, contextlib

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1
import ex1_reval as ev

dates = sorted(os.path.basename(f)[:-5]
               for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json")))
dates = [d for d in dates if "2026-03-02" <= d <= "2026-05-21"]

# ex1_reval -> the validated 4-revert config (must match edited ex1.py)
for k in ("confirm_bar", "two_bar_trail", "take_no_cap", "no_progress",
          "early_weak", "pre10_take_block", "post11_take_block"):
    ev.REVAL_FLAGS[k] = True
ev.REVAL_FLAGS["take_no_cap"]       = False
ev.REVAL_FLAGS["pre10_take_block"]  = False
ev.REVAL_FLAGS["post11_take_block"] = False
ev.ORB_MAYBE_EARLY_CUTOFF = "09:30"
ev.SPY_GAP_ORB_MAYBE_SKIP = -0.3
ev.ALLOC_PCT_BULL = {"TAKE": 0.50, "MAYBE": 0.20}
ev.ALLOC_PCT_NEUT = {"TAKE": 0.45, "MAYBE": 0.15}
ev.ALLOC_PCT_BEAR = {"TAKE": 0.10, "MAYBE": 0.10}

s1 = os.path.join(SIGNAL_DIR, "scratch_verify_ex1.json")
s2 = os.path.join(SIGNAL_DIR, "scratch_verify_reval.json")
for s in (s1, s2):
    if os.path.exists(s):
        os.remove(s)

print(f"verifying {len(dates)} dates {dates[0]} -> {dates[-1]}", flush=True)
mism = 0
t1 = t2 = 0.0
for i, d in enumerate(dates, 1):
    with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
        a = ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=s1)
        b = ev.run_ex1(trade_date=d, backfill=False, save=True, result_file=s2)
    t1 += a["total_pnl"]
    t2 += b["total_pnl"]
    if abs(a["total_pnl"] - b["total_pnl"]) >= 0.005:
        mism += 1
        print(f"  MISMATCH {d}: ex1.py={a['total_pnl']:+.2f}  reval={b['total_pnl']:+.2f}", flush=True)
    else:
        print(f"  [{i:2}/{len(dates)}] {d}  ok  ${a['total_pnl']:+8.2f}", flush=True)
    time.sleep(0.6)

print("\n" + "=" * 64)
print(f"ex1.py (edited)      total: ${t1:+,.2f}")
print(f"ex1_reval (validated) total: ${t2:+,.2f}")
print(f"mismatched dates: {mism}")
print("VERIFY RESULT: " + ("PASS — ex1.py edits match the validated config"
                           if mism == 0 else "** FAIL — edits diverge, do NOT proceed **"))
print("=" * 64)
