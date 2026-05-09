"""
test_take_profit.py — Compare 3 TAKE_PROFIT exit variants against baseline.

Fetches Alpaca data ONCE per date, then simulates all 4 variants in memory.
Does NOT touch exercises.json.

Variants:
  Baseline  : TAKE_PROFIT = 0.03 (current)
  Option A  : No cap — trail + time close handle all exits
  Option B  : TAKE_PROFIT = 0.06 (+6% hard cap)
  Option C  : TAKE-rated = no cap, MAYBE-rated = +3% cap
"""

import sys, os, json, statistics as _stats
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

import ex1  # for constants and helpers only (score_signal, calc_atr_pct, etc.)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ET = "America/New_York"

# ── Historical context: live exercises.json + backfill.json ────────────────────
# Live days have correct market_state on the record; backfill days have stale
# "neutral" so we re-derive from market_states_historical.json using current
# SPY_BULL/SPY_BEAR/VIXY_SURGE thresholds in ex1.

def _classify(spy_gap_pct, vixy_trend_pct):
    """Re-derive market state with current ex1 thresholds. Inputs are percent
    units (e.g. 0.42 = 0.42%) matching market_states_historical.json."""
    if spy_gap_pct / 100 <= ex1.SPY_BEAR or vixy_trend_pct / 100 >= ex1.VIXY_SURGE:
        return "bearish"
    if spy_gap_pct / 100 >= ex1.SPY_BULL and vixy_trend_pct / 100 < ex1.VIXY_SURGE:
        return "bullish"
    return "neutral"

hist_states = {}
date_source = {}  # for reporting: "live" vs "backfill"

with open(os.path.join(BASE_DIR, "exercises.json")) as f:
    for d in json.load(f):
        if "Exercise 1" in d["title"]:
            hist_states[d["date"]] = d["market_state"]
            date_source[d["date"]] = "live"

with open(os.path.join(BASE_DIR, "market_states_historical.json")) as f:
    _msh = {row["date"]: row for row in json.load(f)}

with open(os.path.join(BASE_DIR, "backfill.json")) as f:
    for d in json.load(f):
        date = d["date"]
        if date in hist_states:
            continue  # live wins if both have it
        row = _msh.get(date)
        if row:
            hist_states[date] = _classify(row["spy_gap_pct"], row["vixy_trend_pct"])
        else:
            hist_states[date] = d.get("market_state", "neutral")
        date_source[date] = "backfill"

DATES = sorted(hist_states.keys())


# ── find_exit variants ─────────────────────────────────────────────────────────
def make_find_exit(tp):
    """tp=float means hard cap at that %; tp=None means no cap (trail-only)."""
    def _fe(closes, times, entry_price, entry_bar, ticker=None):
        peak         = entry_price
        consec_above = 0
        trail_armed  = False
        lock_level   = entry_price * (1 + ex1.TRAIL_LOCK)
        entry_mins   = int(times[entry_bar][:2]) * 60 + int(times[entry_bar][3:])
        t90_mins     = entry_mins + ex1.NO_PROGRESS_MINS
        t90_passed   = False
        tew_mins     = entry_mins + ex1.EARLY_WEAK_MINS
        tew_passed   = False

        for i in range(entry_bar + 1, len(closes)):
            price    = closes[i]
            bar_mins = int(times[i][:2]) * 60 + int(times[i][3:])
            peak     = max(peak, price)

            if price >= lock_level:
                consec_above += 1
            else:
                consec_above = 0
            if consec_above >= 2:
                trail_armed = True

            if times[i] >= ex1.ENTRY_CLOSE:
                return {"bar": i, "time": times[i], "price": price, "reason": "TIME_CLOSE"}
            if tp is not None and price >= entry_price * (1 + tp):
                return {"bar": i, "time": times[i], "price": price, "reason": "TAKE_PROFIT"}
            if trail_armed and price <= peak * (1 - ex1.TRAIL_STOP):
                return {"bar": i, "time": times[i], "price": price, "reason": "TRAILING_STOP"}
            if price <= entry_price * (1 - ex1.STOP_LOSS):
                return {"bar": i, "time": times[i], "price": price, "reason": "STOP_LOSS"}
            if not t90_passed and bar_mins >= t90_mins and t90_mins <= 14 * 60:
                t90_passed = True
                if price <= entry_price:
                    return {"bar": i, "time": times[i], "price": price, "reason": "NO_PROGRESS"}
            if ticker not in ex1.EARLY_WEAK_SKIP and not tew_passed and bar_mins >= tew_mins:
                tew_passed = True
                if price < entry_price:
                    lookback = max(entry_bar + 1, i - ex1.EARLY_WEAK_LOOKBACK)
                    if price < closes[lookback]:
                        return {"bar": i, "time": times[i], "price": price, "reason": "EARLY_WEAK"}

        return {"bar": len(closes) - 1, "time": times[-1], "price": closes[-1], "reason": "EOD"}
    return _fe


