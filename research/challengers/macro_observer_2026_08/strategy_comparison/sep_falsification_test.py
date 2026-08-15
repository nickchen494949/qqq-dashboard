#!/usr/bin/env python3
"""
Pure SEP Falsification & Robustness Test (2012-2026)
====================================================
1. Dumps every SEP date and its raw PCE/Rate values.
2. Sweeps PCE threshold and Rate Hike threshold to verify if canonical rule is overfit.
3. Includes cash yield (DFF) when OUT of market to accurately reflect real-world performance.
"""

import sys, os, csv, json
import pandas as pd, numpy as np
from datetime import timedelta
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

STATIC_DIR = os.path.join(SCRIPT_DIR, 'static_data')
DFF_JSON = os.path.join(STATIC_DIR, 'DFF.json')
QQQ_JSON = os.path.join(STATIC_DIR, 'QQQ.json')
SEP_DIR = os.path.join(PROJ_DIR, 'data', 'fomc_sep')

sys.path.insert(0, SCRIPT_DIR)
from strategy_engine import parse_sep_pdfs, build_sep_signals

def next_td(date, trading_dates):
    mask = trading_dates >= date
    return trading_dates[mask][0] if mask.any() else None

# STEP 1: Load Data
# DFF (for cash yield)
with open(DFF_JSON) as f: dff_data = json.load(f)
dff_raw = dff_data.get('values', dff_data) if isinstance(dff_data, dict) else dff_data
dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
dff['date'] = pd.to_datetime(dff['date'])
dff['dff'] = pd.to_numeric(dff['value'], errors='coerce') / 100.0 / 252.0  # Daily yield
dff = dff[['date', 'dff']].dropna().set_index('date')

# QQQ
with open(QQQ_JSON) as f: yd = json.load(f)
vals = yd.get('values', yd) if isinstance(yd, dict) else yd
qqq = pd.DataFrame(vals, columns=['date', 'close'])
qqq['date'] = pd.to_datetime(qqq['date'])
qqq['close'] = pd.to_numeric(qqq['close'], errors='coerce')
qqq = qqq.dropna().sort_values('date').reset_index(drop=True)
qqq['daily_ret'] = qqq['close'].pct_change()
qqq_dates = pd.DatetimeIndex(qqq['date'].values)

# Align DFF to QQQ dates
qqq = qqq.set_index('date')
qqq = qqq.join(dff, how='left')
qqq['dff'] = qqq['dff'].fillna(0)
qqq = qqq.reset_index()

# STEP 2: Parse SEP Base Data
sep_raw = parse_sep_pdfs(SEP_DIR)

def custom_build_sep_signals(sep_raw, pce_thresh=2.0, rate_thresh=0.0):
    sep_signals = []
    sep_in = True
    for i in range(1, len(sep_raw)):
        c, p = sep_raw[i], sep_raw[i - 1]
        ty = c['target_year']
        c_pce = c['pce_by_year'].get(ty)
        c_rate = c['rate_by_year'].get(ty)
        p_pce = p['pce_by_year'].get(ty)
        p_rate = p['rate_by_year'].get(ty)
        if c_pce is None:
            continue
        has_both = all(pd.notna(x) for x in [c_pce, c_rate, p_pce, p_rate])
        rate_up = (c_rate - p_rate) > rate_thresh if has_both else False
        pce_above = c_pce > pce_thresh
        pce_up = c_pce > p_pce if has_both else False
        is_exit = rate_up and pce_above and pce_up if has_both else False
        reenter = (c_rate <= p_rate) if has_both else False
        same_ty = (ty == p['target_year'])
        
        signal = None
        if sep_in and is_exit:
            signal = 'EXIT'; sep_in = False
        elif not sep_in and reenter:
            signal = 'ENTER'; sep_in = True
            
        sep_signals.append({
            'date': c['date'],
            'pce': c_pce, 'prev_pce': p_pce,
            'rate': c_rate, 'prev_rate': p_rate,
            'signal': signal,
        })
    return sep_signals

print("================================================================================")
print("PART 1: EVERY SEP MEETING SINCE 2012 (CANONICAL RULE)")
print("================================================================================")
canonical_signals = custom_build_sep_signals(sep_raw, pce_thresh=2.0, rate_thresh=0.0)
print(f"{'Date':<12} {'Rate':>5} {'PrevRate':>8} | {'PCE':>4} {'PrevPCE':>7} | {'Signal'}")
print("-" * 65)
for s in canonical_signals:
    date_str = s['date']
    if pd.Timestamp(date_str) < pd.Timestamp('2012-01-01'): continue
    r = f"{s['rate']:.1f}" if pd.notna(s['rate']) else "N/A"
    pr = f"{s['prev_rate']:.1f}" if pd.notna(s['prev_rate']) else "N/A"
    pce = f"{s['pce']:.1f}" if pd.notna(s['pce']) else "N/A"
    ppce = f"{s['prev_pce']:.1f}" if pd.notna(s['prev_pce']) else "N/A"
    sig = s['signal'] if s['signal'] else "-"
    print(f"{date_str:<12} {r:>5} {pr:>8} | {pce:>4} {ppce:>7} | {sig}")

