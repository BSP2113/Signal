#!/usr/bin/env python3
"""Re-validation FULL clean re-run — B1 + B2 + combined, one consistent batch.

2026-05-22: market_states_historical.json was stale (last entry 05-06, missing
11 trading days) and ex1_reval.py leaked the live market_state.json into
historical re-runs. Both are now fixed — the historical file is backfilled
through 05-21 and the live-file read is guarded to same-day only.

This re-runs every shipped-rule leave-one-out test against the corrected data.
The all-shipped config defines the NEW baseline; the old +$1,134.81 was built
on wrong market states (two bear days sized as neutral) and is discarded.
Combined config reverts every rule that comes out negative-value.
Scratch output only — exercises.json is never touched.
"""
import os, sys, glob, json, time, contextlib

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1_reval as ex

WIN_START, WIN_END = "2026-03-02", "2026-05-21"

dates = sorted(os.path.basename(f)[:-5]
               for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json")))
dates = [d for d in dates if WIN_START <= d <= WIN_END]
print(f"{len(dates)} dates {dates[0]} -> {dates[-1]}", flush=True)

FLAGS = ["confirm_bar", "two_bar_trail", "take_no_cap", "no_progress",
         "early_weak", "pre10_take_block", "post11_take_block"]


def set_shipped():
    """Restore every rule to its current shipped value."""
    for k in FLAGS:
        ex.REVAL_FLAGS[k] = True
    ex.ORB_MAYBE_EARLY_CUTOFF = "09:50"
    ex.SPY_GAP_ORB_MAYBE_SKIP = -0.3
    ex.ALLOC_PCT_BULL = {"TAKE": 0.50, "MAYBE": 0.20}
    ex.ALLOC_PCT_NEUT = {"TAKE": 0.45, "MAYBE": 0.15}
    ex.ALLOC_PCT_BEAR = {"TAKE": 0.10, "MAYBE": 0.10}


# --- revert actions (each undoes ONE shipped rule) -----------------------
def rv_alloc():
    ex.ALLOC_PCT_BULL = {"TAKE": 0.35, "MAYBE": 0.20}   # pre-2026-05-09 sizing
    ex.ALLOC_PCT_NEUT = {"TAKE": 0.30, "MAYBE": 0.15}
def rv_pre0950():
    ex.ORB_MAYBE_EARLY_CUTOFF = "09:30"                 # disable the pre-09:50 block
def rv_spygap():
    ex.SPY_GAP_ORB_MAYBE_SKIP = -99.0                   # disable the SPY-gap skip
def rv_flag(f):
    return lambda: ex.REVAL_FLAGS.__setitem__(f, False)

CONFIGS = [
    ("B1: TAKE alloc reverted 50/45 -> 35/30", "alloc",   rv_alloc),
    ("B1: pre-09:50 ORB-MAYBE block OFF",      "pre0950", rv_pre0950),
    ("B1: SPY-gap <=-0.3% MAYBE skip OFF",     "spygap",  rv_spygap),
]
for f in FLAGS:
    CONFIGS.append((f"B2: {f} OFF", f, rv_flag(f)))


def run_config(name, scratch, setup):
    set_shipped()
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
    total = sum(x["total_pnl"] for x in data)
    print(f"  total = ${total:+,.2f}", flush=True)
    return total


results = {}
baseline = run_config("ALL SHIPPED (new clean baseline)",
                      "scratch_revfull_baseline.json", lambda: None)
for name, key, setup in CONFIGS:
    results[key] = run_config(name, f"scratch_revfull_{key}.json", setup)

# combined: revert every rule whose value (baseline - rule-off total) is negative
leaks = [(name, key, setup) for (name, key, setup) in CONFIGS
         if (baseline - results[key]) < 0]
if leaks:
    def combined_setup():
        for _, _, setup in leaks:
            setup()
    combined = run_config("COMBINED: all negative-value rules reverted",
                          "scratch_revfull_combined.json", combined_setup)
else:
    combined = None

# --- report --------------------------------------------------------------
print("\n" + "=" * 74)
print("RE-VALIDATION FULL — clean re-run on corrected market-state data")
print(f"New all-shipped baseline: ${baseline:+,.2f}   ({len(dates)} dates)")
print("-" * 74)
for name, key, setup in CONFIGS:
    total = results[key]
    value = baseline - total
    tag = "REAL - keep" if value >= 25 else ("LEAK - revert" if value < 0 else "marginal")
    print(f"  {name}")
    print(f"    rule OFF total ${total:+,.2f}   |   value of rule ${value:+,.2f}   [{tag}]")
print("-" * 74)
if leaks:
    keys = [k for _, k, _ in leaks]
    naive_gain = sum(results[k] - baseline for k in keys)
    print(f"  COMBINED revert of {len(leaks)} negative rules: {keys}")
    print(f"    combined total ${combined:+,.2f}   |   actual gain vs baseline "
          f"${combined - baseline:+,.2f}")
    print(f"    (naive sum of those leave-one-out gains: ${naive_gain:+,.2f} — "
          f"differs because the rules interact)")
else:
    print("  No negative-value rules — nothing to revert.")
print("=" * 74)
