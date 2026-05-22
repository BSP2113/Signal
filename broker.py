"""
broker.py — IBKR trading API wrapper for Signal Reader live execution.

Thin layer on top of ib_insync. Public interface matches the previous Alpaca
version so live_ex1.py / alerts.py / tests need no changes.

Connects to IB Gateway running on localhost (managed by IBC under systemd).
Paper port = 4002, live port = 4001.

Account-type assumption: CASH account. Functions that would only matter on a
margin account (shorting, leverage) are intentionally omitted.
"""

import os
import math
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder


# ── Config ────────────────────────────────────────────────────────────────────
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    cfg = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


_cfg = _load_env()
_HOST      = _cfg.get("IBKR_HOST", "127.0.0.1")
_PORT      = int(_cfg.get("IBKR_PORT", "4002"))   # 4002 paper, 4001 live
_CLIENT_ID = int(_cfg.get("IBKR_CLIENT_ID", "1"))
_ACCOUNT   = _cfg.get("IBKR_ACCOUNT", "")          # blank = primary
# IS_PAPER gates live_ex1.py's $5K sizing cap (broker.IS_PAPER → cap to BUDGET).
# Normally derived from port (4002=paper, 4001=live), but when Gateway sits behind
# a socat / SSH bridge the port can be anything, so allow IBKR_PAPER in .env to
# override explicitly. Only falls back to port-based detection when unset.
_paper_env = _cfg.get("IBKR_PAPER", "").strip().lower()
if _paper_env in ("1", "true", "yes", "on"):
    IS_PAPER = True
elif _paper_env in ("0", "false", "no", "off"):
    IS_PAPER = False
else:
    IS_PAPER = _PORT == 4002

# Reconnect behavior — see client(). A transient Gateway drop (peer-close, a
# WireGuard blip, or the previous clientId not yet released after a restart)
# usually clears within a few seconds, so retry before surfacing the error.
_CONNECT_RETRIES    = 3
_CONNECT_RETRY_WAIT = 3.0   # seconds between attempts


# ── Client (lazy singleton, reconnects if dropped) ────────────────────────────
_client: Optional[IB] = None
_client_lock = threading.Lock()


def client() -> IB:
    global _client
    with _client_lock:
        if _client is None or not _client.isConnected():
            # Retry a few times before giving up: a momentary drop should not
            # bubble up as a loop exception + Telegram alert, and on restart the
            # Gateway may briefly still hold the old clientId.
            last_err = None
            for attempt in range(1, _CONNECT_RETRIES + 1):
                try:
                    ib = IB()
                    ib.connect(_HOST, _PORT, clientId=_CLIENT_ID, timeout=15)
                    _client = ib
                    return _client
                except Exception as e:
                    last_err = e
                    print(f"[broker] connect attempt {attempt}/{_CONNECT_RETRIES} "
                          f"failed: {e!r}")
                    if attempt < _CONNECT_RETRIES:
                        time.sleep(_CONNECT_RETRY_WAIT)
            raise ConnectionError(
                f"broker.client: could not connect to IB Gateway at "
                f"{_HOST}:{_PORT} after {_CONNECT_RETRIES} attempts") from last_err
        return _client


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class Account:
    cash: float
    buying_power: float
    equity: float
    portfolio_value: float
    pattern_day_trader: bool
    is_paper: bool


@dataclass
class Position:
    ticker: str
    qty: float
    avg_entry: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


# ── Account / cash helpers ────────────────────────────────────────────────────
def _summary() -> dict:
    rows = client().accountSummary(_ACCOUNT) if _ACCOUNT else client().accountSummary()
    out = {}
    for r in rows:
        try:
            out[r.tag] = float(r.value)
        except (TypeError, ValueError):
            out[r.tag] = r.value
    return out


def account() -> Account:
    s = _summary()
    cash = float(s.get("SettledCash", s.get("TotalCashValue", 0)))
    return Account(
        cash               = cash,
        buying_power       = float(s.get("AvailableFunds", cash)),
        equity             = float(s.get("NetLiquidation", 0)),
        portfolio_value    = float(s.get("GrossPositionValue", 0)) + cash,
        pattern_day_trader = False,  # cash account is exempt
        is_paper           = IS_PAPER,
    )


