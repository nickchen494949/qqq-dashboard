#!/usr/bin/env python3
"""
Episode-Level Robustness Test for Hawkish Repricing Signal
==========================================================
Collapses overlapping signal days into independent episodes.
Rule: signal must be OFF for ≥60 calendar days before a new episode begins.
Only the first entry day of each cluster counts.

This is the critical statistical test — raw signal-day counts overstate
independence because consecutive days look at nearly the same future returns.
"""

import urllib.request, csv, json, os, sys
import pandas as pd, numpy as np

DASHBOARD_DIR = '/Users/happygolucky/projects/宏观观察器'
KW_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200533.csv"
HORIZONS = {'1M': 21, '3M': 63, '6M': 126, '12M': 252}
MIN_GAP_DAYS = 60  # Calendar days between independent episodes

def load_data():
    # Kim-Wright
    req = urllib.request.Request(KW_URL, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read().decode('utf-8')
    lines = raw.strip().split('\n')
    header_idx = next(i for i, l in enumerate(lines) if l.startswith('Date,'))
    reader = csv.DictReader(lines[header_idx:])
    kw_rows = []
    for row in reader:
        try:
            kw_rows.append({'date': row['Date'], 'fwd_1y': float(row['THREEFF0100.B']),
                            'tp_1y': float(row['THREEFFTP0100.B'])})
        except: continue
    kw = pd.DataFrame(kw_rows)
    kw['date'] = pd.to_datetime(kw['date'])
    kw['exp_short_1y'] = kw['fwd_1y'] - kw['tp_1y']
    kw = kw.sort_values('date').reset_index(drop=True)

    # DFF
    dff_json = os.path.join(DASHBOARD_DIR, 'data', 'fred', 'DFF.json')
    with open(dff_json) as f: dff_data = json.load(f)
    dff_raw = dff_data.get('values', dff_data) if isinstance(dff_data, dict) else dff_data
    dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
    dff['date'] = pd.to_datetime(dff['date'])
    dff['dff'] = pd.to_numeric(dff['value'], errors='coerce')
    dff = dff[['date', 'dff']].dropna()

    merged = pd.merge(kw[['date','exp_short_1y','fwd_1y','tp_1y']], dff[['date','dff']], on='date', how='inner')
    merged = merged.sort_values('date').reset_index(drop=True)
    merged['hawkish_path'] = merged['exp_short_1y'] - merged['dff']
    merged['delta_exp_4w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(20)
    return merged

def load_equity(ticker, inception):
    ypath = os.path.join(DASHBOARD_DIR, 'data', 'yahoo', f'{ticker}.json')
    if os.path.exists(ypath):
        with open(ypath) as f: yd = json.load(f)
        vals = yd.get('values', yd) if isinstance(yd, dict) else yd
        edf = pd.DataFrame(vals, columns=['date', 'close'])
        edf['date'] = pd.to_datetime(edf['date'])
        edf['close'] = pd.to_numeric(edf['close'], errors='coerce')
    else:
        import yfinance as yf
        raw_df = yf.download(ticker, start='1990-01-01', progress=False)
        edf = raw_df[['Close']].reset_index(); edf.columns = ['date', 'close']
        edf['date'] = pd.to_datetime(edf['date']).dt.tz_localize(None)
    return edf[edf['date'] >= inception].dropna().sort_values('date').reset_index(drop=True)

def compute_fwd_mdd(prices, start_idx, days):
    end_idx = start_idx + days
    if end_idx >= len(prices): return np.nan, np.nan
    fwd_ret = prices.iloc[end_idx] / prices.iloc[start_idx] - 1
    window = prices.iloc[start_idx:end_idx+1].values
    peak = window[0]; max_dd = 0
    for p in window[1:]:
        peak = max(peak, p); dd = (p - peak) / peak; max_dd = min(max_dd, dd)
    return fwd_ret, max_dd

def extract_episodes(df):
    df = df.copy()
    df['is_strong_hawk'] = (df['hawkish_path'] > 0.5) & (df['delta_exp_4w'] > 0.25)
    episodes = []
    last_exit_date = pd.Timestamp('1900-01-01')
    in_regime = False; entry_row = None; entry_idx = None

    for i, row in df.iterrows():
        if row['is_strong_hawk']:
            if not in_regime:
                if (row['date'] - last_exit_date).days >= MIN_GAP_DAYS:
                    in_regime = True; entry_row = row; entry_idx = i
                else:
                    in_regime = True; entry_row = None
        else:
            if in_regime:
                last_exit_date = row['date']
                if entry_row is not None:
                    ep = {'entry_date': entry_row['date'], 'exit_date': row['date'],
                          'hp': entry_row['hawkish_path'], 'delta_exp': entry_row['delta_exp_4w'],
                          'exp_1y': entry_row['exp_short_1y'], 'dff': entry_row['dff'],
                          'price': entry_row['close']}
                    for label, days in HORIZONS.items():
                        ret, mdd = compute_fwd_mdd(df['close'], entry_idx, days)
                        ep[f'fwd_{label}'] = ret; ep[f'mdd_{label}'] = mdd
                    episodes.append(ep)
                in_regime = False

    if in_regime and entry_row is not None:
        ep = {'entry_date': entry_row['date'], 'exit_date': df.iloc[-1]['date'],
              'hp': entry_row['hawkish_path'], 'delta_exp': entry_row['delta_exp_4w'],
              'exp_1y': entry_row['exp_short_1y'], 'dff': entry_row['dff'],
              'price': entry_row['close']}
        for label, days in HORIZONS.items():
            ret, mdd = compute_fwd_mdd(df['close'], entry_idx, days)
            ep[f'fwd_{label}'] = ret; ep[f'mdd_{label}'] = mdd
        episodes.append(ep)

    return pd.DataFrame(episodes)

if __name__ == '__main__':
    merged = load_data()
    INCEPTION = {'SPY': '1993-01-29', 'QQQ': '1999-03-10'}

    for ticker in ['SPY', 'QQQ']:
        edf = load_equity(ticker, INCEPTION[ticker])
        df = pd.merge(merged[['date','hawkish_path','delta_exp_4w','exp_short_1y','dff']],
                       edf[['date','close']], on='date', how='inner').sort_values('date').reset_index(drop=True)
        ep_df = extract_episodes(df)

        print(f"\n{'='*100}")
        print(f"  {ticker} — {len(ep_df)} INDEPENDENT EPISODES (≥{MIN_GAP_DAYS}d gap)")
        print(f"{'='*100}")

        for j, (_, ep) in enumerate(ep_df.iterrows()):
            print(f"  {j+1:>2} {ep['entry_date'].strftime('%Y-%m-%d')} "
                  f"Exp1Y={ep['exp_1y']:.2f}% DFF={ep['dff']:.2f}% HP={ep['hp']:+.2f}% "
                  f"ΔExp={ep['delta_exp']:+.2f}% "
                  f"3M={ep['fwd_3M']:+.1%} 6M={ep['fwd_6M']:+.1%}" if pd.notna(ep.get('fwd_3M')) else "")

        print(f"\n  SUMMARY:")
        for label in HORIZONS:
            v = ep_df[f'fwd_{label}'].dropna()
            if len(v) == 0: continue
            print(f"    {label}: mean={v.mean():+.2%} median={v.median():+.2%} "
                  f"neg={(v<0).sum()}/{len(v)} ({(v<0).mean():.0%})")

        non_zlb = ep_df[ep_df['dff'] >= 0.5]
        v3 = non_zlb['fwd_3M'].dropna(); v6 = non_zlb['fwd_6M'].dropna()
        if len(v3) > 0:
            print(f"\n  NON-ZLB ONLY (DFF≥0.5%, N={len(non_zlb)}):")
            print(f"    3M: mean={v3.mean():+.2%} neg={(v3<0).sum()}/{len(v3)}")
            print(f"    6M: mean={v6.mean():+.2%} neg={(v6<0).sum()}/{len(v6)}")