FE_BASELINE = make_find_exit(0.03)
FE_NO_CAP   = make_find_exit(None)
FE_6PCT     = make_find_exit(0.06)


def find_exit_option_c(closes, times, entry_price, entry_bar, ticker=None, rating=None):
    fe = FE_NO_CAP if rating == "TAKE" else FE_BASELINE
    return fe(closes, times, entry_price, entry_bar, ticker)


# ── Opt D/E/F: tightening trail variants ──────────────────────────────────────
# Below trigger peak: standard 2% trail (armed at +1% per ex1.TRAIL_LOCK).
# Once peak >= trigger: trail tightens to TIGHT_TRAIL from peak.
# No hard take-profit cap. All other exits unchanged.
def make_tight_trail(trigger, tight):
    def _fe(closes, times, entry_price, entry_bar, ticker=None):
        return _tight_impl(closes, times, entry_price, entry_bar, ticker,
                           trigger, tight)
    return _fe


def _tight_impl(closes, times, entry_price, entry_bar, ticker, TIGHT_TRIGGER, TIGHT_TRAIL):
    peak         = entry_price
    consec_above = 0
    trail_armed  = False
    tight_on     = False
    lock_level   = entry_price * (1 + ex1.TRAIL_LOCK)
    entry_mins   = int(times[entry_bar][:2]) * 60 + int(times[entry_bar][3:])
    t90_mins     = entry_mins + ex1.NO_PROGRESS_MINS
    t90_passed   = False
    tew_mins     = entry_mins + ex1.EARLY_WEAK_MINS
    tew_passed   = False

    for i in range(entry_bar + 1, len(closes)):
        price    = closes[i]
        bar_mins = int(times[i][:2]) * 60 + int(times[i][3:])
        peak     = max(peak, price)

        if peak >= entry_price * (1 + TIGHT_TRIGGER):
            tight_on = True

        if price >= lock_level:
            consec_above += 1
        else:
            consec_above = 0
        if consec_above >= 2:
            trail_armed = True

        if times[i] >= ex1.ENTRY_CLOSE:
            return {"bar": i, "time": times[i], "price": price, "reason": "TIME_CLOSE"}
        # Tight trail wins once engaged (it's stricter than the 2% trail)
        if tight_on and price <= peak * (1 - TIGHT_TRAIL):
            return {"bar": i, "time": times[i], "price": price, "reason": "TIGHT_TRAIL"}
        if trail_armed and price <= peak * (1 - ex1.TRAIL_STOP):
            return {"bar": i, "time": times[i], "price": price, "reason": "TRAILING_STOP"}
        if price <= entry_price * (1 - ex1.STOP_LOSS):
            return {"bar": i, "time": times[i], "price": price, "reason": "STOP_LOSS"}
        if not t90_passed and bar_mins >= t90_mins and t90_mins <= 14 * 60:
            t90_passed = True
            if price <= entry_price:
                return {"bar": i, "time": times[i], "price": price, "reason": "NO_PROGRESS"}
        if ticker not in ex1.EARLY_WEAK_SKIP and not tew_passed and bar_mins >= tew_mins:
            tew_passed = True
            if price < entry_price:
                lookback = max(entry_bar + 1, i - ex1.EARLY_WEAK_LOOKBACK)
                if price < closes[lookback]:
                    return {"bar": i, "time": times[i], "price": price, "reason": "EARLY_WEAK"}

    return {"bar": len(closes) - 1, "time": times[-1], "price": closes[-1], "reason": "EOD"}


