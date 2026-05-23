# Signal Reader — Deploy Notes

**Last updated 2026-05-22.** Major architecture finding below — please read
before deploying anything.

---

## ⚠️ The big finding (2026-05-22)

On the same 181-day walk-forward window (2025-09-02..2026-05-21):

| Strategy | $5K → | Return |
|---|---|---|
| Day-trade picker bot (current `live_ex1.py`) | $5,735 | **+14.7%** |
| SPY buy-and-hold (the market) | $5,849 | +17.0% |
| QQQ buy-and-hold | $6,340 | +26.8% |
| **Picker MONTHLY buy-and-hold (`monthly_hold.py`)** | **$8,697** | **+73.9%** |

**The day-trade bot underperforms SPY.** The intraday ORB/GAP_GO machinery
destroys ~80% of the picker's stock-selection edge through friction.
**Holding the same picks for the month captures the edge** — +67.7% out
of sample, beats 50/50 random-15 trials, holds even after removing the
top-3 winners.

**Recommendation:** disable `live_ex1.py`, enable `monthly_hold.py`.

---

## Two bots, two architectures (you pick one)

### Option A — `monthly_hold.py`  (NEW, recommended)

Equal-weight monthly buy-and-hold of `picker_picks.json`. Validated at
+73.9% / +67.7% OOS. Cash-account safe (T+1 settles within the month).

- Runs once per day via cron.
- 99% of days: no-op.
- First trading day of each new month: sell prior holdings (market open).
- T+1 settlement waits.
- Second trading day: buy new month's picks equal-weight.
- State in `monthly_state.json`.
- ~24 trades per year, total.

**Deploy:**
1. Disable the day-trade bot — comment out the live_ex1.py line in crontab:
   ```
   # 25 9 * * 1-5 /home/ben/Signal/venv/bin/python3 -u /home/ben/Signal/live_ex1.py >> /home/ben/Signal/logs/live_ex1.log 2>&1
   ```
2. Add the monthly bot:
   ```
   35 9 * * 1-5 /home/ben/Signal/venv/bin/python3 /home/ben/Signal/monthly_hold.py >> /home/ben/Signal/logs/monthly_hold.log 2>&1
   ```
3. Kill the running day-trade bot:
   ```
   kill -TERM $(pgrep -f live_ex1.py$)
   ```
4. (Optional) Manually liquidate any open positions from the day-trade
   bot via IBKR so monthly_hold starts from a clean cash slate, or let
   monthly_hold liquidate them on the 1st of next month.
5. Tomorrow's 9:35 cron run will detect the month, sell anything left,
   start the rebalance flow.

**Kill switch:** stop the monthly_hold cron and delete `monthly_state.json`.
Or just stop the cron — the script is no-op without it.

### Option B — `live_ex1.py` (current day-trade bot)

The intraday breakout system. After today's testing it's known to
**underperform SPY** on out-of-sample data; keep only as fallback while
you trust the new bot, or while picker_picks.json is missing.

Already configured:
- Cron `25 9 * * 1-5` starts the bot at 9:25 AM.
- `USE_PICKER = True` in `live_ex1.py` — uses `picker_picks.json` if present
  (better than the original hand-picked list, but still day-trading).
- `STOP_LOSS = 0.020` in ex1.py (the +$36 tweak from earlier today).

---

## Files

| File | Role |
|---|---|
| `monthly_pick.py` | Generates `picker_picks.json` once per month (idempotent, cron-driven). |
| `picker_picks.json` | Current month's 15 picks. Atomic-written. |
| **`monthly_hold.py`** | **The new bot — equal-weight monthly buy-and-hold.** |
| **`monthly_state.json`** | New bot's state. Auto-created. |
| `live_ex1.py` | Day-trade bot (underperforms SPY — keep only as fallback). |
| `logs/monthly_pick.log`, `logs/monthly_hold.log` | Cron output. |

`picker_picks.json` schema (what both bots read):
```json
{
  "month": "2026-05",
  "as_of": "2026-05-22",
  "tickers": ["ZS", "DXCM", "DDOG", ...]
}
```

`monthly_state.json` schema (the new bot's state):
```json
{
  "month": "2026-05",
  "phase": "IDLE_HOLDING",            // or AWAITING_SETTLEMENT, INITIAL
  "holdings": ["ZS", "DXCM", ...],     // last bought set
  "bought_on": "2026-05-04",
  "per_position": 333.33,
  "updated": "2026-05-04 09:35:21"
}
```

---

## Honest caveats — read these

1. **The +73.9% rides a strong AI/memory rally** (SNDK +29x, WDC +5x,
   LITE +6x in this period — both Alpaca and yfinance confirm; not a
   data bug, real prices). In a bear or non-momentum regime, expect
   much less. The strategy is essentially "long the momentum factor on
   picker-selected names" — known to be regime-dependent.
2. **No downside protection built in.** A 200-day SPY trend filter
   (`monthly_hold.py` could add this) sat in cash 1 of 9 months in the
   test and gave +70.0% vs +73.9% — a small drag in this bull period
   but the right behavior for a bear regime. Worth adding.
3. **Cash-account T+1 settlement** means there's a 1-trading-day window
   each month between liquidation and the new buy. Not in the market
   ~5% of the time. The bot handles this correctly (TO_SELL →
   AWAITING_SETTLEMENT → TO_BUY phases).
4. **Survivorship:** the universe uses current S&P 500 + NASDAQ 100
   membership; this slightly overstates results across multi-year tests.
5. **First live month**: monthly_hold has not yet run live. Validate
   by paper-trading it for one month before scaling to full $5K.

---

## Recommended next builds (in order)

1. **Add the SPY-200d trend filter to monthly_hold.py** — sit in cash
   when SPY is below its 200d SMA. Light cost in bull periods,
   essential protection in bear periods.
2. **Live-vs-sim parity tracker for monthly_hold** — each rebalance,
   compare actual fills to expected; alert on big slippage.
3. **Multi-month performance monitor** — rolling 3-month return vs
   expectation; alert if live performance falls below the
   walk-forward expectation by some threshold.
4. **Replace the graduation criteria.** "55% win rate" doesn't fit
   monthly buy-and-hold — measure annual return, max drawdown,
   live-vs-walk-forward correlation instead.

---

## Rollback

To completely revert to the day-trade bot:
1. Remove the monthly_hold cron entry.
2. Re-enable the live_ex1.py cron entry.
3. (Optional) Set `USE_PICKER = False` in `live_ex1.py` to force the
   original static 17-ticker list (note: that list is the *overfit*
   one — only use as emergency rollback).

`backups/` has timestamped copies of every file changed today.
