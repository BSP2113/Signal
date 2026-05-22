"""Test the two uncommitted picker-short fixes before committing.
1. data.py  _drop_partial_today  — drops today's half-built bar before 4pm ET
2. score.py _momentum_score      — volume-surge baseline excludes the spike days
Plus a real-data smoke test of the whole pipeline (no save_results).
"""
import sys, datetime as real_dt
sys.path.insert(0, "/home/ben/picker-short")

import pandas as pd
import screener.data as data_mod
from screener.score import _momentum_score, score_tickers
from screener.data import fetch_and_filter

passed = []
failed = []
def check(name, cond):
    (passed if cond else failed).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")

# ---------------------------------------------------------------------------
print("\n[1] data.py  _drop_partial_today  (clock monkeypatched)")

class FakeDT:
    fixed = None
    @classmethod
    def now(cls, tz=None):
        return cls.fixed
data_mod.datetime = FakeDT   # the function reads the module global

def make_df(last_date, n=12):
    idx = pd.date_range(end=last_date, periods=n, freq="D")
    return pd.DataFrame({"Close": range(n), "Volume": range(n)}, index=idx)

# before 4pm, last bar IS today  -> drop it
FakeDT.fixed = real_dt.datetime(2026, 5, 21, 10, 0)
df = make_df("2026-05-21")
out = data_mod._drop_partial_today(df)
check("before 4pm + today's bar -> dropped", len(out) == len(df) - 1)

# after 4pm, last bar IS today  -> keep it
FakeDT.fixed = real_dt.datetime(2026, 5, 21, 18, 0)
out = data_mod._drop_partial_today(df)
check("after 4pm + today's bar -> kept", len(out) == len(df))

# before 4pm, last bar is OLD (e.g. ran on a holiday) -> keep it
FakeDT.fixed = real_dt.datetime(2026, 5, 21, 10, 0)
df_old = make_df("2026-05-20")
out = data_mod._drop_partial_today(df_old)
check("before 4pm + stale bar -> kept", len(out) == len(df_old))

# empty df -> no crash
out = data_mod._drop_partial_today(pd.DataFrame())
check("empty df -> no crash", len(out) == 0)

# ---------------------------------------------------------------------------
print("\n[2] score.py  _momentum_score  volume-surge fix")

# Build a ticker whose Close == SPY's Close exactly, so rs5 = rs10 = 0.
# Then rs5_score = rs10_score = 20 each, and vol_score = total - 40.
n = 30
idx = pd.date_range(end="2026-05-20", periods=n, freq="D")
spy = pd.DataFrame({"Close": [100.0] * n}, index=idx)
vol = [1_000_000] * (n - 5) + [1_800_000] * 5   # mild spike in the last 5 days
tk  = pd.DataFrame({"Close": [100.0] * n, "Volume": vol}, index=idx)

total, rs5, rs10 = _momentum_score(tk, spy)
vol_score = total - 40.0          # strip the two RS components (20 + 20)
vol_ratio = vol_score / 20 * 2    # invert vol_score = min(ratio/2,1)*20

new_expected = 1_800_000 / 1_000_000                       # baseline = pre-spike days
old_formula  = 1_800_000 / (sum(vol) / n)                  # baseline = whole window

print(f"  rs5={rs5:.2f}  rs10={rs10:.2f}  (both should be 0.0)")
print(f"  measured vol_ratio = {vol_ratio:.3f}")
print(f"  new formula        = {new_expected:.3f}  <- code now uses this")
print(f"  old formula        = {old_formula:.3f}  <- spike was self-diluted")
check("rs components are zero (clean isolation)", abs(rs5) < 1e-6 and abs(rs10) < 1e-6)
check("vol_ratio matches NEW formula", abs(vol_ratio - new_expected) < 1e-6)
check("NEW formula reports a bigger surge than OLD", new_expected > old_formula)

# ---------------------------------------------------------------------------
print("\n[3] real-data smoke test  (small sample, no save)")
sample = ["F", "BAC", "PFE", "T", "INTC", "CSCO", "KMI", "WBD"]
data = fetch_and_filter(sample)
results = score_tickers(data)
check("SPY downloaded", "SPY" in data)
check("at least one ticker scored", len(results) > 0)
if len(results) > 0:
    cols = ["ticker", "score", "gaps_30d", "atr_pct", "rs_5d", "avg_vol_M"]
    print(results[cols].to_string())

# ---------------------------------------------------------------------------
print(f"\n{'='*50}")
print(f"  {len(passed)} passed, {len(failed)} failed")
if failed:
    print("  FAILED: " + ", ".join(failed))
    sys.exit(1)
print("  ALL GREEN")
