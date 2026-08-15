#!/usr/bin/env python3
"""
Fed Hawkish Path Backtest — v2 (Corrected)
==========================================
Fixes from v1:
1. DFF from FRED (actual effective rate), NOT derived from ZQ=F futures
2. Danger zone uses ΔExpectedRate_1Y (not ΔHP) to avoid confounding
   crisis normalization with true hawkish repricing
3. SPY (1993+) and QQQ (1999+) date ranges validated
4. Episode classification cleaned up

Signal:
  ExpectedShortRate_1Y = THREEFF0100.B - THREEFFTP0100.B
  HawkishPath = ExpectedShortRate_1Y - DFF

Corrected Danger Zone:
  HP > 0.50%
  AND ΔExpectedRate_1Y_4w > 0.25%  (expected rate ITSELF rose, not just the gap)

This isolates: "market is actively repricing future rates HIGHER"
and filters out: "Fed just emergency-cut, expected rate didn't change"
"""

import urllib.request
import csv
import io
import json
import os
import datetime
import sys

import pandas as pd
import numpy as np

# ─── CONFIG ──────────────────────────────────────────────────────
DASHBOARD_DIR = '/Users/happygolucky/projects/宏观观察器'
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
KW_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200533.csv"

# ─── 1. DOWNLOAD KIM-WRIGHT DATA ────────────────────────────────
print("=" * 60)
print("STEP 1: Download Kim-Wright Model Data")
print("=" * 60)

req = urllib.request.Request(KW_URL, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=30)
raw = resp.read().decode('utf-8')
lines = raw.strip().split('\n')

header_idx = None
for i, l in enumerate(lines):
    if l.startswith('Date,'):
        header_idx = i
        break

if header_idx is None:
    print("ERROR: Could not find header in Kim-Wright CSV")
    sys.exit(1)

reader = csv.DictReader(lines[header_idx:])
kw_rows = []
for row in reader:
    try:
        date = row['Date']
        ff0100 = float(row['THREEFF0100.B'])
        tp0100 = float(row['THREEFFTP0100.B'])
        kw_rows.append({'date': date, 'fwd_1y': ff0100, 'tp_1y': tp0100})
    except (ValueError, KeyError):
        continue

kw = pd.DataFrame(kw_rows)
kw['date'] = pd.to_datetime(kw['date'])
kw = kw.sort_values('date').reset_index(drop=True)
kw['exp_short_1y'] = kw['fwd_1y'] - kw['tp_1y']

print(f"  Kim-Wright: {len(kw)} rows, {kw['date'].min().date()} → {kw['date'].max().date()}")

# ─── 2. LOAD DFF (Effective Fed Funds Rate) FROM FRED ────────────
print("\nSTEP 2: Load DFF (Effective Federal Funds Rate) from FRED")
print("=" * 60)

dff = None
# Try dashboard JSON
dff_json = os.path.join(DASHBOARD_DIR, 'data', 'fred', 'DFF.json')
if os.path.exists(dff_json):
    with open(dff_json) as f:
        dff_data = json.load(f)
    if isinstance(dff_data, dict) and 'values' in dff_data:
        dff_raw = dff_data['values']
    elif isinstance(dff_data, list):
        dff_raw = dff_data
    else:
        dff_raw = []
    dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
    dff['date'] = pd.to_datetime(dff['date'])
    dff['dff'] = pd.to_numeric(dff['value'], errors='coerce')
    dff = dff[['date', 'dff']].dropna()
    print(f"  DFF (dashboard JSON): {len(dff)} rows, {dff['date'].min().date()} → {dff['date'].max().date()}")

