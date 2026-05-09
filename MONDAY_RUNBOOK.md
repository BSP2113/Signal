# Monday Live Debut — Runbook

**Date:** 2026-05-11 (Monday)
**Mode:** Alpaca paper trading (NOT real money yet)
**Goal:** validate the full live execution path with no money at risk.
**Real money cutover:** Tuesday or Wednesday, only if Monday's paper session is clean.

---

## Sunday evening (night before): pre-flight

Run these checks the night before. Each takes 30 seconds.

### 1. Telegram alerts work
```
cd /home/ben/Signal
venv/bin/python3 alerts.py
```
You should get a Telegram notification. If not, fix `.env` before Monday.

### 2. Broker connection works
```
venv/bin/python3 broker.py
```
You should see paper account info ($100K paper cash). If you see an error, check `.env`.

### 3. Live runner imports clean
```
venv/bin/python3 -c "import live_ex1; print('OK')"
```

### 4. Install the cron entries (one-time)
```
bash /home/ben/Signal/install_live_cron.sh
```
This adds 3 weekday cron entries. After running, verify:
```
crontab -l | grep "Signal Reader LIVE"
```
You should see 3 lines (09:25 start, 14:35 reconcile, 14:36 git push).

---

## Monday morning

**You don't need to do anything.** Cron handles it.

### Timeline
- **09:20** — `market_check.py` runs, writes today's market state (BULL/NEUT/BEAR)
- **09:25** — `live_ex1.py` starts. You'll get a Telegram alert: "🔔 SESSION OPEN"
- **09:30 onwards** — runner polls every 30s. When a TAKE/MAYBE signal fires, it places a market buy + stop + (MAYBE only) take-profit. You get a Telegram alert per entry.
- **As exits fire** — Telegram alerts for each: "✅ EXIT" or "❌ EXIT" with P&L.
- **14:00** — hard time-close. Every remaining position gets market-sold.
- **14:05** — "🏁 SESSION CLOSE" Telegram alert with day's totals.
- **14:30** — runner self-terminates.
- **14:35** — `reconcile_live.py` runs, compares state vs broker fills.
- **14:36** — git commits and pushes the day's state.

### What to watch for
**Green flags (expected):**
- 🔔 SESSION OPEN alert at 9:25
- 🟢 ENTRY alerts during 9:30-11:30 (typical: 4-8 per day)
- ✅ or ❌ EXIT alerts as positions close
- 🏁 SESSION CLOSE alert at ~14:05

**Yellow flags (investigate, don't panic):**
- Heartbeat alerts stop for >5 min during market hours → check that the runner is alive: `ps aux | grep live_ex1`
- An ⚠️ ERROR alert → look at the message, may need code fix
- "Daily loss limit hit" alert → expected behavior, system halts new entries for the day

**Red flags (stop the runner immediately):**
- Multiple errors back-to-back
- Positions that should have closed but haven't
- Anything that looks "stuck"

To stop the runner manually:
```
pkill -f live_ex1.py
```
Then manually close any open paper positions in the Alpaca dashboard if needed.

---

## Monday EOD: review

After 14:35, check the reconciliation output:
```
cat /home/ben/Signal/logs/reconcile.log
```

Look for:
- `✓ Broker and state agree` → perfect
- `⚠ MISMATCH` → divergence between what the system thinks happened and what actually happened. We need to investigate before going live with real money.

Also check:
```
cat /home/ben/Signal/trades_live.json
```
Shows the day's actual fills.

---

## Tuesday cutover decision (or Wednesday)

**Only flip to real money when ALL of these are true:**
1. Monday paper session ran from 9:25 → 14:30 with no ⚠️ ERROR alerts
2. At least 1 entry fired and exited cleanly
3. Reconciliation showed `✓ Broker and state agree`
4. Telegram alerts came through for every entry/exit

**If any of those failed, do NOT go to real money Tuesday.** Run paper again Tuesday and only cut over once we've had a clean session.

### To switch to real money
1. Open Alpaca dashboard → switch from paper to live keys
2. Edit `/home/ben/Signal/.env`:
   ```
   ALPACA_API_KEY=<your-LIVE-key>
   ALPACA_API_SECRET=<your-LIVE-secret>
   ALPACA_BASE_URL=https://api.alpaca.markets
   ```
3. **Confirm your Alpaca account is CASH, not margin.** Critical for PDT avoidance.
4. **Confirm $5,000 is funded** in the cash account.
5. Verify: `venv/bin/python3 broker.py` should now say `paper=False` and show your real $5K.
6. Cron handles the rest at 9:25 the next morning.

---

## Emergency procedures

### "Something is wrong, just stop everything"
```
pkill -f live_ex1.py
cd /home/ben/Signal
venv/bin/python3 -c "import broker; broker.cancel_all_open_orders()"
```
Then in Alpaca dashboard, manually close any open positions.

### "I want to skip a day"
Disable the cron entry temporarily:
```
crontab -e
# Comment out the live_ex1.py line with #
```

### "I want to switch back to paper"
Edit `.env` back to paper credentials and `https://paper-api.alpaca.markets`.

---

## What this system does NOT do (yet)

- **No EX2 features** (re-entries, PM_ORB, afternoon breakouts) — these violate cash-account settlement rules.
- **No automated reconnection** if the script crashes. Native stops + TPs at the broker will still fire to protect you, but custom exits (trail, weakness, no-progress, time-close) require the script to be running.
- **No market-state override.** Whatever `market_check.py` decides at 9:20 is final.

---

## Files involved

- `live_ex1.py` — main runner (started by cron)
- `broker.py` — Alpaca trading API wrapper
- `alerts.py` — Telegram notifications
- `reconcile_live.py` — EOD broker vs state comparison
- `live_state.json` — current session state (auto-managed)
- `trades_live.json` — EOD log of actual fills
- `logs/live_ex1.log` — runner stdout
- `logs/reconcile.log` — reconciliation output
