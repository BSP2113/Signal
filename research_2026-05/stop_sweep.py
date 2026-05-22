#!/usr/bin/env python3
"""Stop-loss variant sweep — improvement lever #1 (2026-05-22 review).

The clean EX1 record loses $449 across 20 STOP_LOSS exits; 10 of the 20 would
have closed GREEN if held to the close, and all 20 were early entries
(09:31-10:09). Hypothesis: the fixed -1.5% stop whipsaws on the noisy market
open. This sweeps wider-fixed and time-graded stops to see if the morning
false stop-outs can be cut without letting genuine losers run further.

Each variant is a FULL chronological 57-day sim (no first-order shortcuts —
see the first-order-test caveat). V0 reproduces the shipped -1.5% fixed stop
and must match the verified clean ex1.py total of +$1,694.39.
Scratch output only — exercises.json is never touched.
"""
import os, sys, glob, json, time, contextlib

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)
import ex1_stoptest as ex

dates = sorted(os.path.basename(f)[:-5]
               for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json")))
dates = [d for d in dates if "2026-03-02" <= d <= "2026-05-21"]
print(f"{len(dates)} dates {dates[0]} -> {dates[-1]}", flush=True)

VARIANTS = [
    ("V0 baseline -1.5% fixed",       {"mode": "fixed",  "pct": 0.015}),
    ("V1 fixed -2.0%",                {"mode": "fixed",  "pct": 0.020}),
    ("V2 fixed -2.5%",                {"mode": "fixed",  "pct": 0.025}),
    ("V3 graded 10min -2.5%/-1.5%",   {"mode": "graded", "grace": 10, "wide": 0.025, "pct": 0.015}),
    ("V4 graded 15min -2.5%/-1.5%",   {"mode": "graded", "grace": 15, "wide": 0.025, "pct": 0.015}),
    ("V5 graded 20min -2.5%/-1.5%",   {"mode": "graded", "grace": 20, "wide": 0.025, "pct": 0.015}),
    ("V6 graded 15min -3.0%/-1.5%",   {"mode": "graded", "grace": 15, "wide": 0.030, "pct": 0.015}),
]

results = {}
for name, cfg in VARIANTS:
    ex.STOP_CFG = dict(cfg)
    tag = name.split()[0]
    scratch = os.path.join(SIGNAL_DIR, f"scratch_stop_{tag}.json")
    if os.path.exists(scratch):
        os.remove(scratch)
    print(f"\n=== {name} ===", flush=True)
    for i, d in enumerate(dates, 1):
        try:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                ex.run_ex1(trade_date=d, backfill=False, save=True, result_file=scratch)
        except Exception as e:
            print(f"  {d}  ERROR {e!r}", flush=True)
        time.sleep(1.0)
    entries = [x for x in json.load(open(scratch)) if "Exercise 1" in x["title"]]
    trades  = [t for e in entries for t in (e.get("trades") or [])]
    wins    = [t for t in trades if t["pnl"] > 0]
    stops   = [t for t in trades if t["exit_reason"] == "STOP_LOSS"]
    results[name] = dict(
        total   = sum(e["total_pnl"] for e in entries),
        n       = len(trades),
        wr      = 100 * len(wins) / len(trades) if trades else 0,
        worst   = min((e["total_pnl"] for e in entries), default=0.0),
        nstop   = len(stops),
        stoppnl = sum(t["pnl"] for t in stops),
    )
    r = results[name]
    print(f"  total ${r['total']:+,.2f}  WR {r['wr']:.0f}%  worst-day ${r['worst']:+.2f}  "
          f"STOP_LOSS {r['nstop']} (${r['stoppnl']:+.2f})", flush=True)

base = results["V0 baseline -1.5% fixed"]
print("\n" + "=" * 80)
print("STOP-LOSS VARIANT SWEEP — 57-day clean sim")
print(f"{'variant':30}{'total':>12}{'vs base':>10}{'WR':>6}{'worst-day':>11}{'STOP_LOSS':>16}")
print("-" * 80)
for name, _ in VARIANTS:
    r = results[name]
    print(f"{name:30}{r['total']:>+12,.2f}{r['total']-base['total']:>+10.2f}"
          f"{r['wr']:>5.0f}%{r['worst']:>+11.2f}{r['nstop']:>6} (${r['stoppnl']:>+8.2f})")
print("-" * 80)
sane = abs(base["total"] - 1694.39) < 5
print(f"V0 sanity: ${base['total']:+,.2f}  (expect +$1,694.39)  "
      f"[{'OK' if sane else '** MISMATCH — harness not faithful **'}]")
print("=" * 80)
