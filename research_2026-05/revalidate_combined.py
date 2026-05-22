#!/usr/bin/env python3
"""Re-validation Phase C — combined-revert confirmation.

B1 + B2 leave-one-out flagged 4 rules with material negative value on the
lookahead-fixed sim:
    pre-09:50 ORB-MAYBE block   (B1)  -$215
    SPY-gap <=-0.3% MAYBE skip  (B1)  -$45
    pre10_take_block            (B2)  -$80.56
    post11_take_block           (B2)  -$50.13
Leave-one-out tests each in isolation. The two B1 rules both act on ORB-MAYBE
entries and the two B2 rules both act on ORB-TAKE entries, so they interact —
the combined delta will NOT equal the -$390.69 sum. This run reverts all four
at once to get the real number. Scratch output only — never exercises.json.

Config 1 is an all-shipped sanity check — must reproduce ~+$1,134.81.
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


def all_shipped():
    for k in FLAGS:
        ex.REVAL_FLAGS[k] = True
    ex.ORB_MAYBE_EARLY_CUTOFF = "09:50"
    ex.SPY_GAP_ORB_MAYBE_SKIP = -0.3


def combined_revert():
    all_shipped()
    ex.ORB_MAYBE_EARLY_CUTOFF = "09:30"        # B1: pre-09:50 ORB-MAYBE block OFF
    ex.SPY_GAP_ORB_MAYBE_SKIP = -99.0          # B1: SPY-gap MAYBE skip OFF
    ex.REVAL_FLAGS["pre10_take_block"] = False  # B2
    ex.REVAL_FLAGS["post11_take_block"] = False # B2


CONFIGS = [
    ("ALL SHIPPED (sanity check)",        "scratch_revc_sanity.json",   all_shipped),
    ("COMBINED REVERT — 4 leaks OFF",     "scratch_revc_combined.json", combined_revert),
]

results = {}
for name, scratch, setup in CONFIGS:
    setup()
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
print("RE-VALIDATION C — combined-revert confirmation (fixed sim)")
sanity = results["ALL SHIPPED (sanity check)"]
combo = results["COMBINED REVERT — 4 leaks OFF"]
ok = "OK" if abs(sanity - BASELINE) < 5 else "** MISMATCH — copy is NOT faithful **"
print(f"All-shipped sanity:  ${sanity:+,.2f}  (expect ~${BASELINE:+,.2f})  [{ok}]")
print(f"Combined revert:     ${combo:+,.2f}")
print(f"Combined gain:       ${combo - sanity:+,.2f}   "
      f"(vs -$390.69 naive sum of the 4 leave-one-out deltas)")
print("=" * 70)
