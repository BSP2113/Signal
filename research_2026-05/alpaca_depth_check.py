"""Verify Alpaca free IEX minute-data depth and on-the-fly ticker fetch.
Read-only data requests — no trades, no cost."""
import os
from datetime import datetime, timezone, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

BASE = "/home/ben/Signal"
creds = {}
with open(os.path.join(BASE, ".env")) as f:
    for line in f:
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
client = StockHistoricalDataClient(creds["ALPACA_API_KEY"], creds["ALPACA_API_SECRET"])

def probe(ticker, day):
    """Pull 1-min bars for a single trading day, IEX feed — same as ex1.py."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end   = start + timedelta(days=1)
    try:
        bars = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=ticker, timeframe=TimeFrame.Minute,
            start=start, end=end, feed="iex"))
        df = bars.df
        n  = len(df)
        print(f"  {ticker:6s} {day}:  {n:>4} one-min bars  {'OK' if n > 0 else '** EMPTY **'}")
        return n > 0
    except Exception as e:
        print(f"  {ticker:6s} {day}:  ERROR — {e}")
        return False

print("[A] Depth — can we reach the oldest data_cache date (2026-03-02)?")
probe("NVDA", "2026-03-02")        # current ticker, oldest window date
probe("NVDA", "2026-04-13")        # current ticker, exercises.json window start

print("\n[B] On-the-fly — a NON-tracked candidate ticker, historical date?")
probe("UMC",  "2026-03-02")        # picker-short candidate rank 1, not in the 17
probe("STM",  "2026-03-02")        # picker-short candidate rank 3, not in the 17
probe("UMC",  "2026-05-20")        # same candidate, recent date
