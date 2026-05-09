"""
alerts.py — Telegram push notifications for Signal Reader live trading.

Sends short, formatted messages to the user's phone for:
  - Order placements (entries, exits)
  - Errors that need attention
  - End-of-day summary

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from Signal/.env. If either is
missing, alerts no-op and log a warning — they never block trading.
"""

import os
import time
import urllib.parse
import urllib.request
from datetime import datetime


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


_cfg        = _load_env()
_BOT_TOKEN  = _cfg.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID    = _cfg.get("TELEGRAM_CHAT_ID", "")
_ENABLED    = bool(_BOT_TOKEN and _CHAT_ID)

if not _ENABLED:
    print("[alerts] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing — alerts disabled")


# ── Core send (raw) ───────────────────────────────────────────────────────────
def _send_raw(text: str, retry: int = 2) -> bool:
    """Send a Telegram message. Returns True on success, False on failure.
    Never raises — alert failure must not interrupt trading."""
    if not _ENABLED:
        return False

    url  = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":    _CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
    }).encode()

    for attempt in range(retry + 1):
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except Exception as e:
            if attempt < retry:
                time.sleep(1)
                continue
            print(f"[alerts] send failed after {retry+1} attempts: {e}")
            return False
    return False


# ── Formatted alert wrappers ──────────────────────────────────────────────────
def entry(ticker: str, signal: str, rating: str, price: float, dollars: float,
          stop_price: float, take_profit: float | None) -> bool:
    """Order placed — entered a position."""
    tp_line = f"\nTP:    `${take_profit:.2f}`" if take_profit else ""
    msg = (
        f"🟢 *ENTRY* `{ticker}` {signal} {rating}\n"
        f"Price: `${price:.2f}`  Size: `${dollars:,.2f}`\n"
        f"Stop:  `${stop_price:.2f}`{tp_line}"
    )
    return _send_raw(msg)


def position_exit(ticker: str, reason: str, entry_price: float, exit_price: float,
                  pnl_dollars: float, pnl_pct: float) -> bool:
    """Position closed — exit fired (stop / take-profit / trail / time-close / etc)."""
    emoji = "✅" if pnl_dollars >= 0 else "❌"
    sign  = "+" if pnl_dollars >= 0 else ""
    msg = (
        f"{emoji} *EXIT* `{ticker}` ({reason})\n"
        f"Entry: `${entry_price:.2f}` → Exit: `${exit_price:.2f}`\n"
        f"P&L:   `{sign}${pnl_dollars:.2f}` ({sign}{pnl_pct:.2f}%)"
    )
    return _send_raw(msg)


def error(context: str, detail: str) -> bool:
    """Something went wrong — needs attention."""
    msg = f"⚠️ *ERROR* — {context}\n```\n{detail[:500]}\n```"
    return _send_raw(msg)


def info(text: str) -> bool:
    """General info message."""
    return _send_raw(f"ℹ️ {text}")


def session_open(market_state: str, starting_cash: float) -> bool:
    msg = (
        f"🔔 *SESSION OPEN* {datetime.now().strftime('%Y-%m-%d')}\n"
        f"Market: `{market_state.upper()}`\n"
        f"Cash:   `${starting_cash:,.2f}`"
    )
    return _send_raw(msg)


def session_close(realized_pnl: float, n_trades: int, n_wins: int,
                  end_cash: float) -> bool:
    sign = "+" if realized_pnl >= 0 else ""
    msg = (
        f"🏁 *SESSION CLOSE* {datetime.now().strftime('%Y-%m-%d')}\n"
        f"P&L:    `{sign}${realized_pnl:.2f}`\n"
        f"Trades: `{n_trades}`  ({n_wins} wins)\n"
        f"Cash:   `${end_cash:,.2f}`"
    )
    return _send_raw(msg)


# ── Smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if not _ENABLED:
        print("Cannot test — Telegram credentials not set in .env")
        print("Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, then re-run.")
        sys.exit(1)
    print("Sending test message to Telegram...")
    ok = info(f"Signal Reader test message at {datetime.now().strftime('%H:%M:%S')}")
    print("✓ sent" if ok else "✗ failed (check token/chat_id)")
