#!/usr/bin/env python3
"""Conviction-weighted allocation sweep — last edge-improvement tweak.

picker_diag.py showed TAKE +$3.24/tr OOS vs MAYBE +$0.20/tr — a 16x per-trade
gap. This shifts allocation toward TAKE and away from MAYBE while keeping
everything else fixed (picker top-15, -2% stop, all reverts). Critically: it
RESIZES trades rather than cutting them, so it should dodge the first-order
trap that killed pick-count.

Reuses the saved monthly picks. V0 (baseline) must reproduce +$735.
Scratch output only — exercises.json untouched.
"""
import os, sys, re, json, time, contextlib

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1

IS_START = "2026-03-02"
WIN_START, WIN_END = "2025-09-02", "2026-05-21"

picks = {}
for line in open(os.path.join(SIGNAL_DIR, "research_2026-05/picker_wf.log")):
    m = re.match(r"\s+(\d{4}-\d{2}):\s+(\[.*\])\s*$", line)
    if m:
        picks[m.group(1)] = [t.strip(" '\"") for t in m.group(2).strip("[]").split(",")]

all_dates = sorted(e["date"] for e in
                   json.load(open(os.path.join(SIGNAL_DIR, "market_states_historical.json"))))
all_dates = [d for d in all_dates if WIN_START <= d <= WIN_END]
months = sorted(picks)
ex1.TICKER_START = {}

VARIANTS = [
    ("V0 baseline           50/20 45/15 10/10",
     {"BULL": {"TAKE": 0.50, "MAYBE": 0.20},
      "NEUT": {"TAKE": 0.45, "MAYBE": 0.15},
      "BEAR": {"TAKE": 0.10, "MAYBE": 0.10}}),
    ("V1 modest TAKE-shift  55/15 50/10 15/5",
     {"BULL": {"TAKE": 0.55, "MAYBE": 0.15},
      "NEUT": {"TAKE": 0.50, "MAYBE": 0.10},
      "BEAR": {"TAKE": 0.15, "MAYBE": 0.05}}),
    ("V2 strong TAKE-shift  60/10 55/8  20/5",
     {"BULL": {"TAKE": 0.60, "MAYBE": 0.10},
      "NEUT": {"TAKE": 0.55, "MAYBE": 0.08},
      "BEAR": {"TAKE": 0.20, "MAYBE": 0.05}}),
]


def slc(ents):
    tr = [t for e in ents for t in (e.get("trades") or [])]
    w = [t for t in tr if t["pnl"] > 0]
    return (len(ents), len(tr),
            100 * len(w) / len(tr) if tr else 0,
            sum(e["total_pnl"] for e in ents))


results = {}
for name, allocs in VARIANTS:
    ex1.ALLOC_PCT_BULL = dict(allocs["BULL"])
    ex1.ALLOC_PCT_NEUT = dict(allocs["NEUT"])
    ex1.ALLOC_PCT_BEAR = dict(allocs["BEAR"])
    tag = name.split()[0]
    scratch = os.path.join(SIGNAL_DIR, f"scratch_allocsweep_{tag}.json")
    if os.path.exists(scratch):
        os.remove(scratch)
    print(f"\n=== {name} ===", flush=True)
    for mo in months:
        ex1.TICKERS = picks[mo][:15]
        for d in [x for x in all_dates if x.startswith(mo)]:
            try:
                with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                    ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=scratch)
            except Exception as err:
                print(f"  {d}  ERROR {err!r}", flush=True)
            time.sleep(0.8)
    ents = [x for x in json.load(open(scratch)) if "Exercise 1" in x["title"]]
    results[name] = dict(full=slc(ents), oos=slc([e for e in ents if e["date"] < IS_START]))
    f, o = results[name]["full"], results[name]["oos"]
    print(f"  full ${f[3]:+,.2f} ({f[1]}tr {f[2]:.0f}%)  |  "
          f"OOS ${o[3]:+,.2f} ({o[1]}tr {o[2]:.0f}%)", flush=True)

print("\n" + "=" * 86)
print("CONVICTION-WEIGHTED ALLOC SWEEP — walk-forward (picker top-15, -2% stop)")
print(f"{'variant':42}{'full total':>13}{'full WR':>9}{'OOS total':>13}{'OOS WR':>8}")
print("-" * 86)
for name, _ in VARIANTS:
    f, o = results[name]["full"], results[name]["oos"]
    print(f"{name:42}{f[3]:>+13,.2f}{f[2]:>8.0f}%{o[3]:>+13,.2f}{o[2]:>7.0f}%")
print("-" * 86)
base = results["V0 baseline           50/20 45/15 10/10"]["full"][3]
print(f"V0 sanity: ${base:+,.2f}  (expect ~+$735)")
print("=" * 86)
