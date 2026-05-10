"""
reconcile_live.py — End-of-day check that what the live runner THINKS happened
matches what actually happened at the broker.

Run after market close (or any time after 14:00). Pulls all of today's filled
orders from Alpaca, compares them to live_state.json's completed_trades, and
flags any divergence. Also prints a clean summary of the day.

Usage:
    venv/bin/python3 reconcile_live.py [YYYY-MM-DD]

If no date arg, uses today.
"""

import os, sys, json
from datetime import datetime, timedelta, timezone

import broker


BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
STATE_FILE  = os.path.join(BASE_DIR, "live_state.json")
TRADES_FILE = os.path.join(BASE_DIR, "trades_live.json")


def fetch_broker_orders(date_str: str) -> list[dict]:
    """All filled orders for the given date, normalized to dicts."""
    start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end   = start + timedelta(days=1)

    rows = []
    for o in broker.closed_orders(after=start, until=end, limit=500):
        if not o.get("filled_price"):
            continue
        rows.append({
            "order_id":     o["order_id"],
            "ticker":       o["ticker"],
            "side":         o["side"].upper(),
            "type":         o["type"].upper(),
            "qty":          float(o["filled_qty"]) if o["filled_qty"] else 0.0,
            "price":        float(o["filled_price"]),
            "submitted_at": o.get("submitted_at", ""),
            "filled_at":    o.get("filled_at", ""),
        })
    rows.sort(key=lambda r: r["filled_at"] or r["submitted_at"])
    return rows


def pair_buys_sells(orders: list[dict]) -> list[dict]:
    """Pair each BUY with its corresponding SELL on the same ticker.
    Simple FIFO — assumes one open position per ticker at a time, which is
    the EX1 invariant."""
    open_buys = {}     # ticker → BUY dict
    pairs     = []
    for o in orders:
        if o["side"] == "BUY":
            open_buys[o["ticker"]] = o
        elif o["side"] == "SELL":
            buy = open_buys.pop(o["ticker"], None)
            if buy is None:
                pairs.append({"ticker": o["ticker"], "buy": None, "sell": o})
                continue
            pnl = (o["price"] - buy["price"]) * buy["qty"]
            pairs.append({
                "ticker":      o["ticker"],
                "buy":         buy,
                "sell":        o,
                "qty":         buy["qty"],
                "entry_price": buy["price"],
                "exit_price":  o["price"],
                "exit_type":   o["type"],
                "pnl":         round(pnl, 2),
                "pnl_pct":     round((o["price"] - buy["price"]) / buy["price"] * 100, 2),
            })
    # Any remaining open_buys = positions still open
    for t, buy in open_buys.items():
        pairs.append({"ticker": t, "buy": buy, "sell": None, "still_open": True})
    return pairs


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")

    print(f"=== Reconcile {date_str} on {'PAPER' if broker.IS_PAPER else 'LIVE'} ===\n")

    # 1. Broker side
    broker_orders = fetch_broker_orders(date_str)
    pairs         = pair_buys_sells(broker_orders)
    broker_pnl    = sum(p["pnl"] for p in pairs if "pnl" in p)
    broker_trades = [p for p in pairs if p.get("sell") is not None]

    print(f"BROKER fills: {len(broker_orders)} orders → {len(broker_trades)} round-trip trades")
    for p in broker_trades:
        sign = "+" if p["pnl"] >= 0 else ""
        print(f"  {p['ticker']:6}  ${p['entry_price']:>7.2f} → ${p['exit_price']:>7.2f}  "
              f"{p['exit_type']:8}  {sign}${p['pnl']:>7.2f}  ({sign}{p['pnl_pct']:.2f}%)")
    open_left = [p for p in pairs if p.get("still_open")]
    if open_left:
        print(f"  ⚠ {len(open_left)} positions STILL OPEN at end of {date_str}:")
        for p in open_left:
            print(f"    {p['ticker']:6}  bought @ ${p['buy']['price']:.2f}")
    print(f"  TOTAL broker P&L: ${broker_pnl:+.2f}\n")

    # 2. State side
    st = load_state()
    if not st or st.get("session_date") != date_str:
        print(f"No live_state.json for {date_str}. Skipping state comparison.")
        return

    state_trades = st.get("completed_trades", [])
    state_pnl    = st.get("session_pnl", 0.0)
    print(f"STATE  trades: {len(state_trades)}  P&L: ${state_pnl:+.2f}\n")

    # 3. Diff
    print("DIVERGENCE CHECK:")
    if abs(broker_pnl - state_pnl) < 0.01 and len(broker_trades) == len(state_trades):
        print(f"  ✓ Broker and state agree (${broker_pnl:+.2f}).")
    else:
        print(f"  ⚠ MISMATCH:")
        print(f"      broker P&L = ${broker_pnl:+.2f} ({len(broker_trades)} trades)")
        print(f"      state  P&L = ${state_pnl:+.2f} ({len(state_trades)} trades)")
        print(f"      delta      = ${broker_pnl - state_pnl:+.2f}")
        # Per-ticker diff
        broker_by_t = {p["ticker"]: p for p in broker_trades}
        state_by_t  = {t["ticker"]: t for t in state_trades}
        for ticker in sorted(set(broker_by_t) | set(state_by_t)):
            b = broker_by_t.get(ticker)
            s = state_by_t.get(ticker)
            if b and s:
                if abs(b["pnl"] - s["pnl"]) > 0.01:
                    print(f"      {ticker}: broker ${b['pnl']:+.2f} vs state ${s['pnl']:+.2f}")
            elif b and not s:
                print(f"      {ticker}: in broker only ({b['pnl']:+.2f})")
            elif s and not b:
                print(f"      {ticker}: in state only ({s['pnl']:+.2f})")

    # 4. Persist trades_live.json
    with open(TRADES_FILE, "w") as f:
        json.dump({
            "date":         date_str,
            "broker_pnl":   round(broker_pnl, 2),
            "state_pnl":    round(state_pnl, 2),
            "trades":       broker_trades,
            "still_open":   open_left,
        }, f, indent=2, default=str)
    print(f"\nWrote {TRADES_FILE}")


if __name__ == "__main__":
    main()
