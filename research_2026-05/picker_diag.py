#!/usr/bin/env python3
"""Diagnose the walk-forward picker run — where is the +$0.86/trade edge weak
vs strong? Points to the improvement lever before any tuning.

Reads the monthly picks from picker_wf.log and the trades from
scratch_picker_wf.json. Key question: is the picker's RANK informative —
do rank 1-5 names beat rank 11-15? If so, trading fewer/higher-ranked names
lifts the edge for free. Splits everything in-sample vs out-of-sample.
"""
import os, re, json
from collections import defaultdict

SIGNAL_DIR = "/home/ben/Signal"
IS_START = "2026-03-02"

# --- monthly picks from the walk-forward log -----------------------------
picks = {}
for line in open(os.path.join(SIGNAL_DIR, "research_2026-05/picker_wf.log")):
    m = re.match(r"\s+(\d{4}-\d{2}):\s+(\[.*\])\s*$", line)
    if m:
        picks[m.group(1)] = [t.strip(" '\"") for t in m.group(2).strip("[]").split(",")]
print(f"parsed picks for {len(picks)} months")

rank = {}                                  # (month, ticker) -> 1-based rank
for mo, lst in picks.items():
    for i, t in enumerate(lst, 1):
        rank[(mo, t)] = i

# --- trades --------------------------------------------------------------
entries = [x for x in json.load(open(os.path.join(SIGNAL_DIR, "scratch_picker_wf.json")))
           if "Exercise 1" in x["title"]]
trades = []
for e in entries:
    for t in (e.get("trades") or []):
        t = dict(t)
        t["_date"] = e["date"]
        t["_rank"] = rank.get((e["date"][:7], t["ticker"]))
        trades.append(t)


def stats(rows):
    if not rows:
        return "  n=0"
    w = [r for r in rows if r["pnl"] > 0]
    tot = sum(r["pnl"] for r in rows)
    return (f"  n={len(rows):4}  WR={100*len(w)/len(rows):3.0f}%  "
            f"total=${tot:+9.2f}  exp=${tot/len(rows):+6.2f}/tr")


def section(title, key_fn, buckets):
    print(f"\n=== {title} ===")
    for label, pred in buckets:
        allr = [t for t in trades if pred(t)]
        oos = [t for t in allr if t["_date"] < IS_START]
        print(f"{label:18} ALL{stats(allr)}")
        print(f"{'':18} OOS{stats(oos)}")


print(f"\ntotal trades: {len(trades)}")
section("by PICKER RANK", None, [
    ("rank 1-5",   lambda t: t["_rank"] and t["_rank"] <= 5),
    ("rank 6-10",  lambda t: t["_rank"] and 6 <= t["_rank"] <= 10),
    ("rank 11-15", lambda t: t["_rank"] and t["_rank"] >= 11),
])
section("by RATING", None, [
    ("TAKE",  lambda t: t["rating"] == "TAKE"),
    ("MAYBE", lambda t: t["rating"] == "MAYBE"),
])
section("by SIGNAL", None, [
    ("ORB",    lambda t: t["signal"] == "ORB"),
    ("GAP_GO", lambda t: t["signal"] == "GAP_GO"),
])
reasons = sorted({t["exit_reason"] for t in trades})
section("by EXIT REASON", None, [(r, (lambda r: lambda t: t["exit_reason"] == r)(r)) for r in reasons])
