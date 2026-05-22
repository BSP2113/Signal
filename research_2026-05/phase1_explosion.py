"""Phase 1 — What does a pre-explosion stock look like?

Labels 'explosion' days (big, clean, followed-through up-moves) across the
universe, then checks whether pre-event chart features separate them from
normal days. Daily-bar first pass. READ-ONLY on the cached daily history.

Features (all measured as of today's close — no lookahead):
  compression  <1 = daily range contracting (coiled spring)
  quietness    higher = flatter recent 10-day move (quiet before the storm)
  vol_drift    >1 = volume building over the last 5 days
  prox_high    ~1 = sitting just under its 20-day high (coiled at resistance)
Target: did the stock 'explode' on any of the NEXT 5 trading days?
"""
import pickle
import numpy as np
import pandas as pd

with open('/tmp/rotation_daily_5821.pkl', 'rb') as f:
    df = pickle.load(f)
df['Date'] = pd.to_datetime(df['Date'], utc=True).dt.tz_localize(None)
df = df.sort_values(['ticker', 'Date'])

recs = []
for tk, g in df.groupby('ticker', sort=False):
    g = g.reset_index(drop=True)
    if len(g) < 45:
        continue
    c, h, l, v = g.Close, g.High, g.Low, g.Volume
    prev      = c.shift(1)
    ret       = c / prev - 1
    rng       = (h - l) / prev
    close_pos = (c - l) / (h - l).replace(0, np.nan)
    explo     = ((ret >= 0.04) & (close_pos >= 0.65)).astype(float)   # big clean up day

    roll5  = rng.rolling(5).mean()
    vroll5 = v.rolling(5).mean()
    feat = pd.DataFrame({
        'ticker'      : tk,
        'price'       : c,
        'avgvol20'    : v.rolling(20).mean(),
        'compression' : roll5 / roll5.shift(5),
        'quietness'   : -(c / c.shift(10) - 1).abs(),
        'vol_drift'   : vroll5 / vroll5.shift(5),
        'prox_high'   : c / h.rolling(20).max(),
    })
    feat['exploded_5d'] = pd.concat([explo.shift(-k) for k in range(1, 6)],
                                    axis=1).max(axis=1)
    recs.append(feat)

A = pd.concat(recs, ignore_index=True)
A = A[(A.avgvol20 >= 1e6) & (A.price >= 2.0)]                         # liquid real stocks
A = A.dropna(subset=['compression', 'quietness', 'vol_drift', 'prox_high', 'exploded_5d'])

base = A['exploded_5d'].mean()
print(f"Ticker-days analysed : {len(A):,}")
print(f"Base rate (explosion within next 5 trading days): {base*100:.1f}%\n")

for feat in ['compression', 'quietness', 'vol_drift', 'prox_high']:
    q    = pd.qcut(A[feat], 5, labels=['Q1 low', 'Q2', 'Q3', 'Q4', 'Q5 high'],
                   duplicates='drop')
    rate = A.groupby(q, observed=True)['exploded_5d'].mean() * 100
    print(f"{feat}  — explosion rate by quintile:")
    for k in rate.index:
        print(f"   {k:<9} {rate[k]:5.1f}%   ({rate[k]/(base*100):.2f}x base)")
    print()
