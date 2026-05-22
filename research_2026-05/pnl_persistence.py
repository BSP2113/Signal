"""Does a stock's recent sim P&L predict its near-future sim P&L?
First read, using the validated baseline (17 curated tickers, 57 days). READ-ONLY."""
import json
import pandas as pd

T17 = ["NVDA","TSLA","AMD","COIN","META","PLTR","SMCI","CRDO","IONQ",
       "SNDK","DELL","KOPN","SHOP","ASTS","ARM","DKNG","UPST"]
LIVE = "2026-04-13"

ex = sorted([e for e in json.load(open('/home/ben/Signal/scratch_baseline_5821.json'))
             if 'Exercise 1' in e['title']], key=lambda e: e['date'])
dates = [e['date'] for e in ex]
pnl = pd.DataFrame(0.0, index=dates, columns=T17)
cnt = pd.DataFrame(0,   index=dates, columns=T17)
for e in ex:
    for t in e['trades']:
        tk = t['ticker']
        if tk in T17:
            pnl.loc[e['date'], tk] += t['pnl']
            cnt.loc[e['date'], tk] += 1

def split_report(rows1, rows2, label):
    df = pd.DataFrame({'P1': pnl.loc[rows1].sum(), 'P2': pnl.loc[rows2].sum(),
                       'n1': cnt.loc[rows1].sum(), 'n2': cnt.loc[rows2].sum()})
    df = df[(df.n1 >= 1) & (df.n2 >= 1)]              # active in both periods
    rho  = df['P1'].rank().corr(df['P2'].rank())   # Spearman = Pearson on ranks
    same = ((df.P1 > 0) == (df.P2 > 0)).mean()
    print(f"\n=== {label} ===  ({len(df)} tickers active in both)")
    print(f"  Spearman rank corr (period-1 P&L vs period-2 P&L): {rho:+.2f}")
    print(f"  Sign persistence (profit/loss direction held):     {same*100:.0f}%")
    print(f"  {'ticker':<8}{'period 1':>11}{'period 2':>11}")
    for tk, r in df.sort_values('P1', ascending=False).iterrows():
        flag = "" if (r.P1 > 0) == (r.P2 > 0) else "   <- flipped"
        print(f"  {tk:<8}{r.P1:>+11.2f}{r.P2:>+11.2f}{flag}")
    return rho

bf = [d for d in dates if d <  LIVE]
lv = [d for d in dates if d >= LIVE]
split_report(bf, lv, "SPLIT A: backfill (Mar) -> live (Apr-May)")
mid = len(lv) // 2
split_report(lv[:mid], lv[mid:], "SPLIT B: live 1st-half -> live 2nd-half")

# rolling: trailing-15 trade-days vs forward-10
pairs = []
for tk in T17:
    p, c = pnl[tk].values, cnt[tk].values
    for i in range(15, len(p) - 10):
        if c[i-15:i].sum() >= 3:                      # real trailing signal only
            pairs.append((p[i-15:i].sum(), p[i:i+10].sum()))
roll = pd.DataFrame(pairs, columns=['trail', 'fwd'])
print(f"\n=== ROLLING: trailing-15d P&L -> forward-10d P&L ===")
print(f"  {len(roll)} observations (ticker traded >=3x in the trailing window)")
print(f"  Spearman: {roll.trail.rank().corr(roll.fwd.rank()):+.2f}    "
      f"Pearson: {roll.trail.corr(roll.fwd):+.2f}")
