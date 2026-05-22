#!/usr/bin/env python3
"""Build ex1_reval.py — a faithful copy of ex1.py with the 7 shipped logic
rules each placed behind a REVAL_FLAGS toggle (all default True = shipped
behaviour). Aborts loudly if any anchor doesn't match exactly once.
"""
SRC = "/home/ben/Signal/ex1.py"
DST = "/home/ben/Signal/ex1_reval.py"

content = open(SRC).read()

REPLACEMENTS = [
    ("REVAL_FLAGS dict",
     'ET          = "America/New_York"',
     'ET          = "America/New_York"\n'
     '\n'
     '# Re-validation toggles (Phase B2). All True = shipped behaviour; the\n'
     '# re-validation driver flips one False at a time to measure each rule.\n'
     'REVAL_FLAGS = {\n'
     '    "confirm_bar":       True,\n'
     '    "two_bar_trail":     True,\n'
     '    "take_no_cap":       True,\n'
     '    "no_progress":       True,\n'
     '    "early_weak":        True,\n'
     '    "pre10_take_block":  True,\n'
     '    "post11_take_block": True,\n'
     '}'),
    ("confirm-bar exit",
     '        if large_gap and i == entry_bar + 1 and highs and lows:',
     '        if REVAL_FLAGS["confirm_bar"] and large_gap and i == entry_bar + 1 and highs and lows:'),
    ("2-bar trail arm",
     '        if consec_above >= 2:',
     '        if consec_above >= (2 if REVAL_FLAGS["two_bar_trail"] else 1):'),
    ("TAKE no-cap",
     '        if rating != "TAKE" and price >= entry_price * (1 + TAKE_PROFIT):',
     '        if ((rating != "TAKE") or not REVAL_FLAGS["take_no_cap"]) and price >= entry_price * (1 + TAKE_PROFIT):'),
    ("no-progress exit",
     '        if not t90_passed and bar_mins >= t90_mins and t90_mins <= 14 * 60:',
     '        if REVAL_FLAGS["no_progress"] and not t90_passed and bar_mins >= t90_mins and t90_mins <= 14 * 60:'),
    ("early-weak exit",
     '        if ticker not in EARLY_WEAK_SKIP and not tew_passed and bar_mins >= tew_mins:',
     '        if REVAL_FLAGS["early_weak"] and ticker not in EARLY_WEAK_SKIP and not tew_passed and bar_mins >= tew_mins:'),
    ("pre-10:00 TAKE block",
     '                if rating == "TAKE" and times[i] < "10:00":',
     '                if REVAL_FLAGS["pre10_take_block"] and rating == "TAKE" and times[i] < "10:00":'),
    ("post-11:00 TAKE block",
     '                if rating == "TAKE" and times[i] >= "11:00":',
     '                if REVAL_FLAGS["post11_take_block"] and rating == "TAKE" and times[i] >= "11:00":'),
]

for label, old, new in REPLACEMENTS:
    n = content.count(old)
    assert n == 1, f"FAIL: '{label}' anchor matched {n} times (need exactly 1)"
    content = content.replace(old, new)
    print(f"  ok: {label}")

with open(DST, "w") as f:
    f.write(content)
print(f"\nWrote {DST}  ({content.count(chr(10))+1} lines)")
