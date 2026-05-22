#!/usr/bin/env python3
"""Re-validation Phase B1 — the 3 constant-driven shipped rules, on the
lookahead-fixed sim.

For each rule: run the 57-day fixed sim (2026-03-02..05-21) with that ONE rule
reverted to its pre-shipped value, every other rule left shipped. Compare to the
all-rules-on baseline, +$1,134.81.  Value of rule = baseline - reverted.
Meaningfully positive => the rule earns its keep. Near-zero/negative => it was a
biased-sim artifact and should be reverted. Scratch output only.
"""
import os, sys, glob, json, time, contextlib

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1

WIN_START, WIN_END = "2026-03-02", "2026-05-21"
BASELINE = 1134.81

dates = sorted(os.path.basename(f)[:-5]
               for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json")))
dates = [d for d in dates if WIN_START <= d <= WIN_END]
print(f"{len(dates)} dates {dates[0]} -> {dates[-1]}", flush=True)

# shipped (current) constant values — restored before every config
SHIPPED = {
    "ALLOC_PCT_BULL": {"TAKE": 0.50, "MAYBE": 0.20},
    "ALLOC_PCT_NEUT": {"TAKE": 0.45, "MAYBE": 0.15},
    "ALLOC_PCT_BEAR": {"TAKE": 0.10, "MAYBE": 0.10},
    "ORB_MAYBE_EARLY_CUTOFF": "09:50",
    "SPY_GAP_ORB_MAYBE_SKIP": -0.3,
}
def apply_shipped():
    for k, v in SHIPPED.items():
        setattr(ex1, k, dict(v) if isinstance(v, dict) else v)

def revert_alloc():        # TAKE sizing back to pre-2026-05-09 (35% BULL / 30% NEUT)
    ex1.ALLOC_PCT_BULL = {"TAKE": 0.35, "MAYBE": 0.20}
    ex1.ALLOC_PCT_NEUT = {"TAKE": 0.30, "MAYBE": 0.15}
def revert_pre0950():      # disable the pre-09:50 ORB-MAYBE block
    ex1.ORB_MAYBE_EARLY_CUTOFF = "09:30"
def revert_spygap():       # disable the SPY-gap<=-0.3% ORB-MAYBE skip
    ex1.SPY_GAP_ORB_MAYBE_SKIP = -99.0

CONFIGS = [
    ("TAKE allocations reverted to 35/30", "scratch_reval_alloc.json",   revert_alloc),
    ("pre-09:50 ORB-MAYBE block OFF",      "scratch_reval_pre0950.json", revert_pre0950),
    ("SPY-gap <=-0.3% MAYBE skip OFF",     "scratch_reval_spygap.json",  revert_spygap),
]

results = {}
for name, scratch, revert in CONFIGS:
    apply_shipped()
    revert()
    spath = os.path.join(SIGNAL_DIR, scratch)
    if os.path.exists(spath):
        os.remove(spath)
    print(f"\n=== {name}  ->  {scratch} ===", flush=True)
    for i, d in enumerate(dates, 1):
        try:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                ex = ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=scratch)
            print(f"  [{i:2}/{len(dates)}] {d}  P&L=${ex['total_pnl']:+8.2f}  "
                  f"wallet=${ex['portfolio_eod']:,.2f}", flush=True)
        except Exception as e:
            print(f"  [{i:2}/{len(dates)}] {d}  ERROR: {e!r}", flush=True)
        time.sleep(1.5)
    data = [e for e in json.load(open(spath)) if "Exercise 1" in e["title"]]
    results[name] = sum(e["total_pnl"] for e in data)
    print(f"  total = ${results[name]:+,.2f}", flush=True)

apply_shipped()   # leave the ex1 module in its shipped state

print("\n" + "=" * 70)
print("RE-VALIDATION B1 — constant-driven shipped rules (57-day fixed sim)")
print(f"All-rules-ON baseline: ${BASELINE:+,.2f}")
print("-" * 70)
for name, total in results.items():
    value = BASELINE - total
    tag = "REAL — keep" if value >= 25 else ("ARTIFACT — revert?" if value <= 0 else "marginal")
    print(f"  {name}")
    print(f"    rule OFF total ${total:+,.2f}   |   value of rule ${value:+,.2f}   [{tag}]")
print("=" * 70)