def _settled_cash_today() -> Optional[float]:
    """Cash that has fully settled as of today, from IBKR's SettledCashByDate.

    IBKR reports it as 'YYYYMMDD:amount;YYYYMMDD:amount;...' — each pair is the
    settled balance as of that settlement date. The pair for today (or the most
    recent date that has already arrived) is the cash safe to spend now without
    a good-faith violation. Returns None if IBKR did not report the field.
    """
    today = datetime.now().strftime("%Y%m%d")
    vals = client().accountValues(_ACCOUNT) if _ACCOUNT else client().accountValues()
    for v in vals:
        if v.tag != "SettledCashByDate" or not v.value:
            continue
        pairs = {}
        for chunk in v.value.split(";"):
            if ":" in chunk:
                d, amt = chunk.split(":", 1)
                try:
                    pairs[d.strip()] = float(amt)
                except ValueError:
                    pass
        if not pairs:
            return None
        arrived = {d: a for d, a in pairs.items() if d <= today}
        if arrived:
            return arrived[max(arrived)]   # most recent settlement date reached
        return min(pairs.values())         # all future-dated → conservative floor
    return None


def settled_cash() -> float:
    """Cash genuinely available to spend without a good-faith violation.

    Paper: AvailableFunds — paper is virtual $1M with no GFV enforcement, and
    the paper_seed calibration was snapshotted against this field.

    Live cash account: SettledCashByDate's today figure. AvailableFunds is
    wrong here — it includes unsettled same-day sale proceeds, and buying with
    those then selling same day is a good-faith violation (3 in 12 months →
    90-day cash-settled-only lock). If IBKR does not report SettledCashByDate,
    return 0.0 (blocks new entries) rather than silently risk a violation.
    See GO_LIVE.md — this MUST be verified against the real cash account day one.
    """
    if IS_PAPER:
        s = _summary()
        return float(s.get("AvailableFunds", s.get("SettledCash", 0)))
    settled = _settled_cash_today()
    if settled is None:
        print("[broker] WARNING: live account did not report SettledCashByDate — "
              "cannot confirm settled cash; returning $0 to block entries (GFV-safe).")
        return 0.0
    return settled


# ── Position helpers ──────────────────────────────────────────────────────────
def position(ticker: str) -> Optional[Position]:
    for p in client().portfolio():
        if p.contract.symbol == ticker and p.position != 0:
            qty = float(p.position)
            cost = float(p.averageCost)
            return Position(
                ticker             = ticker,
                qty                = qty,
                avg_entry          = cost,
                market_value       = float(p.marketValue),
                unrealized_pnl     = float(p.unrealizedPNL),
                unrealized_pnl_pct = (float(p.unrealizedPNL) / (cost * qty)) * 100 if (cost and qty) else 0.0,
            )
    return None


def all_positions() -> list[Position]:
    out = []
    for p in client().portfolio():
        if p.position == 0:
            continue
        qty = float(p.position)
        cost = float(p.averageCost)
        out.append(Position(
            ticker             = p.contract.symbol,
            qty                = qty,
            avg_entry          = cost,
            market_value       = float(p.marketValue),
            unrealized_pnl     = float(p.unrealizedPNL),
            unrealized_pnl_pct = (float(p.unrealizedPNL) / (cost * qty)) * 100 if (cost and qty) else 0.0,
        ))
    return out


# ── Order placement ───────────────────────────────────────────────────────────
def _stock(ticker: str) -> Stock:
    c = Stock(ticker, "SMART", "USD")
    client().qualifyContracts(c)
    return c


