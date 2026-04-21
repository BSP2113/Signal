"""
ex1.py — Exercise 1: Buy Only, $1,000

Entry logic:
  Primary   — Opening Range Breakout (ORB): first close above the 9:30–9:44 high
  Secondary — VWAP Cross: price crosses above VWAP after 3+ bars below, with 1.5x+ volume

Run manually:  venv/bin/python3 ex1.py [YYYY-MM-DD]
Cron calls it: venv/bin/python3 ex1.py  (defaults to today)
"""

import yfinance as yf
import json
import os
import sys
from datetime import datetime, timedelta

TICKERS  = ["NVDA", "TSLA", "AMD", "COIN", "META", "PLTR", "MSTR", "SMCI", "NFLX", "HOOD"]
BUDGET   = 1000.0
ALLOC    = {"TAKE": 350.0, "MAYBE": 200.0}
ORB_BARS = 15   # 9:30–9:44 = 15 one-minute bars
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def calc_vwap(highs, lows, closes, volumes):
    cum_tp_vol, cum_vol, result = 0, 0, []
    for h, l, c, v in zip(highs, lows, closes, volumes):
        tp = (h + l + c) / 3
        cum_tp_vol += tp * v
        cum_vol    += v
        result.append(cum_tp_vol / cum_vol if cum_vol else c)
    return result


def score_signal(closes_so_far, vol, avg_volume):
    """Rate a BUY signal TAKE / MAYBE / SKIP."""
    vol_ratio = vol / avg_volume if avg_volume else 0
    if len(closes_so_far) < 2:
        return "SKIP", vol_ratio

    day_open   = closes_so_far[0]
    day_change = (closes_so_far[-1] - day_open) / day_open if day_open else 0

    # Don't buy into a stock already down >2% unless volume is very strong
    if day_change < -0.02 and vol_ratio < 2.0:
        return "SKIP", vol_ratio

    if vol_ratio < 0.5: return "SKIP",  vol_ratio
    if vol_ratio < 1.0: return "MAYBE", vol_ratio

    score  = 1 if vol_ratio >= 1.5 else 0
    recent = closes_so_far[-min(12, len(closes_so_far)):]
    flips  = sum(1 for j in range(1, len(recent) - 1)
                 if (recent[-j] - recent[-j-1]) * (recent[-j-1] - recent[-j-2]) < 0)
    score += 1 if flips < 3 else -1

    if score >= 1:   return "TAKE",  vol_ratio
    elif score == 0: return "MAYBE", vol_ratio
    else:            return "SKIP",  vol_ratio


def find_entry(closes, highs, lows, volumes, times):
    """Return first qualifying entry or None."""
    if len(closes) <= ORB_BARS:
        return None

    avg_vol  = sum(volumes) / len(volumes) if volumes else 1
    vwap     = calc_vwap(highs, lows, closes, volumes)
    orb_high = max(closes[:ORB_BARS])

    # Primary: ORB breakout
    for i in range(ORB_BARS, len(closes)):
        if closes[i] > orb_high:
            rating, vr = score_signal(closes[:i+1], volumes[i], avg_vol)
            if rating != "SKIP":
                return {"time": times[i], "price": closes[i],
                        "rating": rating, "vol_ratio": vr, "signal": "ORB"}

    # Secondary: VWAP cross (price was below VWAP for 3+ bars, then crosses above with strong volume)
    for i in range(ORB_BARS + 3, len(closes)):
        was_below = all(closes[i - k] < vwap[i - k] for k in range(1, 4))
        cross_up  = closes[i] > vwap[i]
        if was_below and cross_up and volumes[i] >= avg_vol * 1.5:
            rating, vr = score_signal(closes[:i+1], volumes[i], avg_vol)
            if rating != "SKIP":
                return {"time": times[i], "price": closes[i],
                        "rating": rating, "vol_ratio": vr, "signal": "VWAP"}

    return None