if dff is None or len(dff) == 0:
    # Try dashboard CSV
    dff_csv = os.path.join(DASHBOARD_DIR, 'csv', 'fred', 'DFF.csv')
    if os.path.exists(dff_csv):
        dff = pd.read_csv(dff_csv)
        cols = dff.columns.tolist()
        date_col = [c for c in cols if 'date' in c.lower() or 'Date' in c][0]
        val_col = [c for c in cols if c != date_col][0]
        dff = dff.rename(columns={date_col: 'date', val_col: 'dff'})
        dff['date'] = pd.to_datetime(dff['date'])
        dff['dff'] = pd.to_numeric(dff['dff'], errors='coerce')
        dff = dff[['date', 'dff']].dropna()
        print(f"  DFF (dashboard CSV): {len(dff)} rows")

if dff is None or len(dff) == 0:
    # Fallback: FRED direct download
    print("  Downloading DFF from FRED...")
    fred_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF&cosd=1990-01-01"
    req2 = urllib.request.Request(fred_url, headers={'User-Agent': 'Mozilla/5.0'})
    resp2 = urllib.request.urlopen(req2, timeout=30)
    dff_text = resp2.read().decode('utf-8')
    dff = pd.read_csv(io.StringIO(dff_text))
    dff.columns = ['date', 'dff']
    dff['date'] = pd.to_datetime(dff['date'])
    dff['dff'] = pd.to_numeric(dff['dff'], errors='coerce')
    dff = dff.dropna()
    print(f"  DFF (FRED download): {len(dff)} rows, {dff['date'].min().date()} → {dff['date'].max().date()}")

print(f"  NOTE: DFF = Effective Federal Funds Rate (overnight interbank rate)")
print(f"        This is NOT derived from ZQ=F futures. It is the actual realized rate.")

# ─── 3. LOAD SPY & QQQ ──────────────────────────────────────────
print("\nSTEP 3: Load Equity Data (SPY, QQQ)")
print("=" * 60)

import yfinance as yf

# Known inception dates
INCEPTION = {'SPY': '1993-01-29', 'QQQ': '1999-03-10'}

equities = {}
for ticker in ['SPY', 'QQQ']:
    inception = pd.Timestamp(INCEPTION[ticker])
    
    # Try dashboard data first
    ypath = os.path.join(DASHBOARD_DIR, 'data', 'yahoo', f'{ticker}.json')
    if os.path.exists(ypath):
        with open(ypath) as f:
            yd = json.load(f)
        vals = yd.get('values', yd) if isinstance(yd, dict) else yd
        edf = pd.DataFrame(vals, columns=['date', 'close'])
        edf['date'] = pd.to_datetime(edf['date'])
        edf['close'] = pd.to_numeric(edf['close'], errors='coerce')
        edf = edf.dropna()
    else:
        print(f"  Downloading {ticker} from Yahoo...")
        raw_df = yf.download(ticker, start='1990-01-01', progress=False)
        edf = raw_df[['Close']].reset_index()
        edf.columns = ['date', 'close']
        edf['date'] = pd.to_datetime(edf['date']).dt.tz_localize(None)
    
    # Filter to actual inception date
    edf = edf[edf['date'] >= inception]
    equities[ticker] = edf.sort_values('date').reset_index(drop=True)
    print(f"  {ticker}: {len(equities[ticker])} rows, "
          f"{equities[ticker]['date'].min().date()} → {equities[ticker]['date'].max().date()}"
          f" (inception: {INCEPTION[ticker]})")

# ─── 4. MERGE & COMPUTE SIGNALS ─────────────────────────────────
print("\nSTEP 4: Merge & Compute Corrected Signals")
print("=" * 60)

merged = pd.merge(kw[['date', 'exp_short_1y', 'fwd_1y', 'tp_1y']], 
                   dff[['date', 'dff']], on='date', how='inner')
merged = merged.sort_values('date').reset_index(drop=True)

# Core signal: HawkishPath = expected 1Y rate - current fed funds rate
merged['hawkish_path'] = merged['exp_short_1y'] - merged['dff']

