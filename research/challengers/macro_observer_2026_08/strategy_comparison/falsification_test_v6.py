#!/usr/bin/env python3
"""
Historical Falsification Test v6.1 — Exhaustive Episode Table
========================================================
Runs every Hawkish pulse independently as a virtual trade.
"""

import sys, os, csv, json, urllib.request
import pandas as pd, numpy as np
from datetime import timedelta
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
KW_CSV = os.path.join(SCRIPT_DIR, 'static_data', 'kw_feds200533_snapshot.csv')

# STEP 1: Load data
print("Loading data...")
with open(KW_CSV, 'r', encoding='utf-8') as f:
    lines = f.read().strip().split('\n')
header_idx = next(i for i, l in enumerate(lines) if l.startswith('Date,'))
reader = csv.DictReader(lines[header_idx:])
kw_rows = []
for row in reader:
    try:
        kw_rows.append({'date': row['Date'], 'fwd_1y': float(row['THREEFF0100.B']),
                        'tp_1y': float(row['THREEFFTP0100.B'])})
    except: continue
kw = pd.DataFrame(kw_rows); kw['date'] = pd.to_datetime(kw['date'])
kw['exp_short_1y'] = kw['fwd_1y'] - kw['tp_1y']
kw = kw.sort_values('date').reset_index(drop=True)

dff_json = os.path.join(SCRIPT_DIR, 'static_data', 'DFF.json')
with open(dff_json) as f: dff_data = json.load(f)
dff_raw = dff_data.get('values', dff_data) if isinstance(dff_data, dict) else dff_data
dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
dff['date'] = pd.to_datetime(dff['date']); dff['dff'] = pd.to_numeric(dff['value'], errors='coerce')
dff = dff[['date', 'dff']].dropna()

