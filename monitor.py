#!/usr/bin/env python3
"""
monitor.py — continuous intraday signal scanner
Polls all tickers every 5 minutes during market hours.
Prints new TAKE/MAYBE signals as they appear.

Usage: python3 monitor.py
"""

import time
from datetime import datetime
import pytz
from alpaca.data.historical import StockHistoricalDataClient

from fetch_data import fetch, _load_creds, detect_signals, TICKERS

ET           = pytz.timezone("America/New_York")
POLL_SECONDS = 300    # 5 minutes
MIN_TIME     = "11:00"  # ignore morning noise — ex1/ex2 already covers the open
COOLDOWN_MIN = 30     # don't re-alert same ticker within this many minutes


def market_open():
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.strftime("%H:%M")
    return "09:30" <= t <= "16:00"


def _vol_ratio(reason_str):
    """Parse the volume ratio float out of a reason string like '3.5x avg volume'."""
    for part in reason_str.split(","):
        part = part.strip()
        if part.endswith("x avg volume"):
            try:
                return float(part.split("x")[0])
            except ValueError:
                pass
    return 0.0


def scan(client, seen, last_alerted):
    """Fetch all tickers and return new TAKE-rated UP signals after MIN_TIME."""
    today  = datetime.now(ET).strftime("%Y-%m-%d")
    now_hm = datetime.now(ET).strftime("%H:%M")
    alerts = []

    for ticker in TICKERS:
        asset = fetch(ticker, client)
        if not asset:
            continue
        for sig in detect_signals(asset, date_filter=today):
            key = f"{ticker}|{sig['ts']}"
            if key in seen:
                continue
            seen.add(key)

            sig_time = sig["date"][11:16]

            # Only TAKE-rated UP signals after the morning window
            if sig["rating"] != "TAKE":
                continue
            if sig["direction"] != "UP":
                continue
            if sig_time < MIN_TIME:
                continue

            # Cooldown: skip if same ticker alerted within COOLDOWN_MIN minutes
            last = last_alerted.get(ticker)
            if last and (datetime.now(ET) - last).seconds < COOLDOWN_MIN * 60:
                continue

            vol = _vol_ratio(sig["reason"])
            last_alerted[ticker] = datetime.now(ET)
            alerts.append({
                "ticker": ticker,
                "time":   sig_time,
                "price":  sig["price"],
                "dir":    sig["direction"],
                "reason": sig["reason"],
                "rating": sig["rating"],
                "vol":    vol,
            })

    return alerts


def print_alert(a, now_str):
    print(f"[{now_str}] ** LATE SIGNAL **  {a['ticker']:<5}  UP  @ ${a['price']:.2f}  "
          f"signal@{a['time']}  |  {a['reason']}")


def main():
    key, secret = _load_creds()
    client = StockHistoricalDataClient(api_key=key, secret_key=secret)
    seen         = set()
    last_alerted = {}

    print(f"Monitor started — watching {len(TICKERS)} tickers every {POLL_SECONDS // 60} min")
    print(f"Alerting on: TAKE-rated UP signals after {MIN_TIME}, {COOLDOWN_MIN}min cooldown per ticker")
    print(f"Tickers: {', '.join(TICKERS)}\n")

    # Seed with existing signals so we don't replay history on startup
    print("Seeding existing signals...")
    scan(client, seen, last_alerted)
    last_alerted.clear()  # don't let seed set cooldown timers
    print(f"  {len(seen)} existing bars suppressed. Watching for new ones...\n")

    while True:
        if not market_open():
            now_str = datetime.now(ET).strftime("%H:%M")
            print(f"[{now_str}] Market closed — checking again in 60s")
            time.sleep(60)
            continue

        now_str = datetime.now(ET).strftime("%H:%M:%S")
        alerts  = scan(client, seen, last_alerted)

        if alerts:
            for a in alerts:
                print_alert(a, now_str)
        else:
            print(f"[{now_str}] No new signals")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
