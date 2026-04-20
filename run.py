"""
run.py — keeps the dashboard up to date by re-fetching data every 60 seconds.

Run with: python3 run.py
Then open dashboard.html in your browser — it will auto-refresh to show the latest data.
Press Ctrl+C to stop.
"""

import time
import subprocess
from datetime import datetime

REFRESH_SECONDS = 60

print("Signal Reader — live mode")
print(f"Fetching every {REFRESH_SECONDS} seconds. Open dashboard.html in your browser.")
print("Press Ctrl+C to stop.\n")

while True:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching data...", end=" ", flush=True)
    result = subprocess.run(["python3", "fetch_data.py"], capture_output=True, text=True)
    if result.returncode == 0:
        print("Done.")
    else:
        print(f"Error: {result.stderr.strip()}")
    time.sleep(REFRESH_SECONDS)