merged = pd.merge(kw[['date','exp_short_1y']], dff[['date','dff']], on='date', how='inner')
merged = merged.sort_values('date').reset_index(drop=True)
merged['hawkish_path'] = merged['exp_short_1y'] - merged['dff']
merged['delta_exp_4w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(20)
merged['is_strong_hawk'] = (merged['hawkish_path'] > 0.5) & (merged['delta_exp_4w'] > 0.25)

ypath = os.path.join(SCRIPT_DIR, 'static_data', 'QQQ.json')
if os.path.exists(ypath):
    with open(ypath) as f: yd = json.load(f)
    vals = yd.get('values', yd) if isinstance(yd, dict) else yd
    qqq = pd.DataFrame(vals, columns=['date', 'close'])
    qqq['date'] = pd.to_datetime(qqq['date']); qqq['close'] = pd.to_numeric(qqq['close'], errors='coerce')

qqq = qqq.dropna().sort_values('date').reset_index(drop=True)
qqq['daily_ret'] = qqq['close'].pct_change()
qqq_dates = pd.DatetimeIndex(qqq['date'].values)

eps_path = os.path.join(PROJ_DIR, 'data', 'valuation', 'SP500_EPS.json')
with open(eps_path) as f: eps_data = json.load(f)
eps_vals = eps_data if isinstance(eps_data, list) else eps_data.get('values', [])
eps_df = pd.DataFrame(eps_vals, columns=['date', 'eps'])
eps_df['date'] = pd.to_datetime(eps_df['date'])
eps_df['eps'] = pd.to_numeric(eps_df['eps'], errors='coerce')
eps_df = eps_df.dropna().sort_values('date').reset_index(drop=True)
eps_df['eps_12m'] = eps_df['eps'].rolling(4, min_periods=4).sum()
eps_df['eps_mom_6m'] = eps_df['eps'].pct_change(6) * 100

# STEP 2: Build daily signals
def next_td(date, trading_dates):
    mask = trading_dates >= date
    return trading_dates[mask][0] if mask.any() else None

def kw_pub_tuesday(obs_date):
    wd = obs_date.weekday()
    friday = obs_date + timedelta(days=(4 - wd) % 7)
    return friday + timedelta(days=4)

hawk_daily = merged[['date','hawkish_path','delta_exp_4w','is_strong_hawk']].copy()
hawk_daily['pub_date'] = hawk_daily['date'].apply(kw_pub_tuesday)
hawk_daily['trade_date'] = hawk_daily['pub_date'].apply(lambda d: next_td(d, qqq_dates))
hawk_daily = hawk_daily.dropna(subset=['trade_date'])

hawk_signal_series = {}
for _, row in hawk_daily.iterrows():
    td = row['trade_date']
    if td not in hawk_signal_series or row['date'] > hawk_signal_series[td]['obs_date']:
        hawk_signal_series[td] = {'obs_date': row['date'], 'hp': row['hawkish_path'],
                                   'is_strong': row['is_strong_hawk']}

hawk_ff = pd.DataFrame(index=qqq['date'])
hawk_ff['hawk_hp'] = np.nan; hawk_ff['hawk_strong_raw'] = False
last_hp = np.nan; last_strong = False
for date in qqq['date']:
    if date in hawk_signal_series:
        last_hp = hawk_signal_series[date]['hp']
        last_strong = hawk_signal_series[date]['is_strong']
    hawk_ff.loc[date, 'hawk_hp'] = last_hp
    hawk_ff.loc[date, 'hawk_strong_raw'] = last_strong
hawk_ff['hawk_strong_prev'] = hawk_ff['hawk_strong_raw'].shift(1).fillna(False)
hawk_ff['hawk_strong_pulse'] = hawk_ff['hawk_strong_raw'] & ~hawk_ff['hawk_strong_prev']

eps_ff = pd.DataFrame(index=qqq['date'])
eps_ff['eps_mom_6m'] = np.nan
for _, row in eps_df.iterrows():
    # Simulated 45-day publication lag to ensure point-in-time availability
    pub_date = row['date'] + timedelta(days=45)
    td = next_td(pub_date, qqq_dates)
    if td is not None and pd.notna(row['eps_mom_6m']):
        eps_ff.loc[td, 'eps_mom_6m'] = row['eps_mom_6m']
eps_ff['eps_mom_6m'] = eps_ff['eps_mom_6m'].ffill()

# STEP 3: Virtual Trade Engine
EPS_THRESHOLD = -3.0

def evaluate_pulse(pulse_date, qqq_df, eps_ff, hawk_ff):
    exit_mask = qqq_df['date'] >= pulse_date
    if not exit_mask.any(): return None
    exit_idx = qqq_df[exit_mask].index[0]
    exit_date = qqq_df.loc[exit_idx, 'date']
    exit_price = qqq_df.loc[exit_idx, 'close']
    
    eps_at_exit = eps_ff.loc[exit_date, 'eps_mom_6m'] if exit_date in eps_ff.index else np.nan
    is_late_arrival = pd.notna(eps_at_exit) and eps_at_exit <= EPS_THRESHOLD
    classification = "Late (House on Fire)" if is_late_arrival else "Early Warning"
    
    eps_was_above_since_exit = False if is_late_arrival else (pd.notna(eps_at_exit) and eps_at_exit > EPS_THRESHOLD)
    
    entry_date, entry_price, entry_reason, entry_idx = None, None, None, None
    
    for idx in range(exit_idx + 1, len(qqq_df)):
        curr_date = qqq_df.loc[idx, 'date']
        curr_price = qqq_df.loc[idx, 'close']
        
        hawk = hawk_ff.loc[curr_date] if curr_date in hawk_ff.index else pd.Series({'hawk_hp': np.nan})
        eps_mom = eps_ff.loc[curr_date, 'eps_mom_6m'] if curr_date in eps_ff.index else np.nan
        
        if pd.notna(eps_mom) and eps_mom > EPS_THRESHOLD:
            eps_was_above_since_exit = True
            
        if is_late_arrival:
            if pd.notna(eps_mom) and eps_mom > EPS_THRESHOLD:
                entry_date, entry_price, entry_reason, entry_idx = curr_date, curr_price, 'EPS_RECOVERY', idx
                break
        else:
            if eps_was_above_since_exit and pd.notna(eps_mom) and eps_mom <= EPS_THRESHOLD:
                entry_date, entry_price, entry_reason, entry_idx = curr_date, curr_price, 'EPS_NEW', idx
                break
            
            hp = hawk['hawk_hp']
            if pd.notna(hp) and hp < 0.5:
                entry_date, entry_price, entry_reason, entry_idx = curr_date, curr_price, 'HAWK_NORMALIZE', idx
                break
                
    if entry_date is None:
        entry_date, entry_price, entry_reason, entry_idx = qqq_df['date'].iloc[-1], qqq_df['close'].iloc[-1], 'STILL_OUT', len(qqq_df) - 1
        
    days_out = (entry_date - exit_date).days
    bh_return = entry_price / exit_price - 1
    
    out_slice = qqq_df.loc[exit_idx:entry_idx, 'close']
    min_price = out_slice.min()
    max_price = out_slice.max()
    avoided_dd = (min_price - exit_price) / exit_price
    missed_up = (max_price - exit_price) / exit_price
    
    sub_3m_ret, sub_6m_ret = np.nan, np.nan
    if entry_idx + 63 < len(qqq_df):
        sub_3m_ret = qqq_df.loc[entry_idx + 63, 'close'] / entry_price - 1
    if entry_idx + 126 < len(qqq_df):
        sub_6m_ret = qqq_df.loc[entry_idx + 126, 'close'] / entry_price - 1
        
    return {
        'pulse_date': pulse_date,
        'eps_at_exit': eps_at_exit,
        'classification': classification,
        're_entry_date': entry_date,
        'reason': entry_reason,
        'days_out': days_out,
        'bh_return': bh_return,
        'avoided_dd': avoided_dd,
        'missed_up': missed_up,
        'sub_3m': sub_3m_ret,
        'sub_6m': sub_6m_ret
    }

pulses = hawk_ff[hawk_ff['hawk_strong_pulse']].index.tolist()
results = []
for p in pulses:
    if p >= pd.Timestamp('2000-01-01'):
        res = evaluate_pulse(p, qqq, eps_ff, hawk_ff)
        if res: results.append(res)

print(f"{'Pulse Date':>10} | {'EPS@Exit':>9} | {'Class':>15} | {'Re-entry':>10} | {'Reason':>15} | {'Days':>4} | {'B&H':>7} | {'AvoidDD':>7} | {'MissUp':>7} | {'Sub3M':>7} | {'Sub6M':>7}")
print("-" * 125)
for r in results:
    eps_str = f"{r['eps_at_exit']:+.1f}%" if pd.notna(r['eps_at_exit']) else "N/A"
    c_str = "Late" if "Late" in r['classification'] else "Early"
    s3 = f"{r['sub_3m']:+.1%}" if pd.notna(r['sub_3m']) else "N/A"
    s6 = f"{r['sub_6m']:+.1%}" if pd.notna(r['sub_6m']) else "N/A"
    print(f"{r['pulse_date'].strftime('%Y-%m-%d'):>10} | {eps_str:>9} | {c_str:>15} | {r['re_entry_date'].strftime('%Y-%m-%d'):>10} | {r['reason']:>15} | {r['days_out']:>4} | {r['bh_return']:>+7.1%} | {r['avoided_dd']:>+7.1%} | {r['missed_up']:>+7.1%} | {s3:>7} | {s6:>7}")