def _latest_price(ticker: str, retries: int = 1, retry_wait: float = 1.5) -> float:
    """Snapshot price for dollar→qty conversion. Falls back to last/close.

    Each candidate (marketPrice, last, close) is independently validated for
    NaN and non-positive values, because NaN is truthy in Python and would
    otherwise slip through `or` chains and propagate into share-count math.

    If the first call yields no valid price (IBKR data not yet populated for
    this contract), retries up to `retries` more times with `retry_wait`s
    between attempts.
    """
    c = _stock(ticker)
    attempts = retries + 1
    for attempt in range(attempts):
        [tk] = client().reqTickers(c)
        for candidate in (tk.marketPrice(), tk.last, tk.close):
            if candidate is None:
                continue
            try:
                p = float(candidate)
            except (TypeError, ValueError):
                continue
            if math.isnan(p) or p <= 0:
                continue
            return p
        if attempt < attempts - 1:
            print(f"[broker] _latest_price {ticker}: no price on attempt {attempt+1}/{attempts}, retrying in {retry_wait}s")
            client().sleep(retry_wait)
    raise RuntimeError(f"_latest_price {ticker}: no valid price after {attempts} attempts (market/last/close all NaN or <=0)")


def market_buy(ticker: str, dollars: float, price_hint: float | None = None) -> dict:
    """
    Submit a market BUY for approximately `dollars` worth of `ticker`.
    Whole shares only — qty = floor(dollars / latest_price). May leave a few
    dollars unspent vs Alpaca's exact-notional behavior.

    price_hint: a known-fresh price (e.g. from the Alpaca signal bar) used to
    compute share count. Avoids calling IBKR for a price snapshot, which
    returns NaN on IBKR Lite without a paid market-data subscription. Falls
    back to `_latest_price` only when no hint is given.
    """
    if dollars <= 0:
        raise ValueError(f"market_buy: dollars must be positive (got {dollars})")
    bp = settled_cash()
    if dollars > bp:
        raise RuntimeError(f"market_buy {ticker}: ${dollars:.2f} requested but only "
                           f"${bp:.2f} buying power available")

    if price_hint is not None and not math.isnan(price_hint) and price_hint > 0:
        price = float(price_hint)
    else:
        price = _latest_price(ticker)
    qty = math.floor(dollars / price)
    if qty < 1:
        raise RuntimeError(f"market_buy {ticker}: ${dollars:.2f} / ${price:.2f} = {qty} shares")

    order = MarketOrder("BUY", qty, tif="DAY", outsideRth=False)
    trade = client().placeOrder(_stock(ticker), order)
    client().sleep(1.5)  # brief wait for status update
    return _trade_summary(trade)


def market_sell_position(ticker: str) -> dict:
    pos = position(ticker)
    if pos is None or pos.qty == 0:
        raise RuntimeError(f"market_sell_position {ticker}: no open position")

    order = MarketOrder("SELL", abs(pos.qty), tif="DAY", outsideRth=False)
    trade = client().placeOrder(_stock(ticker), order)
    client().sleep(1.5)
    return _trade_summary(trade)


def attach_stop_loss(ticker: str, qty: float, stop_price: float) -> dict:
    order = StopOrder("SELL", qty, round(stop_price, 2), tif="DAY", outsideRth=False)
    trade = client().placeOrder(_stock(ticker), order)
    client().sleep(1.0)
    return _trade_summary(trade)


def attach_take_profit(ticker: str, qty: float, limit_price: float) -> dict:
    order = LimitOrder("SELL", qty, round(limit_price, 2), tif="DAY", outsideRth=False)
    trade = client().placeOrder(_stock(ticker), order)
    client().sleep(1.0)
    return _trade_summary(trade)


# ── Order management ──────────────────────────────────────────────────────────
def open_orders(ticker: Optional[str] = None) -> list[dict]:
    out = []
    for trade in client().openTrades():
        if trade.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
            continue
        if ticker and trade.contract.symbol != ticker:
            continue
        out.append(_trade_summary(trade))
    return out


def cancel_order(order_id: str) -> None:
    target = int(order_id)
    for trade in client().openTrades():
        if trade.order.orderId == target:
            client().cancelOrder(trade.order)
            return


def cancel_all_open_orders() -> int:
    n = 0
    for trade in client().openTrades():
        client().cancelOrder(trade.order)
        n += 1
    return n