def run_ex1(trade_date=None):
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    next_day = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"EX1 — {trade_date}")
    print("Fetching official closing prices...")
    daily = yf.download(TICKERS, start=trade_date, end=next_day,
                        interval="1d", progress=False, auto_adjust=True)
    eod_prices = {}
    for t in TICKERS:
        try:
            val = daily["Close"][t].iloc[0]
            if not (val != val):  # NaN check
                eod_prices[t] = round(float(val), 2)
        except Exception:
            pass

    cash    = BUDGET
    entries = []
    skipped = []

    for ticker in TICKERS:
        if ticker not in eod_prices:
            skipped.append(f"{ticker}(no data)")
            continue

        print(f"  Analyzing {ticker}...")
        data  = yf.download(ticker, period="5d", interval="1m",
                            progress=False, auto_adjust=True)
        today = data[data.index.strftime("%Y-%m-%d") == trade_date].between_time("09:30", "15:59")

        if today.empty:
            skipped.append(f"{ticker}(no data)")
            continue

        closes  = [round(float(v), 2) for v in today["Close"].squeeze().tolist()]
        highs   = [round(float(v), 2) for v in today["High"].squeeze().tolist()]
        lows    = [round(float(v), 2) for v in today["Low"].squeeze().tolist()]
        volumes = [int(v) for v in today["Volume"].squeeze().tolist()]
        times   = [t.strftime("%H:%M") for t in today.index]
        eod     = eod_prices[ticker]

        entry = find_entry(closes, highs, lows, volumes, times)

        if entry is None:
            skipped.append(f"{ticker}(no signal)")
            continue

        alloc = ALLOC[entry["rating"]]
        if cash < alloc:
            skipped.append(f"{ticker}(budget)")
            continue

        cash -= alloc
        pnl     = round((eod - entry["price"]) / entry["price"] * alloc, 2)
        pnl_pct = round((eod - entry["price"]) / entry["price"] * 100, 2)
        entries.append({
            "ticker":    ticker,
            "action":    "BUY",
            "signal":    entry["signal"],
            "time":      entry["time"],
            "entry":     entry["price"],
            "eod":       eod,
            "allocated": alloc,
            "units":     round(alloc / entry["price"], 4),
            "pnl":       pnl,
            "pnl_pct":   pnl_pct,
            "rating":    entry["rating"],
            "vol_ratio": round(entry["vol_ratio"], 1),
        })

    total_inv = sum(e["allocated"] for e in entries)
    total_pnl = round(sum(e["pnl"] for e in entries), 2)

    print(f"\n=== Results: {trade_date} ===\n")
    for e in entries:
        s = "+" if e["pnl"] >= 0 else ""
        print(f"  {e['ticker']:5s} | {e['time']} | {e['signal']:4s} | "
              f"${e['entry']:.2f} entry | {e['rating']} {e['vol_ratio']}x | "
              f"EOD ${e['eod']:.2f} | {s}${e['pnl']:.2f} ({s}{e['pnl_pct']:.2f}%)")

    if skipped:
        print(f"\n  No entry: {', '.join(skipped)}")

    print(f"\n  Deployed: ${total_inv:.2f} | Cash: ${round(cash, 2):.2f}")
    print(f"  P&L: ${total_pnl:+.2f} | Portfolio EOD: ${round(BUDGET + total_pnl, 2):.2f}")

    exercise = {
        "title":            "Exercise 1 - Buy",
        "date":             trade_date,
        "starting_capital": BUDGET,
        "cash_held":        round(cash, 2),
        "trades":           entries,
        "total_invested":   round(total_inv, 2),
        "eod_value":        round(total_inv + total_pnl, 2),
        "total_pnl":        total_pnl,
        "total_pnl_pct":    round(total_pnl / total_inv * 100, 2) if total_inv else 0,
        "portfolio_eod":    round(BUDGET + total_pnl, 2),
    }

    path = os.path.join(BASE_DIR, "exercises.json")
    existing = []
    if os.path.exists(path):
        with open(path) as f:
            existing = json.load(f)
    existing = [e for e in existing if e["date"] != trade_date]
    existing.append(exercise)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)
    print(f"\n  Saved to exercises.json")

    return exercise


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_ex1(date_arg)
