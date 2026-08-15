#!/usr/bin/env python3
"""
When SEP = OUT, what assets rise?
"""
import os, sys, warnings
import numpy as np, pandas as pd
import yfinance as yf

warnings.filterwarnings('ignore')
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))
import strategy_engine as se

DATA_DIR = os.path.join(PROJECT_DIR, 'market_data')

def gy(t):
    p = os.path.join(DATA_DIR, f'yahoo_{t}.csv')
    if os.path.exists(p):
        s = pd.read_csv(p, index_col=0, parse_dates=True).squeeze()
        if len(s) > 100: return s
    df = yf.download(t, start='2005-01-01', progress=False, auto_adjust=False)
    adj = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj, pd.DataFrame): adj = adj.iloc[:,0]
    adj.to_csv(p); return adj

print("Loading assets...")
tickers = {
    # Bonds
    'TLT':  '20Y+ Treasury',
    'IEF':  '7-10Y Treasury',
    'SHY':  '1-3Y Treasury',
    'TIP':  'TIPS (inflation)',
    'BND':  'Total Bond',
    'LQD':  'IG Corporate',
    'HYG':  'High Yield',
    # Gold / Commodities
    'GLD':  'Gold',
    'SLV':  'Silver',
    'DBC':  'Commodities',
    # Dollar
    'UUP':  'US Dollar Bull',
    # Equity alternatives
    'XLU':  'Utilities',
    'XLP':  'Consumer Staples',
    'XLV':  'Healthcare',
    'VNQ':  'REITs',
    # Inverse / Hedge
    'SH':   'Short S&P 500',
    'PSQ':  'Short QQQ',
    'SQQQ': 'Short 3x QQQ',
    # Reference
    'QQQ':  'QQQ',
    'SPY':  'S&P 500',
}

prices = {}
for t in tickers:
    try:
        prices[t] = gy(t)
    except:
        print(f"  ⚠️ {t} failed")

qqq = prices['QQQ']
idx = qqq.dropna().index; idx = idx[idx >= '2012-01-01']

sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

# Find OUT periods
out_mask = sep_state == 0
in_mask = sep_state == 1

# Find contiguous OUT periods
periods = []
in_out = False
start = None
for i, d in enumerate(idx):
    if out_mask.iloc[i] and not in_out:
        start = d; in_out = True
    elif not out_mask.iloc[i] and in_out:
        periods.append((start, idx[i-1]))
        in_out = False
if in_out:
    periods.append((start, idx[-1]))

print(f"\n  SEP OUT periods: {len(periods)}")
for s, e in periods:
    days = (e - s).days
    print(f"    {s.strftime('%Y-%m-%d')} → {e.strftime('%Y-%m-%d')} ({days}d)")

total_out = out_mask.sum()
total_in = in_mask.sum()
print(f"\n  Total: {total_out} days OUT ({total_out/len(idx)*100:.1f}%), {total_in} days IN ({total_in/len(idx)*100:.1f}%)")

# ═══════════════════════════════════════════════════
# PART 1: Average daily return during OUT vs IN
# ═══════════════════════════════════════════════════
print(f"\n{'='*110}")
print(f"  PART 1: ANNUALIZED RETURN during SEP OUT vs IN")
print(f"{'='*110}")
print(f"\n  {'Asset':<6} {'Name':<20} {'OUT ann%':>9} {'IN ann%':>9} {'OUT Sharpe':>10} {'OUT win%':>9} {'OUT cum%':>9}")
print(f"  {'─'*6} {'─'*20} {'─'*9} {'─'*9} {'─'*10} {'─'*9} {'─'*9}")

