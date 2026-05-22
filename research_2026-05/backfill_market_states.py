#!/usr/bin/env python3
"""Backfill market_states_historical.json for 2026-05-07..05-21.

market_states_historical.json went stale at 2026-05-06, so every sim re-run
since has defaulted the last 11 trading days to NEUT/gap-0.0. This recomputes
the real SPY gap % and VIXY trend % for those days using market_check.py's
EXACT live formula (run() function reused directly — no re-implementation), so
there is zero risk of formula drift.

market_check.run() writes market_state.json as a side effect. To avoid
clobbering the LIVE file mid-trading-day, market_check.BASE_DIR is repointed at
a temp dir (with a copy of .env) before any call — all its writes land there.
The live market_state.json is never touched.

Backs up market_states_historical.json before merging. Run once.
"""
import os, sys, json, glob, shutil, tempfile, time
from datetime import datetime

SIGNAL_DIR = "/home/ben/Signal"
sys.path.insert(0, SIGNAL_DIR)

HIST = os.path.join(SIGNAL_DIR, "market_states_historical.json")

# --- dates needing a backfill --------------------------------------------
cache_dates = sorted(os.path.basename(f)[:-5]
                     for f in glob.glob(os.path.join(SIGNAL_DIR, "data_cache", "2026-*.json")))
window = [d for d in cache_dates if "2026-03-02" <= d <= "2026-05-21"]
hist = json.load(open(HIST))
have = {e["date"] for e in hist}
missing = [d for d in window if d not in have]
print(f"{len(missing)} dates to backfill: {missing}\n")

# --- redirect market_check's file I/O into a throwaway temp dir ----------
tmp = tempfile.mkdtemp(prefix="mc_backfill_")
shutil.copy(os.path.join(SIGNAL_DIR, ".env"), os.path.join(tmp, ".env"))
import market_check
market_check.BASE_DIR = tmp          # run() now writes tmp/market_state.json
print(f"market_check output redirected to {tmp} (live market_state.json untouched)\n")

# --- compute each missing date ------------------------------------------
new_entries = []
for d in missing:
    r = market_check.run(d)
    new_entries.append({
        "date": d,
        "spy_gap_pct": r["spy_gap_pct"],
        "vixy_trend_pct": r["vixy_trend_pct"],
    })
    print(f"  -> {d}  spy_gap={r['spy_gap_pct']:+.3f}%  vixy={r['vixy_trend_pct']:+.3f}%  "
          f"state={r['state'].upper()}\n")
    time.sleep(1.0)

shutil.rmtree(tmp, ignore_errors=True)

# --- cross-check 05-20 / 05-21 against the live exercises.json record ----
print("=" * 64)
print("CROSS-CHECK vs exercises.json live record (05-20 / 05-21):")
ex = json.load(open(os.path.join(SIGNAL_DIR, "exercises.json")))
exmap = {e["date"]: e for e in ex if "Exercise 1" in e.get("title", "")}
for d in ("2026-05-20", "2026-05-21"):
    comp = next(e for e in new_entries if e["date"] == d)
    live = exmap.get(d, {})
    print(f"  {d}  computed gap={comp['spy_gap_pct']:+.3f}  vixy={comp['vixy_trend_pct']:+.3f}"
          f"   |  exercises.json gap={live.get('spy_gap_pct')}  vixy={live.get('vixy_trend_pct')}")
print("=" * 64)

# --- back up, merge, write ----------------------------------------------
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = os.path.join(SIGNAL_DIR, "backups", f"market_states_historical.json.pre-backfill-{stamp}")
os.makedirs(os.path.dirname(backup), exist_ok=True)
shutil.copy(HIST, backup)
print(f"\nbacked up original -> {backup}")

merged = sorted(hist + new_entries, key=lambda e: e["date"])
with open(HIST, "w") as f:
    json.dump(merged, f, indent=2)
print(f"market_states_historical.json: {len(hist)} -> {len(merged)} entries  "
      f"(last date now {merged[-1]['date']})")
