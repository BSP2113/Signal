"""Per-ticker P&L from the live record (exercises.json, EX1 only). READ-ONLY."""
import json
from collections import defaultdict

CURRENT_17 = ["NVDA","TSLA","AMD","COIN","META","PLTR","SMCI","CRDO","IONQ",
              "SNDK","DELL","KOPN","SHOP","ASTS","ARM","DKNG","UPST"]

data = json.load(open("/home/ben/Signal/exercises.json"))
e1 = sorted([e for e in data if "Exercise 1" in e["title"]], key=lambda e: e["date"])
print(f"exercises.json — {len(e1)} EX1 day-entries, {e1[0]['date']} -> {e1[-1]['date']}\n")

# discover trade-dict keys from a real sample
sample = next((t for e in e1 for t in e.get("trades", [])), None)
print("sample trade keys:", list(sample.keys()))
tkr_key = next(k for k in ("ticker","symbol") if k in sample)
pnl_key = next(k for k in ("pnl","dollar_pnl","profit","pnl_dollars","net_pnl") if k in sample)
print(f"using ticker='{tkr_key}', pnl='{pnl_key}'\n")

agg = defaultdict(lambda: {"pnl":0.0,"n":0,"wins":0,"first":None,"last":None})
for e in e1:
    for t in e.get("trades", []):
        a = agg[t[tkr_key]]
        p = t[pnl_key]
        a["pnl"] += p; a["n"] += 1
        a["wins"] += (p > 0)
        a["first"] = e["date"] if a["first"] is None else min(a["first"], e["date"])
        a["last"]  = e["date"] if a["last"]  is None else max(a["last"],  e["date"])

rows = sorted(agg.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
print(f"{'#':<4}{'TICKER':<8}{'TRADES':>7}{'WINS':>6}{'WR%':>7}{'TOTAL P&L':>12}{'AVG/TRD':>10}   ACTIVE")
print("-" * 78)
for i,(tk,a) in enumerate(rows, 1):
    wr  = a["wins"]/a["n"]*100 if a["n"] else 0
    avg = a["pnl"]/a["n"]      if a["n"] else 0
    print(f"{i:<4}{tk:<8}{a['n']:>7}{a['wins']:>6}{wr:>6.1f}%{a['pnl']:>+12.2f}{avg:>+10.2f}   {a['first']}->{a['last']}")

never = [tk for tk in CURRENT_17 if tk not in agg]
if never:
    print(f"\nIn the 17 but never traded in this window: {', '.join(never)}")
print(f"\nTotal across all tickers: ${sum(a['pnl'] for _,a in rows):+,.2f}")