# ── find_all_trades (parameterized by find_exit fn) ───────────────────────────
def find_all_trades(closes, highs, lows, volumes, times, skip_orb,
                    spy_by_time, gap_pct, ticker, fe_fn):
    if len(closes) <= ex1.ORB_BARS:
        return []

    avg_vol  = sum(volumes) / len(volumes) if volumes else 1
    orb_high = max(closes[:ex1.ORB_BARS])
    day_open = closes[0]

    # GAP_GO
    if gap_pct >= ex1.GAP_GO_THRESH and ticker not in ex1.GAP_GO_SKIP_TICKERS:
        open_bar_high = highs[0]
        for i in range(1, len(closes)):
            if times[i] > ex1.GAP_GO_WINDOW:
                break
            if closes[i] > open_bar_high:
                vr = volumes[i] / avg_vol if avg_vol else 0
                if vr < 1.0:
                    continue
                rating = "TAKE" if vr >= 1.5 else "MAYBE"
                if spy_by_time and day_open:
                    ticker_chg = (closes[i] - day_open) / day_open
                    spy_times  = sorted(t for t in spy_by_time if t <= times[i])
                    if spy_times:
                        spy_open = spy_by_time[spy_times[0]]
                        spy_now  = spy_by_time[spy_times[-1]]
                        spy_chg  = (spy_now - spy_open) / spy_open if spy_open else 0
                        if ticker_chg <= spy_chg:
                            return []
                entry = {"bar": i, "time": times[i], "price": closes[i],
                         "rating": rating, "vol_ratio": round(vr, 1), "signal": "GAP_GO"}
                # Option C uses rating-aware version
                if fe_fn is find_exit_option_c:
                    exit_ = fe_fn(closes, times, entry["price"], i, ticker, rating)
                else:
                    exit_ = fe_fn(closes, times, entry["price"], i, ticker)
                return [(entry, exit_)]
        return []

    if skip_orb:
        return []

    for i in range(ex1.ORB_BARS, len(closes)):
        if times[i] > ex1.ORB_CUTOFF:
            break
        if closes[i] > orb_high:
            rating, vr = ex1.score_signal(closes[:i+1], volumes[i], avg_vol)
            if rating != "SKIP":
                if rating == "TAKE" and times[i] < "10:00":
                    continue
                if spy_by_time and day_open:
                    ticker_chg = (closes[i] - day_open) / day_open
                    spy_times  = sorted(t for t in spy_by_time if t <= times[i])
                    if spy_times:
                        spy_open = spy_by_time[spy_times[0]]
                        spy_now  = spy_by_time[spy_times[-1]]
                        spy_chg  = (spy_now - spy_open) / spy_open if spy_open else 0
                        if ticker_chg <= spy_chg:
                            return []
                entry = {"bar": i, "time": times[i], "price": closes[i],
                         "rating": rating, "vol_ratio": round(vr, 1), "signal": "ORB"}
                if fe_fn is find_exit_option_c:
                    exit_ = fe_fn(closes, times, entry["price"], i, ticker, rating)
                else:
                    exit_ = fe_fn(closes, times, entry["price"], i, ticker)
                return [(entry, exit_)]

    return []