# CORRECTED: Use Δ of Expected Rate itself (not ΔHP)
# This isolates true hawkish repricing from crisis normalization
merged['delta_exp_4w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(20)
merged['delta_exp_8w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(40)
# Also track DFF changes for diagnostics
merged['delta_dff_4w'] = merged['dff'] - merged['dff'].shift(20)
# Old (flawed) ΔHP for comparison
merged['delta_hp_4w'] = merged['hawkish_path'] - merged['hawkish_path'].shift(20)

print(f"  Merged: {len(merged)} rows, {merged['date'].min().date()} → {merged['date'].max().date()}")
print(f"\n  Signal stats:")
print(f"    HP mean: {merged['hawkish_path'].mean():.3f}%")
print(f"    HP std:  {merged['hawkish_path'].std():.3f}%")
print(f"    ΔExp1Y_4w mean: {merged['delta_exp_4w'].mean():.4f}%, std: {merged['delta_exp_4w'].std():.3f}%")

# ─── 5. COMPUTE FORWARD RETURNS ─────────────────────────────────
print("\nSTEP 5: Compute Forward Returns & MDD")
print("=" * 60)

horizons = {'1M': 21, '3M': 63, '6M': 126, '12M': 252}

for ticker_name, edf in equities.items():
    df = pd.merge(merged[['date', 'hawkish_path', 'delta_exp_4w', 'delta_exp_8w',
                           'delta_dff_4w', 'delta_hp_4w', 'exp_short_1y', 'dff']], 
                   edf[['date', 'close']], on='date', how='inner')
    df = df.sort_values('date').reset_index(drop=True)
    
    for label, days in horizons.items():
        df[f'fwd_{label}'] = df['close'].shift(-days) / df['close'] - 1
    
    for label, days in horizons.items():
        mdd_vals = []
        for i in range(len(df)):
            if i + days >= len(df):
                mdd_vals.append(np.nan)
                continue
            future_prices = df['close'].iloc[i:i+days+1].values
            peak = future_prices[0]
            max_dd = 0
            for p in future_prices[1:]:
                peak = max(peak, p)
                dd = (p - peak) / peak
                max_dd = min(max_dd, dd)
            mdd_vals.append(max_dd)
        df[f'mdd_{label}'] = mdd_vals
    
    equities[ticker_name] = df
    print(f"  {ticker_name}: {len(df)} merged rows, "
          f"{df['date'].min().date()} → {df['date'].max().date()}")

# ─── 6. REGIME ANALYSIS ─────────────────────────────────────────
print("\nSTEP 6: Regime Analysis (Corrected)")
print("=" * 60)
print("  CRITICAL FIX: 'Strongly Hawkish' now requires ΔExpectedRate_1Y > 0.25%")
print("  This filters out crisis normalization (DFF drops → HP rises mechanically)")

regime_defs = {
    # ── CORRECTED regimes (using ΔExp1Y) ──
    'Hawkish_v2 (HP>0 & ΔExp1Y_4w>0)': 
        lambda d: (d['hawkish_path'] > 0) & (d['delta_exp_4w'] > 0),
    'StrongHawkish_v2 (HP>0.5 & ΔExp1Y_4w>0.25)': 
        lambda d: (d['hawkish_path'] > 0.5) & (d['delta_exp_4w'] > 0.25),
    'StrongHawkish_v2_strict (HP>0.5 & ΔExp1Y_4w>0.25 & ΔDFF≥0)':
        lambda d: (d['hawkish_path'] > 0.5) & (d['delta_exp_4w'] > 0.25) & (d['delta_dff_4w'] >= 0),
    # ── OLD (flawed) regime for comparison ──
    'StrongHawkish_v1_OLD (HP>0.5 & ΔHP_4w>0.25)': 
        lambda d: (d['hawkish_path'] > 0.5) & (d['delta_hp_4w'] > 0.25),
    # ── Context regimes ──
    'Dovish (HP<0)': lambda d: d['hawkish_path'] < 0,
    'Dovish Shift (HP<0 & ΔExp1Y_4w<-0.25)': 
        lambda d: (d['hawkish_path'] < 0) & (d['delta_exp_4w'] < -0.25),
    'Neutral (|HP|<0.25)': lambda d: d['hawkish_path'].abs() < 0.25,
    'All': lambda d: pd.Series(True, index=d.index),
}

results = []
for ticker_name, df in equities.items():
    for regime_name, regime_fn in regime_defs.items():
        mask = regime_fn(df) & df['fwd_1M'].notna()
        n = mask.sum()
        if n < 5:
            continue
        
        row = {
            'Ticker': ticker_name,
            'Regime': regime_name,
            'N_days': n,
            'Pct_time': f"{100*n/mask.notna().sum():.1f}%",
        }
        
        for label in horizons:
            fwd_col = f'fwd_{label}'
            mdd_col = f'mdd_{label}'
            subset = df.loc[mask]
            valid = subset[fwd_col].dropna()
            row[f'{label}_mean'] = valid.mean() if len(valid) > 0 else np.nan
            row[f'{label}_median'] = valid.median() if len(valid) > 0 else np.nan
            row[f'{label}_hit_neg'] = (valid < 0).mean() if len(valid) > 0 else np.nan
            valid_mdd = subset[mdd_col].dropna()
            row[f'{label}_mdd_mean'] = valid_mdd.mean() if len(valid_mdd) > 0 else np.nan
            row[f'{label}_mdd_p10'] = valid_mdd.quantile(0.10) if len(valid_mdd) > 0 else np.nan
        
        results.append(row)

results_df = pd.DataFrame(results)

# ─── 7. PRINT RESULTS ───────────────────────────────────────────
print("\n" + "=" * 80)
print("RESULTS: Fed Hawkish Path (v2 Corrected) & Equity Forward Returns")
print("=" * 80)
print(f"Signal: HawkishPath = ExpectedShortRate_1Y (Kim-Wright) - DFF (FRED)")
print(f"CORRECTION: Danger zone uses ΔExpectedRate_1Y, NOT ΔHP")
print()

for ticker_name in ['SPY', 'QQQ']:
    df = equities[ticker_name]
    print(f"\n{'─'*80}")
    print(f"  {ticker_name}  (data: {df['date'].min().date()} → {df['date'].max().date()})")
    print(f"{'─'*80}")
    
    subset = results_df[results_df['Ticker'] == ticker_name]
    
    for _, row in subset.iterrows():
        regime = row['Regime']
        # Highlight v2 corrected vs v1 old
        prefix = "  🔴" if 'v2' in regime and 'Strong' in regime else \
                 "  ⚠️ " if 'v1_OLD' in regime else "  ▸"
        print(f"\n{prefix} {regime}  (N={row['N_days']}, {row['Pct_time']} of time)")
        print(f"    {'Horizon':<8} {'Mean':>8} {'Median':>8} {'%Neg':>7} {'AvgMDD':>8} {'MDD_p10':>8}")
        print(f"    {'─'*50}")
        for label in horizons:
            mean_r = row[f'{label}_mean']
            med_r = row[f'{label}_median']
            neg_r = row[f'{label}_hit_neg']
            mdd_m = row[f'{label}_mdd_mean']
            mdd_p = row[f'{label}_mdd_p10']
            if pd.notna(mean_r):
                print(f"    {label:<8} {mean_r:>+7.2%} {med_r:>+7.2%} {neg_r:>6.1%} {mdd_m:>+7.2%} {mdd_p:>+7.2%}")
            else:
                print(f"    {label:<8}     N/A      N/A    N/A      N/A      N/A")

# ─── 8. EPISODE ANALYSIS (v2 corrected) ─────────────────────────
print("\n\n" + "=" * 80)
print("EPISODE ANALYSIS (v2): Strongly Hawkish = HP>0.5 & ΔExp1Y_4w>0.25")
print("=" * 80)

for ticker_name in ['SPY', 'QQQ']:
    df = equities[ticker_name].copy()
    # v2 corrected regime
    df['is_strong_hawk_v2'] = (df['hawkish_path'] > 0.5) & (df['delta_exp_4w'] > 0.25)
    df['regime_start'] = df['is_strong_hawk_v2'] & ~df['is_strong_hawk_v2'].shift(1, fill_value=False)
    
    starts = df[df['regime_start']]['date'].tolist()
    episodes = []
    if starts:
        current_ep = starts[0]
        for i in range(1, len(starts)):
            if (starts[i] - starts[i-1]).days > 60:
                episodes.append(current_ep)
                current_ep = starts[i]
        episodes.append(current_ep)
    
    print(f"\n  {ticker_name}: {len(episodes)} distinct strongly hawkish episodes (v2 corrected)")
    for ep_date in episodes:
        row = df[df['date'] >= ep_date].iloc[0]
        hp = row['hawkish_path']
        dexp = row['delta_exp_4w'] if pd.notna(row['delta_exp_4w']) else 0
        ddff = row['delta_dff_4w'] if pd.notna(row['delta_dff_4w']) else 0
        exp1y = row['exp_short_1y']
        dff_val = row['dff']
        price = row['close']
        fwd3m = row.get('fwd_3M', np.nan)
        fwd6m = row.get('fwd_6M', np.nan)
        mdd3m = row.get('mdd_3M', np.nan)
        
        line = (f"  {ep_date.date()}: HP={hp:+.2f}% | "
                f"Exp1Y={exp1y:.2f}% DFF={dff_val:.2f}% | "
                f"ΔExp4w={dexp:+.2f}% ΔDFF4w={ddff:+.2f}%")
        if pd.notna(fwd3m):
            line += f" | {ticker_name}=${price:.0f} →3M={fwd3m:+.1%} →6M={fwd6m:+.1%} MDD3M={mdd3m:+.1%}"
        print(line)

# ─── 9. COMPARISON: v1 vs v2 ────────────────────────────────────
print("\n\n" + "=" * 80)
print("COMPARISON: v1 (old, flawed ΔHP) vs v2 (corrected ΔExp1Y)")
print("=" * 80)

for ticker_name in ['SPY', 'QQQ']:
    print(f"\n  {ticker_name}:")
    v1 = results_df[(results_df['Ticker'] == ticker_name) & 
                     results_df['Regime'].str.contains('v1_OLD')]
    v2 = results_df[(results_df['Ticker'] == ticker_name) & 
                     results_df['Regime'].str.contains('v2') & 
                     results_df['Regime'].str.contains('StrongHawkish') &
                     ~results_df['Regime'].str.contains('strict')]
    base = results_df[(results_df['Ticker'] == ticker_name) & 
                       (results_df['Regime'] == 'All')]
    
    if len(v1) > 0 and len(v2) > 0 and len(base) > 0:
        print(f"    {'Version':<30} {'N':>6} {'3M_mean':>9} {'3M_%neg':>9} {'6M_mean':>9}")
        print(f"    {'─'*60}")
        for label, row_df in [('v1 OLD (ΔHP)', v1), ('v2 CORRECTED (ΔExp1Y)', v2), ('Baseline (All)', base)]:
            r = row_df.iloc[0]
            print(f"    {label:<30} {r['N_days']:>6} {r['3M_mean']:>+8.2%} {r['3M_hit_neg']:>8.1%} {r['6M_mean']:>+8.2%}")

# ─── 10. SAVE ────────────────────────────────────────────────────
print("\n\nSaving results...")
results_df.to_csv(os.path.join(OUTPUT_DIR, 'hawkish_path_v2_results.csv'), index=False)

signal_out = merged[['date', 'dff', 'fwd_1y', 'tp_1y', 'exp_short_1y', 
                       'hawkish_path', 'delta_exp_4w', 'delta_exp_8w',
                       'delta_dff_4w', 'delta_hp_4w']].copy()
signal_out.to_csv(os.path.join(OUTPUT_DIR, 'hawkish_path_v2_signal.csv'), index=False)
print(f"  → hawkish_path_v2_results.csv")
print(f"  → hawkish_path_v2_signal.csv")
print("\nDone!")
