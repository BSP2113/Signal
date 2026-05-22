#!/usr/bin/env python3
"""Pick-count (N) sweep — edge-improvement test: trade fewer, higher-ranked picks.

picker_diag.py showed the picker's RANK is strongly informative and holds out
of sample (rank 1-5 +$2.29/tr OOS, rank 11-15 -$0.47/tr OOS). Trimming the pick
count should lift the edge. This re-runs the walk-forward sim for several N,
reusing the SAME monthly ranked picks truncated to top-N — the picker is not
re-fetched, only the traded universe shrinks.

Full chronological sim per N (no first-order shortcut). N=15 must reproduce
picker_walkforward.py's +$735. Scratch output only — exercises.json untouched.
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
print(f"parsed picks for {len(picks)} months", flush=True)

all_dates = sorted(e["date"] for e in
                   json.load(open(os.path.join(SIGNAL_DIR, "market_states_historical.json"))))
all_dates = [d for d in all_dates if WIN_START <= d <= WIN_END]
months = sorted(picks)

ex1.TICKER_START = {}
N_VALUES = [5, 8, 10, 12, 15]
results = {}


def slc(ents):
    tr = [t for e in ents for t in (e.get("trades") or [])]
    w = [t for t in tr if t["pnl"] > 0]
    return (len(ents), len(tr),
            100 * len(w) / len(tr) if tr else 0,
            sum(e["total_pnl"] for e in ents))


for N in N_VALUES:
    scratch = os.path.join(SIGNAL_DIR, f"scratch_nsweep_{N}.json")
    if os.path.exists(scratch):
        os.remove(scratch)
    print(f"\n=== N={N} ===", flush=True)
    for mo in months:
        if not picks.get(mo):
            continue
        ex1.TICKERS = picks[mo][:N]
        for d in [x for x in all_dates if x.startswith(mo)]:
            try:
                with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                    ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=scratch)
            except Exception as err:
                print(f"  {d}  ERROR {err!r}", flush=True)
            time.sleep(0.8)
    ents = [x for x in json.load(open(scratch)) if "Exercise 1" in x["title"]]
    results[N] = dict(full=slc(ents),
                      oos=slc([e for e in ents if e["date"] < IS_START]),
                      ins=slc([e for e in ents if e["date"] >= IS_START]))
    f, o = results[N]["full"], results[N]["oos"]
    print(f"  full ${f[3]:+,.2f} ({f[1]}tr {f[2]:.0f}%)  |  "
          f"OOS ${o[3]:+,.2f} ({o[1]}tr {o[2]:.0f}%)", flush=True)

print("\n" + "=" * 74)
print("PICK-COUNT (N) SWEEP — walk-forward, dynamic picker")
print(f"{'N':>4}{'full total':>14}{'full WR':>9}{'OOS total':>13}{'OOS WR':>8}{'OOS $/tr':>10}")
print("-" * 74)
for N in N_VALUES:
    f, o = results[N]["full"], results[N]["oos"]
    print(f"{N:>4}{f[3]:>+14,.2f}{f[2]:>8.0f}%{o[3]:>+13,.2f}{o[2]:>7.0f}%"
          f"{(o[3]/o[1] if o[1] else 0):>+10.2f}")
print("-" * 74)
print(f"N=15 sanity: ${results[15]['full'][3]:+,.2f}  (expect ~+$735)")
print("=" * 74)