# ── Simulate one day against cached ticker data ────────────────────────────────
def simulate_day(date, ticker_data, eod_prices, spy_by_time,
                 atr_modifier, prior_closes, market_state,
                 starting_balance, streak, in_drawdown, fe_fn):

    in_streak  = streak >= ex1.STREAK_TRIGGER
    day_loss_hit = False

    def spy_alloc(rating):
        if market_state == "bullish":
            return round(starting_balance * ex1.ALLOC_PCT_BULL[rating], 2)
        if market_state == "bearish":
            return round(starting_balance * ex1.ALLOC_PCT_BEAR[rating], 2)
        return round(starting_balance * ex1.ALLOC_PCT_NEUT[rating], 2)

    potential = []
    for ticker, td in ticker_data.items():
        closes  = td["closes"]
        highs   = td["highs"]
        lows    = td["lows"]
        volumes = td["volumes"]
        times   = td["times"]

        gap_pct  = 0.0
        skip_orb = False
        if ticker in prior_closes and prior_closes[ticker] and closes:
            gap_pct  = (closes[0] - prior_closes[ticker]) / prior_closes[ticker]
            skip_orb = abs(gap_pct) > ex1.GAP_FILTER

        ticker_trades = find_all_trades(closes, highs, lows, volumes, times,
                                        skip_orb, spy_by_time, gap_pct, ticker, fe_fn)

        modifier = atr_modifier.get(ticker, 1.0)
        for trade_num, (entry, exit_) in enumerate(ticker_trades, 1):
            if trade_num > 1 and market_state != "bullish":
                continue

            alloc = round(spy_alloc(entry["rating"]) * modifier, 2)
            if in_streak and entry["rating"] == "MAYBE":
                alloc = round(alloc * ex1.MAYBE_STREAK_CUT, 2)
            if in_drawdown:
                alloc = round(alloc * ex1.DRAWDOWN_CUT, 2)

            pnl     = round((exit_["price"] - entry["price"]) / entry["price"] * alloc, 2)
            pnl_pct = round((exit_["price"] - entry["price"]) / entry["price"] * 100, 2)
            potential.append({
                "ticker":      ticker,
                "trade_num":   trade_num,
                "signal":      entry["signal"],
                "time":        entry["time"],
                "exit_time":   exit_["time"],
                "entry":       entry["price"],
                "exit":        exit_["price"],
                "exit_reason": exit_["reason"],
                "eod":         eod_prices.get(ticker, exit_["price"]),
                "allocated":   alloc,
                "rating":      entry["rating"],
                "vol_ratio":   entry["vol_ratio"],
                "pnl":         pnl,
                "pnl_pct":     pnl_pct,
            })

    potential.sort(key=lambda t: t["time"])

    entries = []
    active  = []
    for trade in potential:
        if day_loss_hit:
            break
        active   = [a for a in active if a["exit_time"] > trade["time"]]
        deployed = sum(a["allocated"] for a in active)
        if starting_balance - deployed < trade["allocated"]:
            continue
        active.append({"exit_time": trade["exit_time"], "allocated": trade["allocated"]})
        entries.append(trade)
        if round(sum(e["pnl"] for e in entries), 2) <= ex1.DAY_LOSS_LIMIT:
            day_loss_hit = True

    return {
        "date":          date,
        "total_pnl":     round(sum(e["pnl"] for e in entries), 2),
        "total_trades":  len(entries),
        "trades":        entries,
        "starting_cap":  starting_balance,
        "market_state":  market_state,
    }


# ── Fetch all data for one date ────────────────────────────────────────────────
def fetch_day(client, date):
    print(f"  Fetching {date}...", flush=True)
    next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    start_dt = datetime.strptime(date,     "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt   = datetime.strptime(next_day, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    tickers = ex1.TICKERS

    # EOD prices
    daily = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=tickers, timeframe=TimeFrame.Day,
        start=start_dt, end=end_dt, feed="iex",
    ))
    eod_prices = {}
    for t in tickers:
        bars = daily.data.get(t, [])
        if bars:
            eod_prices[t] = round(bars[0].close, 2)

    # Prior closes + ATR
    prior_daily = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=tickers, timeframe=TimeFrame.Day,
        start=start_dt - timedelta(days=21), end=start_dt, feed="iex",
    ))
    prior_closes = {}
    atr_pcts     = {}
    for t in tickers:
        bars = prior_daily.data.get(t, [])
        if bars:
            prior_closes[t] = bars[-1].close
            val = ex1.calc_atr_pct(bars)
            if val:
                atr_pcts[t] = val

    if len(atr_pcts) >= 2:
        med = _stats.median(atr_pcts.values())
        atr_modifier = {
            t: round(min(ex1.ATR_MAX_MOD, max(ex1.ATR_MIN_MOD, med / atr_pcts[t])), 3)
            for t in atr_pcts
        }
    else:
        atr_modifier = {}

    # SPY intraday
    spy_by_time = {}
    try:
        spy_intra = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols="SPY", timeframe=TimeFrame.Minute,
            start=start_dt, end=end_dt, feed="iex",
        ))
        df_spy = spy_intra.df
        if isinstance(df_spy.index, pd.MultiIndex):
            df_spy = df_spy.xs("SPY", level=0)
        df_spy    = df_spy.tz_convert(ET)
        spy_today = df_spy.between_time("09:30", "15:59")
        for t, row in spy_today.iterrows():
            spy_by_time[t.strftime("%H:%M")] = row["close"]
    except Exception:
        pass

    # Per-ticker intraday
    ticker_data = {}
    for ticker in tickers:
        if ticker not in eod_prices:
            continue
        try:
            intra = client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=ticker, timeframe=TimeFrame.Minute,
                start=start_dt, end=end_dt, feed="iex",
            ))
            df = intra.df
            if df.empty:
                continue
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(ticker, level=0)
            df    = df.tz_convert(ET)
            today = df.between_time("09:30", "15:59")
            if today.empty:
                continue
            ticker_data[ticker] = {
                "closes":  [round(float(v), 2) for v in today["close"].tolist()],
                "highs":   [round(float(v), 2) for v in today["high"].tolist()],
                "lows":    [round(float(v), 2) for v in today["low"].tolist()],
                "volumes": [int(v) for v in today["volume"].tolist()],
                "times":   [t.strftime("%H:%M") for t in today.index],
            }
        except Exception:
            pass

    return {
        "eod_prices":   eod_prices,
        "prior_closes": prior_closes,
        "atr_modifier": atr_modifier,
        "spy_by_time":  spy_by_time,
        "ticker_data":  ticker_data,
    }