# STEP 3: Parameter Sweep Engine
def run_sep_backtest(pce_thresh, rate_thresh):
    signals = custom_build_sep_signals(sep_raw, pce_thresh, rate_thresh)
    exit_dates = []
    enter_dates = []
    for r in signals:
        if r['signal'] == 'EXIT': exit_dates.append(pd.Timestamp(r['date']))
        elif r['signal'] == 'ENTER': enter_dates.append(pd.Timestamp(r['date']))
        
    canonical_exit_td = [next_td(d + timedelta(days=1), qqq_dates) for d in exit_dates]
    canonical_exit_td = set([d for d in canonical_exit_td if d is not None])
    canonical_enter_td = [next_td(d + timedelta(days=1), qqq_dates) for d in enter_dates]
    canonical_enter_td = set([d for d in canonical_enter_td if d is not None])
    
    SAMPLE_START = pd.Timestamp('2012-01-01')
    SAMPLE_END = qqq['date'].max()
    mask = (qqq['date'] >= SAMPLE_START) & (qqq['date'] <= SAMPLE_END)
    df = qqq[mask].copy()
    
    equity = 1.0; state = 'IN'
    eq_curve = []
    for _, row in df.iterrows():
        d = row['date']
        ret = row['daily_ret'] if pd.notna(row['daily_ret']) else 0.0
        cash_yield = row['dff']
        
        if state == 'IN':
            equity *= (1 + ret)
            if d in canonical_exit_td:
                state = 'OUT'
        else:
            equity *= (1 + cash_yield)
            if d in canonical_enter_td:
                state = 'IN'
        
        eq_curve.append({'date': d, 'equity': equity, 'state': state})
        
    eq_df = pd.DataFrame(eq_curve)
    eq = eq_df['equity'].values; n = len(eq); years = n / 252
    cagr = (eq[-1]/eq[0])**(1/years) - 1
    dr = np.diff(eq)/eq[:-1]
    sharpe = np.mean(dr)/np.std(dr)*np.sqrt(252) if np.std(dr)>0 else 0
    peak = np.maximum.accumulate(eq); dd = (eq-peak)/peak; mdd = dd.min()
    in_mkt = (eq_df['state']=='IN').mean()
    
    # Calculate transitions
    transitions = (eq_df['state'] != eq_df['state'].shift(1)).sum() - 1 # minus initial state
    trades = max(0, transitions // 2 + (transitions % 2))
    
    return cagr, sharpe, mdd, in_mkt, trades, exit_dates, enter_dates

print("\n================================================================================")
print("PART 2: PARAMETER SWEEP (2012-2026)")
print("================================================================================")
print(f"PCE_Thresh | Rate_Thresh |   CAGR   | Sharpe |   MDD   | InMkt | #Trades")
print("-" * 75)

# First run B&H for baseline
SAMPLE_START = pd.Timestamp('2012-01-01')
mask = (qqq['date'] >= SAMPLE_START)
bh_eq = (1 + qqq[mask]['daily_ret'].fillna(0)).cumprod().values
bh_cagr = (bh_eq[-1])**(252/len(bh_eq)) - 1
bh_dr = np.diff(bh_eq)/bh_eq[:-1]
bh_sharpe = np.mean(bh_dr)/np.std(bh_dr)*np.sqrt(252)
bh_mdd = ((bh_eq - np.maximum.accumulate(bh_eq))/np.maximum.accumulate(bh_eq)).min()
print(f"{'B&H (QQQ)':<10} | {'N/A':<11} | {bh_cagr:>7.1%} | {bh_sharpe:>6.2f} | {bh_mdd:>7.1%} | {1.0:>5.0%} | {0:>3}")

pce_grid = [1.5, 1.8, 2.0, 2.2, 2.5]
rate_grid = [-0.25, 0.0, 0.25, 0.5]

results = []
for p in pce_grid:
    for r in rate_grid:
        cagr, sharpe, mdd, inmkt, tr, exit_dates, enter_dates = run_sep_backtest(p, r)
        marker = " <=== CANONICAL" if (p == 2.0 and r == 0.0) else ""
        print(f"{p:>10.1f} | {r:>11.2f} | {cagr:>7.1%} | {sharpe:>6.2f} | {mdd:>7.1%} | {inmkt:>5.0%} | {tr:>3}{marker}")
        results.append({
            'pce': p, 'rate': r, 'trades': tr,
            'exit_dates': exit_dates, 'enter_dates': enter_dates
        })

print("\n================================================================================")
print("PART 3: TRADE LOGS BY THRESHOLD COMBINATION")
print("================================================================================")
for res in results:
    p, r = res['pce'], res['rate']
    marker = " (CANONICAL)" if (p == 2.0 and r == 0.0) else ""
    print(f"\n--- PCE > {p:.1f}%, Rate Hike > {r:.2f}% {marker} ---")
    exits = sorted([d.strftime('%Y-%m-%d') for d in res['exit_dates']])
    enters = sorted([d.strftime('%Y-%m-%d') for d in res['enter_dates']])
    
    # Simple pairing for display
    print(f"Exits:  {exits}")
    print(f"Enters: {enters}")

