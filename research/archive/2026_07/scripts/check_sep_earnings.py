"""
Check: Is earnings growth (YoY) dropping one quarter before every SEP EXIT?
============================================================================
For each SEP EXIT event, look at the earnings growth in the quarter BEFORE
the EXIT date, and compare it to the quarter before that.
"""
import os, sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy_engine import parse_sep_pdfs, build_sep_signals

# --- Load earnings data ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
earnings_path = os.path.join(project_root, 'market_data', 'multpl_earnings_growth.csv')
sep_dir = os.path.join(project_root, 'fomc_sep')

earnings = pd.read_csv(earnings_path, parse_dates=['date'])
earnings = earnings.sort_values('date').reset_index(drop=True)

# --- Parse SEP and build signals ---
sep_raw = parse_sep_pdfs(sep_dir)
sep_signals = build_sep_signals(sep_raw)

# --- Find all EXIT events ---
exits = [s for s in sep_signals if s['signal'] == 'EXIT']

print("=" * 80)
print("SEP EXIT Events vs S&P 500 Earnings Growth (YoY)")
print("Question: Was earnings growth DROPPING in the quarter before SEP EXIT?")
print("=" * 80)
print()

results = []
for ex in exits:
    exit_date = pd.Timestamp(ex['date'])
    exit_quarter_end = exit_date - pd.offsets.QuarterEnd(0)  # current quarter end
    
    # Find the most recent earnings data at or before the EXIT date
    # Earnings are reported with a lag, so the "available" quarter is ~1Q before
    available = earnings[earnings['date'] <= exit_date].copy()
    
    if len(available) < 2:
        print(f"  EXIT {ex['date']}: Not enough earnings data")
        continue
    
    # Latest available quarter and the one before
    latest = available.iloc[-1]
    prev = available.iloc[-2]
    
    latest_growth = latest['earnings_growth_yoy']
    prev_growth = prev['earnings_growth_yoy']
    delta = latest_growth - prev_growth
    is_dropping = delta < 0
    
    results.append({
        'exit_date': ex['date'],
        'target_year': ex['target_year'],
        'pce': ex['pce'],
        'prev_pce': ex['prev_pce'],
        'rate': ex['rate'],
        'prev_rate': ex['prev_rate'],
        'earnings_q': str(latest['date'].date()),
        'earnings_growth': latest_growth,
        'prev_earnings_q': str(prev['date'].date()),
        'prev_earnings_growth': prev_growth,
        'delta': delta,
        'is_dropping': is_dropping,
    })
    
    drop_marker = "✅ YES dropping" if is_dropping else "❌ NO, still rising"
    print(f"SEP EXIT: {ex['date']}  (target_year={ex['target_year']})")
    print(f"  PCE: {ex['prev_pce']} → {ex['pce']}  |  Rate: {ex['prev_rate']} → {ex['rate']}")
    print(f"  Earnings Q:      {prev['date'].date()} = {prev_growth:+.2f}%")
    print(f"  Earnings Q (latest): {latest['date'].date()} = {latest_growth:+.2f}%")
    print(f"  Delta: {delta:+.2f}pp  →  {drop_marker}")
    print()

# --- Summary ---
print("=" * 80)
print("SUMMARY")
print("=" * 80)
total = len(results)
dropping = sum(1 for r in results if r['is_dropping'])
print(f"Total SEP EXIT events: {total}")
print(f"Earnings dropping one Q before: {dropping}/{total} ({100*dropping/total:.0f}%)")
print(f"Earnings NOT dropping: {total - dropping}/{total}")
print()

if dropping == total:
    print("✅ YES — every single SEP EXIT had earnings declining the quarter before.")
else:
    print("❌ NO — not every SEP EXIT had earnings declining the quarter before.")
    print("\nExceptions:")
    for r in results:
        if not r['is_dropping']:
            print(f"  {r['exit_date']}: {r['prev_earnings_q']} ({r['prev_earnings_growth']:+.2f}%) → {r['earnings_q']} ({r['earnings_growth']:+.2f}%) = {r['delta']:+.2f}pp")