# ── Wallet helpers (mirrors ex1 logic, reads temp json) ───────────────────────
def wallet_balance(results_so_far):
    return round(ex1.BUDGET + sum(r["total_pnl"] for r in results_so_far), 2)


def loss_streak(results_so_far):
    streak = 0
    for r in reversed(results_so_far):
        if r["total_pnl"] < 0:
            streak += 1
        else:
            break
    return streak


def in_drawdown(results_so_far):
    if len(results_so_far) < 2:
        return False
    window = results_so_far[-ex1.DRAWDOWN_WINDOW:]
    vals   = [ex1.BUDGET + sum(r["total_pnl"] for r in results_so_far[:i+1])
              for i in range(len(results_so_far))]
    if len(vals) < 2:
        return False
    window_vals = vals[-ex1.DRAWDOWN_WINDOW:]
    peak        = max(window_vals)
    current     = vals[-1]
    return current < peak * (1 - ex1.DRAWDOWN_THRESHOLD)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    key, secret = ex1._load_creds()
    client      = StockHistoricalDataClient(api_key=key, secret_key=secret)

    VARIANTS = [
        ("Baseline(3%)",     FE_BASELINE),
        ("Opt A (no cap)",   FE_NO_CAP),
        ("Opt B (6%)",       FE_6PCT),
        ("Opt C (TAKE*)",    find_exit_option_c),
        ("Opt D 1%>3%",      make_tight_trail(0.03, 0.01)),
        ("Opt E 1.5%>3%",    make_tight_trail(0.03, 0.015)),
        ("Opt F 1%>5%",      make_tight_trail(0.05, 0.01)),
        ("Opt G 1.5%>5%",    make_tight_trail(0.05, 0.015)),
    ]
    variant_results = {name: [] for name, _ in VARIANTS}

    print(f"\nFetching data for {len(DATES)} dates (once per date)...")
    day_cache = {}
    for date in DATES:
        day_cache[date] = fetch_day(client, date)

    print(f"\nRunning simulations...")
    for vname, fe_fn in VARIANTS:
        print(f"\n  --- {vname} ---")
        accumulated = []
        for date in DATES:
            dd = day_cache[date]
            bal     = wallet_balance(accumulated)
            streak  = loss_streak(accumulated)
            drawdn  = in_drawdown(accumulated)
            mstate  = hist_states.get(date, "neutral")

            result = simulate_day(
                date, dd["ticker_data"], dd["eod_prices"], dd["spy_by_time"],
                dd["atr_modifier"], dd["prior_closes"], mstate,
                bal, streak, drawdn, fe_fn,
            )
            accumulated.append(result)
            variant_results[vname].append(result)
            s = "+" if result["total_pnl"] >= 0 else ""
            print(f"    {date}: {s}${result['total_pnl']:.2f}  "
                  f"({result['total_trades']} trades, wallet ${bal + result['total_pnl']:,.2f})")

    # ── Comparison table ──────────────────────────────────────────────────────
    vnames = [n for n, _ in VARIANTS]
    print(f"\n{'═'*80}")
    print(f"  TAKE_PROFIT VARIANT COMPARISON — {len(DATES)} dates")
    print(f"  * Opt C: TAKE-rated = no cap, MAYBE-rated = keep +3% cap")
    print(f"{'═'*80}")
    header = f"  {'Date':<12}"
    for n in vnames:
        header += f"  {n:>14}"
    print(header)
    print("  " + "─" * (12 + len(vnames) * 16))

    totals    = {n: 0.0 for n in vnames}
    wins      = {n: 0   for n in vnames}
    tp_exits  = {n: 0   for n in vnames}

    for date in DATES:
        row = f"  {date:<12}"
        for n in vnames:
            day = next((r for r in variant_results[n] if r["date"] == date), None)
            pnl = day["total_pnl"] if day else 0.0
            totals[n] += pnl
            if pnl > 0:
                wins[n] += 1
            if day:
                tp_exits[n] += sum(1 for t in day["trades"] if t["exit_reason"] == "TAKE_PROFIT")
            row += f"  {pnl:>+13.2f}"
        print(row)

    print("  " + "─" * (12 + len(vnames) * 16))

    row = f"  {'TOTAL':<12}"
    for n in vnames:
        row += f"  {totals[n]:>+13.2f}"
    print(row)

    row = f"  {'WIN DAYS':<12}"
    for n in vnames:
        row += f"  {wins[n]:>10}/{len(DATES)}"
    print(row)

    row = f"  {'TP exits':<12}"
    for n in vnames:
        row += f"  {tp_exits[n]:>13}"
    print(row)

    baseline = totals[vnames[0]]
    row = f"  {'vs baseline':<12}"
    row += f"  {'—':>14}"
    for n in vnames[1:]:
        delta = totals[n] - baseline
        row += f"  {delta:>+13.2f}"
    print(row)

    best = max(vnames, key=lambda n: totals[n])
    print(f"\n  Best: {best}  (${totals[best]:+.2f})")
    print(f"{'═'*80}\n")

    # ── Split: live (15 days) vs backfill (38 days) ───────────────────────────
    print(f"  SPLIT: live vs backfill")
    print(f"  {'Variant':<18}  {'live $':>10}  {'live W':>7}  "
          f"{'back $':>10}  {'back W':>7}")
    print("  " + "─" * 60)
    for n in vnames:
        l_pnl = sum(r["total_pnl"] for r in variant_results[n]
                    if date_source.get(r["date"]) == "live")
        l_wins = sum(1 for r in variant_results[n]
                     if date_source.get(r["date"]) == "live" and r["total_pnl"] > 0)
        l_days = sum(1 for d in DATES if date_source.get(d) == "live")
        b_pnl = sum(r["total_pnl"] for r in variant_results[n]
                    if date_source.get(r["date"]) == "backfill")
        b_wins = sum(1 for r in variant_results[n]
                     if date_source.get(r["date"]) == "backfill" and r["total_pnl"] > 0)
        b_days = sum(1 for d in DATES if date_source.get(d) == "backfill")
        print(f"  {n:<18}  {l_pnl:>+10.2f}  {l_wins:>3}/{l_days:<3}  "
              f"{b_pnl:>+10.2f}  {b_wins:>3}/{b_days:<3}")
    print()

    # ── Per-trade breakdown for changed exits ─────────────────────────────────
    print("TRADES WHERE VARIANTS DIFFER FROM BASELINE:")
    print("─" * 80)
    for date in DATES:
        base_trades = {t["ticker"]: t for t in
                       next((r["trades"] for r in variant_results["Baseline(3%)"] if r["date"] == date), [])}
        for vname in vnames[1:]:
            var_trades = {t["ticker"]: t for t in
                          next((r["trades"] for r in variant_results[vname] if r["date"] == date), [])}
            for ticker, vt in var_trades.items():
                bt = base_trades.get(ticker)
                if bt and abs(vt["pnl"] - bt["pnl"]) > 0.01:
                    delta = vt["pnl"] - bt["pnl"]
                    print(f"  {date} {ticker:5s} [{vname}]  "
                          f"base={bt['exit_reason']:15s} {bt['pnl_pct']:+.2f}%  "
                          f"var={vt['exit_reason']:15s} {vt['pnl_pct']:+.2f}%  "
                          f"delta={delta:+.2f}")