def closed_orders(symbols: Optional[list[str]] = None,
                  after: Optional[datetime] = None,
                  until: Optional[datetime] = None,
                  limit: int = 500) -> list[dict]:
    """
    Filled orders since the IB session started, normalized to the same shape
    as _trade_summary. Used by live_ex1.execute_exit + reconcile_live.

    Note: IBKR's session-scoped Trade list resets on each Gateway restart, so
    this is reliable for same-day reconciliation but won't return yesterday's
    orders. That matches our usage — reconcile runs at EOD.
    """
    out = []
    for trade in client().trades():
        if trade.orderStatus.status != "Filled":
            continue
        if symbols and trade.contract.symbol not in symbols:
            continue
        # Time filter: use fill time if available, else order time
        fill_ts = None
        if trade.fills:
            fill_ts = trade.fills[-1].execution.time  # UTC datetime
        if after and fill_ts and fill_ts < after:
            continue
        if until and fill_ts and fill_ts >= until:
            continue
        summary = _trade_summary(trade)
        if fill_ts:
            summary["filled_at"] = fill_ts.isoformat()
        out.append(summary)
        if len(out) >= limit:
            break
    return out


# ── Internal helpers ──────────────────────────────────────────────────────────
def _trade_summary(trade) -> dict:
    """Trim ib_insync Trade to the same shape Alpaca's _order_summary produced."""
    o = trade.order
    s = trade.orderStatus
    fills = trade.fills
    fill_avg = None
    if fills:
        total_qty = sum(f.execution.shares for f in fills)
        if total_qty > 0:
            fill_avg = sum(f.execution.price * f.execution.shares for f in fills) / total_qty
    return {
        "order_id":     str(o.orderId),
        "ticker":       trade.contract.symbol,
        "side":         o.action,                                 # "BUY" / "SELL"
        "type":         o.orderType,                              # "MKT" / "LMT" / "STP"
        "qty":          float(o.totalQuantity),
        "notional":     None,
        "filled_qty":   float(s.filled or 0),
        "filled_price": float(fill_avg) if fill_avg else (float(s.avgFillPrice) if s.avgFillPrice else None),
        "limit_price":  float(o.lmtPrice) if o.lmtPrice else None,
        "stop_price":   float(o.auxPrice) if o.auxPrice else None,
        "status":       _status_to_alpaca(s.status),
        "submitted_at": datetime.now().isoformat(),
    }


def _status_to_alpaca(s: str) -> str:
    return {
        "Submitted":       "new",
        "PreSubmitted":    "pending_new",
        "PendingSubmit":   "pending_new",
        "ApiPending":      "pending_new",
        "Filled":          "filled",
        "PartiallyFilled": "partially_filled",
        "Cancelled":       "canceled",
        "ApiCancelled":    "canceled",
        "Inactive":        "rejected",
    }.get(s, s.lower())


# ── Smoke test (run as `venv/bin/python3 broker.py`) ──────────────────────────
if __name__ == "__main__":
    print(f"Broker connecting to {_HOST}:{_PORT}  (paper={IS_PAPER})")
    a = account()
    print(f"  cash:           ${a.cash:>12,.2f}")
    print(f"  buying_power:   ${a.buying_power:>12,.2f}")
    print(f"  equity:         ${a.equity:>12,.2f}")
    print(f"  portfolio:      ${a.portfolio_value:>12,.2f}")
    print(f"  PDT flag:       {a.pattern_day_trader}")
    pos = all_positions()
    print(f"  open positions: {len(pos)}")
    for p in pos:
        print(f"    {p.ticker:6} qty={p.qty:>6.2f}  avg_entry=${p.avg_entry:>7.2f}  "
              f"P&L=${p.unrealized_pnl:>+7.2f} ({p.unrealized_pnl_pct:>+5.2f}%)")
    oo = open_orders()
    print(f"  open orders:    {len(oo)}")
    for o in oo:
        print(f"    {o['ticker']:6} {o['side']:4} {o['type']:8} qty={o['qty']:>6.2f}  "
              f"status={o['status']}")
