#!/usr/bin/env python3
"""Extended-window sim — improvement lever #2 (2026-05-22 review).

Runs the current post-revert ex1.py (-2.0% stop) over 2025-09-02..2026-05-21
to test whether the edge holds OUT OF SAMPLE. The system was tuned on
2026-03..05; 2025-09..2026-02 is unseen data. If the edge survives there,
it's real; if it collapses, the spring result was overfit/fluke.

Survivorship caveat: today's 17 tickers were partly curated on recent
performance. TICKER_START gates the 5 recent adds, so 2025 dates trade only
the 12 long-standing tickers — the out-of-sample edge here is still mildly
optimistic. Scratch output only — exercises.json untouched.
"""
import os, sys, json, time, contextlib
from collections import defaultdict

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1

WIN_START, WIN_END = "2025-09-02", "2026-05-21"
IS_START = "2026-03-02"   # in-sample (tuned) period begins here

dates = sorted(e["date"] for e in
               json.load(open(os.path.join(SIGNAL_DIR, "market_states_historical.json"))))
dates = [d for d in dates if WIN_START <= d <= WIN_END]
print(f"{len(dates)} dates {dates[0]}..{dates[-1]}", flush=True)

scratch = os.path.join(SIGNAL_DIR, "scratch_extended.json")
if os.path.exists(scratch):
    os.remove(scratch)

for i, d in enumerate(dates, 1):
    try:
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            e = ex1.run_ex1(trade_date=d, backfill=False, save=True, result_file=scratch)
        print(f"  [{i:3}/{len(dates)}] {d}  P&L ${e['total_pnl']:+8.2f}  "
              f"wallet ${e['portfolio_eod']:,.2f}", flush=True)
    except Exception as err:
        print(f"  [{i:3}/{len(dates)}] {d}  ERROR {err!r}", flush=True)
    time.sleep(1.0)

entries = [x for x in json.load(open(scratch)) if "Exercise 1" in x["title"]]


def report(label, ents):
    if not ents:
        print(f"{label}\n  (no data)")
        return
    trades = [t for e in ents for t in (e.get("trades") or [])]
    w = [t for t in trades if t["pnl"] > 0]
    l = [t for t in trades if t["pnl"] <= 0]
    days = [e["total_pnl"] for e in ents]
    wr = 100 * len(w) / len(trades) if trades else 0
    aw = sum(t["pnl"] for t in w) / len(w) if w else 0
    al = sum(t["pnl"] for t in l) / len(l) if l else 0
    exp = (wr / 100) * aw + (1 - wr / 100) * al
    print(f"{label}")
    print(f"  {len(ents)} days | {len(trades)} trades | WR {wr:.0f}% | total ${sum(days):+,.2f}")
    print(f"  avgW ${aw:+.2f} | avgL ${al:+.2f} | expectancy ${exp:+.2f}/trade | "
          f"worst day ${min(days):+.2f}")


print("\n" + "=" * 72)
print("EXTENDED-WINDOW SIM — does the edge hold out of sample?")
report("FULL  2025-09 .. 2026-05", entries)
print()
report("OUT-OF-SAMPLE  2025-09 .. 2026-02 (unseen)", [e for e in entries if e["date"] < IS_START])
print()
report("IN-SAMPLE  2026-03 .. 2026-05 (tuned on this)", [e for e in entries if e["date"] >= IS_START])
print()
print("by MARKET STATE (whole window):")
byms = defaultdict(list)
for e in entries:
    for t in (e.get("trades") or []):
        byms[t.get("spy_state", "?")].append(t)
for ms in ("bullish", "neutral", "bearish"):
    rows = byms.get(ms, [])
    if rows:
        w = [t for t in rows if t["pnl"] > 0]
        print(f"  {ms:8} {len(rows):4} trades  WR {100*len(w)/len(rows):3.0f}%  "
              f"total ${sum(t['pnl'] for t in rows):+9.2f}")
print()
print("by MONTH:")
bymo = defaultdict(list)
for e in entries:
    bymo[e["date"][:7]].append(e["total_pnl"])
for mo in sorted(bymo):
    v = bymo[mo]
    print(f"  {mo}  {len(v):2}d  ${sum(v):+9.2f}")
print("=" * 72)