results = []
for t, name in tickers.items():
    if t not in prices: continue
    p = prices[t].reindex(idx).ffill()
    dr = p.pct_change().fillna(0)
    
    dr_out = dr[out_mask]
    dr_in = dr[in_mask]
    
    ann_out = dr_out.mean() * 252 * 100
    ann_in = dr_in.mean() * 252 * 100
    sh_out = dr_out.mean() / dr_out.std() * np.sqrt(252) if dr_out.std() > 0 else 0
    win_out = (dr_out > 0).mean() * 100
    
    # Cumulative return during all OUT periods combined
    cum_out = 1.0
    for s, e in periods:
        mask_p = (idx >= s) & (idx <= e)
        pr = p.reindex(idx[mask_p])
        if len(pr) > 1:
            cum_out *= float(pr.iloc[-1]) / float(pr.iloc[0])
    cum_out_pct = (cum_out - 1) * 100
    
    results.append((t, name, ann_out, ann_in, sh_out, win_out, cum_out_pct))

results.sort(key=lambda x: x[2], reverse=True)
for t, name, ann_out, ann_in, sh_out, win_out, cum_out in results:
    mark = ' ✅' if ann_out > 5 and sh_out > 0.3 else (' ⚠️' if ann_out > 0 else '')
    print(f"  {t:<6} {name:<20} {ann_out:>+8.1f}% {ann_in:>+8.1f}% {sh_out:>9.2f} {win_out:>8.1f}% {cum_out:>+8.1f}%{mark}")

# ═══════════════════════════════════════════════════
# PART 2: Per-period breakdown (each OUT window)
# ═══════════════════════════════════════════════════
print(f"\n{'='*110}")
print(f"  PART 2: RETURN PER OUT PERIOD")
print(f"{'='*110}")

# Top performers from Part 1
top_assets = [r[0] for r in results if r[2] > 0][:10]

hdr = f"  {'Period':<27} {'Days':>5}"
for t in top_assets:
    hdr += f" {t:>7}"
print(hdr)
print(f"  {'─'*27} {'─'*5}" + f" {'─'*7}" * len(top_assets))

for s, e in periods:
    days = (e - s).days
    line = f"  {s.strftime('%Y-%m-%d')}→{e.strftime('%Y-%m-%d')} {days:>4}d"
    for t in top_assets:
        if t not in prices: 
            line += f" {'N/A':>7}"
            continue
        p = prices[t].reindex(idx).ffill()
        mask_p = (idx >= s) & (idx <= e)
        pr = p.reindex(idx[mask_p])
        if len(pr) > 1:
            ret = (float(pr.iloc[-1]) / float(pr.iloc[0]) - 1) * 100
            line += f" {ret:>+6.1f}%"
        else:
            line += f" {'N/A':>7}"
    print(line)

# ═══════════════════════════════════════════════════
# PART 3: BEST PARKING STRATEGY
# ═══════════════════════════════════════════════════
print(f"\n{'='*110}")
print(f"  PART 3: BEST 'PARKING' DURING OUT — consistent winners")
print(f"{'='*110}")

print(f"\n  {'Asset':<6} {'Name':<20} {'Win periods':>12} {'Avg ret%':>9} {'Worst%':>8} {'Best%':>8} {'Verdict':>10}")
print(f"  {'─'*6} {'─'*20} {'─'*12} {'─'*9} {'─'*8} {'─'*8} {'─'*10}")

for t in top_assets:
    if t not in prices: continue
    name = tickers[t]
    p = prices[t].reindex(idx).ffill()
    rets = []
    for s, e in periods:
        mask_p = (idx >= s) & (idx <= e)
        pr = p.reindex(idx[mask_p])
        if len(pr) > 1:
            rets.append((float(pr.iloc[-1]) / float(pr.iloc[0]) - 1) * 100)
    if not rets: continue
    wins = sum(1 for r in rets if r > 0)
    avg = np.mean(rets)
    worst = min(rets)
    best = max(rets)
    verdict = '★ BEST' if wins == len(rets) else ('✅ GOOD' if wins >= len(rets)*0.7 else '⚠️ MIXED')
    print(f"  {t:<6} {name:<20} {wins}/{len(rets):>9} {avg:>+8.1f}% {worst:>+7.1f}% {best:>+7.1f}% {verdict:>10}")

print(f"\n  ANALYSIS COMPLETE.")
