"""
fetch_data.py — pulls 1-minute interval price data from Yahoo Finance and generates dashboard.html

Run with: python3 fetch_data.py
Then open dashboard.html in your browser.
Note: Yahoo Finance only provides 1-minute data for the last 7 days.
"""

import json
import yfinance as yf
from datetime import datetime

# Assets to track — add or remove tickers here
TICKERS = ["AAPL", "MSFT", "BTC-USD", "ETH-USD"]

# 1-minute data — Yahoo Finance supports up to 7 days at this resolution
PERIOD = "5d"
INTERVAL = "1m"


def fetch(ticker):
    data = yf.download(ticker, period=PERIOD, interval=INTERVAL, progress=False, auto_adjust=True)
    if data.empty:
        print(f"  Warning: no data returned for {ticker}")
        return None
    dates = [str(d) for d in data.index]
    closes = [round(float(v), 2) for v in data["Close"].squeeze().tolist()]
    volumes = [int(v) for v in data["Volume"].squeeze().tolist()]
    return {"ticker": ticker, "dates": dates, "closes": closes, "volumes": volumes}


def detect_signals(asset):
    """Flag 1-minute candles where price moved >1% or volume spiked >2x average."""
    signals = []
    closes = asset["closes"]
    volumes = asset["volumes"]
    dates = asset["dates"]
    avg_volume = sum(volumes) / len(volumes) if volumes else 1

    for i in range(1, len(closes)):
        if closes[i - 1] == 0:
            continue
        price_change = abs(closes[i] - closes[i - 1]) / closes[i - 1]
        volume_spike = volumes[i] > avg_volume * 2

        if price_change > 0.01 or volume_spike:
            direction = "UP" if closes[i] > closes[i - 1] else "DOWN"
            reason = []
            if price_change > 0.01:
                reason.append(f"price moved {price_change:.2%} {direction}")
            if volume_spike:
                reason.append(f"volume {volumes[i]:,} vs avg {avg_volume:,.0f}")
            signals.append({"date": dates[i], "reason": ", ".join(reason), "direction": direction})

    return signals


def build_dashboard(assets):
    cards = ""
    charts_js = ""

    for asset in assets:
        ticker = asset["ticker"]
        signals = detect_signals(asset)
        signal_rows = "".join(
            f'<tr class="signal-{s["direction"].lower()}">'
            f'<td>{s["date"]}</td><td>{s["direction"]}</td><td>{s["reason"]}</td></tr>'
            for s in signals
        ) or "<tr><td colspan='3'>No signals detected</td></tr>"

        cards += f"""
        <div class="card">
            <h2>{ticker}</h2>
            <div class="chart-wrap">
                <canvas id="chart-{ticker}"></canvas>
            </div>
            <button class="reset-btn" onclick="resetZoom('{ticker}')">Reset Zoom</button>
            <h3>Signals</h3>
            <table>
                <thead><tr><th>Date</th><th>Direction</th><th>Reason</th></tr></thead>
                <tbody>{signal_rows}</tbody>
            </table>
        </div>
        """

        labels = json.dumps(asset["dates"])
        prices = json.dumps(asset["closes"])
        volumes = json.dumps(asset["volumes"])

        charts_js += f"""
        (function() {{
            var ctx = document.getElementById('chart-{ticker}').getContext('2d');
            charts['{ticker}'] = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: {labels},
                    datasets: [{{
                        label: '{ticker} Close Price',
                        data: {prices},
                        borderColor: '#4f8ef7',
                        backgroundColor: 'rgba(79,142,247,0.1)',
                        tension: 0.2,
                        pointRadius: 3,
                        yAxisID: 'y'
                    }}, {{
                        label: 'Volume',
                        data: {volumes},
                        type: 'bar',
                        backgroundColor: 'rgba(150,150,150,0.3)',
                        yAxisID: 'y2'
                    }}]
                }},
                options: {{
                    responsive: true,
                    interaction: {{ mode: 'index', intersect: false }},
                    scales: {{
                        y: {{ position: 'left', title: {{ display: true, text: 'Price (USD)' }} }},
                        y2: {{ position: 'right', grid: {{ drawOnChartArea: false }}, title: {{ display: true, text: 'Volume' }} }}
                    }},
                    plugins: {{
                        zoom: {{
                            zoom: {{ wheel: {{ enabled: true }}, pinch: {{ enabled: true }}, mode: 'x' }},
                            pan: {{ enabled: true, mode: 'x' }}
                        }}
                    }}
            }});
        }})();
        """

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="60">
    <title>Signal Reader Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@1.2.1/dist/chartjs-plugin-zoom.min.js"></script>
    <style>
        body {{ font-family: sans-serif; background: #0f0f1a; color: #e0e0e0; margin: 0; padding: 20px; }}
        h1 {{ color: #4f8ef7; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(600px, 1fr)); gap: 24px; }}
        .card {{ background: #1a1a2e; border-radius: 10px; padding: 20px; }}
        h2 {{ margin-top: 0; color: #7eb8f7; }}
        h3 {{ color: #aaa; font-size: 0.9em; margin-top: 20px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
        th {{ text-align: left; color: #888; padding: 4px 8px; border-bottom: 1px solid #333; }}
        td {{ padding: 4px 8px; }}
        .signal-up {{ color: #4caf50; }}
        .signal-down {{ color: #f44336; }}
        .meta {{ color: #555; font-size: 0.8em; margin-top: 30px; }}
        .reset-btn {{ margin-top: 8px; background: #2a2a4a; color: #7eb8f7; border: 1px solid #4f8ef7; border-radius: 5px; padding: 4px 12px; cursor: pointer; font-size: 0.8em; }}
        .reset-btn:hover {{ background: #4f8ef7; color: #fff; }}
    </style>
</head>
<body>
    <h1>Signal Reader Dashboard</h1>
    <p>Tracking: {", ".join(TICKERS)} &nbsp;|&nbsp; Interval: {INTERVAL} &nbsp;|&nbsp; Period: {PERIOD}</p>
    <div class="grid">{cards}</div>
    <p class="meta">Generated: {generated} — auto-refreshes every 60 seconds (keep run.py running)</p>
    <script>
        var charts = {{}};
        function resetZoom(ticker) {{ charts[ticker].resetZoom(); }}
        {charts_js}
    </script>
</body>
</html>"""


if __name__ == "__main__":
    print(f"Fetching data for: {', '.join(TICKERS)}")
    assets = []
    for ticker in TICKERS:
        print(f"  Downloading {ticker}...")
        result = fetch(ticker)
        if result:
            assets.append(result)

    if not assets:
        print("No data fetched. Check your internet connection.")
    else:
        html = build_dashboard(assets)
        with open("dashboard.html", "w") as f:
            f.write(html)
        print(f"\nDone! Open Signal-Reader/dashboard.html in your browser.")
        print(f"Signals flagged when price moves >5% or volume spikes >1.5x average.")
