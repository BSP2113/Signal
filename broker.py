"""
broker.py — Alpaca trading API wrapper for Signal Reader live execution.

Thin layer on top of alpaca-py. Every trading action goes through here so we
can swap paper ↔ live by changing one .env variable, and so we have one place
to add logging, error handling, and (eventually) a kill switch.

Used by live_ex1.py — never call alpaca-py directly from the runner.

Account-type assumption: CASH account. Functions that would only matter on a
margin account (shorting, leverage checks) are intentionally omitted.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus


# ── Config ────────────────────────────────────────────────────────────────────
def _load_env():
    """Read API key/secret/base from Signal/.env (the file the simulator already uses)."""
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
_API_KEY    = _cfg.get("ALPACA_API_KEY")
_API_SECRET = _cfg.get("ALPACA_API_SECRET")
_BASE_URL   = _cfg.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
IS_PAPER    = "paper" in _BASE_URL.lower()

if not _API_KEY or not _API_SECRET:
    raise RuntimeError("Alpaca credentials missing from Signal/.env")


# ── Client (lazy singleton) ───────────────────────────────────────────────────
_client: Optional[TradingClient] = None


def client() -> TradingClient:
    global _client
    if _client is None:
        _client = TradingClient(api_key=_API_KEY, secret_key=_API_SECRET, paper=IS_PAPER)
    return _client


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class Account:
    cash: float                # settled cash
    buying_power: float        # what the broker says we can spend right now
    equity: float              # total account value (cash + positions market value)
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
def account() -> Account:
    a = client().get_account()
    return Account(
        cash             = float(a.cash),
        buying_power     = float(a.buying_power),
        equity           = float(a.equity),
        portfolio_value  = float(a.portfolio_value),
        pattern_day_trader = bool(a.pattern_day_trader),
        is_paper         = IS_PAPER,
    )


def settled_cash() -> float:
    """Cash the broker says is available to spend RIGHT NOW. In a cash account
    this excludes proceeds from same-day sells (they settle T+1)."""
    return account().buying_power


# ── Position helpers ──────────────────────────────────────────────────────────
def position(ticker: str) -> Optional[Position]:
    """Return current position for ticker, or None if flat."""
    try:
        p = client().get_open_position(ticker)
    except Exception:
        return None
    return Position(
        ticker             = p.symbol,
        qty                = float(p.qty),
        avg_entry          = float(p.avg_entry_price),
        market_value       = float(p.market_value),
        unrealized_pnl     = float(p.unrealized_pl),
        unrealized_pnl_pct = float(p.unrealized_plpc) * 100,
    )


def all_positions() -> list[Position]:
    """All currently-open positions across the account."""
    out = []
    for p in client().get_all_positions():
        out.append(Position(
            ticker             = p.symbol,
            qty                = float(p.qty),
            avg_entry          = float(p.avg_entry_price),
            market_value       = float(p.market_value),
            unrealized_pnl     = float(p.unrealized_pl),
            unrealized_pnl_pct = float(p.unrealized_plpc) * 100,
        ))
    return out


# ── Order placement ───────────────────────────────────────────────────────────
def market_buy(ticker: str, dollars: float) -> dict:
    """
    Submit a market BUY for approximately `dollars` worth of `ticker`.
    Uses notional sizing (Alpaca calculates qty from current price), so we
    don't have to worry about lot rounding.

    Returns a dict with order_id, qty (after fill), submitted_at, status.
    """
    if dollars <= 0:
        raise ValueError(f"market_buy: dollars must be positive (got {dollars})")
    bp = settled_cash()
    if dollars > bp:
        raise RuntimeError(f"market_buy {ticker}: ${dollars:.2f} requested but only "
                           f"${bp:.2f} buying power available")

    order = client().submit_order(MarketOrderRequest(
        symbol        = ticker,
        notional      = round(dollars, 2),
        side          = OrderSide.BUY,
        time_in_force = TimeInForce.DAY,
    ))
    return _order_summary(order)


def market_sell_position(ticker: str) -> dict:
    """Liquidate the entire open position for ticker via market sell."""
    pos = position(ticker)
    if pos is None or pos.qty == 0:
        raise RuntimeError(f"market_sell_position {ticker}: no open position")

    order = client().submit_order(MarketOrderRequest(
        symbol        = ticker,
        qty           = abs(pos.qty),
        side          = OrderSide.SELL,
        time_in_force = TimeInForce.DAY,
    ))
    return _order_summary(order)


def attach_stop_loss(ticker: str, qty: float, stop_price: float) -> dict:
    """
    Submit a native stop-loss SELL order for `qty` shares of `ticker`.
    Broker watches every tick and fills at market when stop_price is hit.
    Survives our script crashing.
    """
    order = client().submit_order(StopOrderRequest(
        symbol        = ticker,
        qty           = qty,
        side          = OrderSide.SELL,
        time_in_force = TimeInForce.DAY,
        stop_price    = round(stop_price, 2),
    ))
    return _order_summary(order)


def attach_take_profit(ticker: str, qty: float, limit_price: float) -> dict:
    """
    Submit a native take-profit limit SELL order. Used for MAYBE-rated entries
    only — TAKE-rated trades skip the +3% cap by design.
    """
    order = client().submit_order(LimitOrderRequest(
        symbol        = ticker,
        qty           = qty,
        side          = OrderSide.SELL,
        time_in_force = TimeInForce.DAY,
        limit_price   = round(limit_price, 2),
    ))
    return _order_summary(order)


# ── Order management ──────────────────────────────────────────────────────────
def open_orders(ticker: Optional[str] = None) -> list[dict]:
    """All open (unfilled) orders. Optionally filter to a single ticker."""
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[ticker] if ticker else None)
    return [_order_summary(o) for o in client().get_orders(req)]


def cancel_order(order_id: str) -> None:
    client().cancel_order_by_id(order_id)


def cancel_all_open_orders() -> int:
    """Cancel every open order across the account. Returns count cancelled."""
    cancelled = client().cancel_orders()
    return len(cancelled) if cancelled else 0


# ── Internal helpers ──────────────────────────────────────────────────────────
def _order_summary(o) -> dict:
    """Trim Alpaca's order object to the fields the runner cares about."""
    return {
        "order_id":     str(o.id),
        "ticker":       o.symbol,
        "side":         o.side.value if hasattr(o.side, "value") else str(o.side),
        "type":         o.order_type.value if hasattr(o.order_type, "value") else str(o.order_type),
        "qty":          float(o.qty) if o.qty else 0.0,
        "notional":     float(o.notional) if o.notional else None,
        "filled_qty":   float(o.filled_qty) if o.filled_qty else 0.0,
        "filled_price": float(o.filled_avg_price) if o.filled_avg_price else None,
        "limit_price":  float(o.limit_price) if o.limit_price else None,
        "stop_price":   float(o.stop_price) if o.stop_price else None,
        "status":       o.status.value if hasattr(o.status, "value") else str(o.status),
        "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
    }


# ── Smoke test (run as `venv/bin/python3 broker.py`) ──────────────────────────
if __name__ == "__main__":
    print(f"Broker connected to: {_BASE_URL}  (paper={IS_PAPER})")
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
