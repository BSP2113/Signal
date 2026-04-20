# CLAUDE.md — Project Context & Goals

## About Me

I have limited coding knowledge. Please explain technical decisions in plain English when relevant. Prefer simple, readable code over clever solutions. Always tell me what you're doing and why.

## Project Goal

Build a **market signal spotter** — a tool that pulls live and historical pricing data from financial APIs, identifies trends, and flags potential buy/sell opportunities.

This is a **monitoring and analysis tool first**. Automated trade execution is a future consideration only after signals are validated over time.

## Phase 1 — Signal Spotter (Current Focus)

### What to build:

- Connect to one or more financial data APIs (see below)
- Pull live and historical price data
- Visualize price trends over time (charts in browser)
- Flag unusual price movements (e.g. sudden spikes in volume or price)
- Track multiple assets in one dashboard

### APIs to use:

- **Yahoo Finance** — no API key needed, good for stocks, start here
- **Alpha Vantage** — free tier, stocks and crypto, requires free API key
- **Coinbase API** — for crypto data
- **Alpaca** — best option if/when we move to paper trading or live trading

### Do NOT build yet:

- Automated trade execution
- Live order placement
- Any connection to real brokerage accounts

## Phase 2 — Paper Trading (Future)

Once signals have been monitored and validated over several weeks:

- Connect to Alpaca paper trading (simulated trades, no real money)
- Test whether signals actually predict price movements
- Only consider live trading after paper trading proves consistent results

## Tech Approach

- Keep dependencies minimal
- Output should be viewable in a browser (HTML dashboard or similar)
- Store data locally for now — no database required initially
- Use Python or JavaScript, whichever is simpler for each task

## GitHub

- All code should be version controlled with git
- Commit regularly with descriptive messages
- Push to GitHub so the project is accessible across devices

## Key Reminders

- Always explain what an API key is and where to get one before assuming I have it
- Warn me before making any changes that could cost money or place real trades
- Prefer paper trading and simulation over anything touching real funds
- When in doubt, build the simpler version first and iterate
