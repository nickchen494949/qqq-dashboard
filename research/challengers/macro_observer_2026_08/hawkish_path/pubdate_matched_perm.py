#!/usr/bin/env python3
"""
Hawkish Repricing — Two Targeted Fixes
=======================================
Fix 1: Publication-date backtest
  Kim-Wright publishes weekly, typically Tuesday, data through prior Friday.
  Map each signal date → publication Tuesday → enter at that Tuesday's close.
  
Fix 2: Matched-episode permutation
  (a) Calendar-day spacing: null uses ≥60 calendar days, not ≥42 trading days
  (b) Circular block bootstrap: preserve real inter-episode gap structure
"""

import urllib.request, csv, json, os
import pandas as pd, numpy as np
from datetime import timedelta

DASHBOARD_DIR = '/Users/happygolucky/projects/宏观观察器'
KW_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200533.csv"
HORIZONS = {'1M': 21, '3M': 63, '6M': 126, '12M': 252}
N_PERM = 100_000
np.random.seed(42)

# ─── DATA LOADING ────────────────────────────────────────────────
print("Loading data...")

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
kw = pd.DataFrame(kw_rows); kw['date'] = pd.to_datetime(kw['date'])
kw['exp_short_1y'] = kw['fwd_1y'] - kw['tp_1y']
kw = kw.sort_values('date').reset_index(drop=True)

dff_json = os.path.join(DASHBOARD_DIR, 'data', 'fred', 'DFF.json')
with open(dff_json) as f: dff_data = json.load(f)
dff_raw = dff_data.get('values', dff_data) if isinstance(dff_data, dict) else dff_data
dff = pd.DataFrame(dff_raw, columns=['date', 'value'])
dff['date'] = pd.to_datetime(dff['date']); dff['dff'] = pd.to_numeric(dff['value'], errors='coerce')
dff = dff[['date', 'dff']].dropna()

merged = pd.merge(kw[['date','exp_short_1y','fwd_1y','tp_1y']], dff[['date','dff']], on='date', how='inner')
merged = merged.sort_values('date').reset_index(drop=True)
merged['hawkish_path'] = merged['exp_short_1y'] - merged['dff']
merged['delta_exp_4w'] = merged['exp_short_1y'] - merged['exp_short_1y'].shift(20)

INCEPTION = {'SPY': '1993-01-29', 'QQQ': '1999-03-10'}
equities = {}
for ticker in ['SPY', 'QQQ']:
    ypath = os.path.join(DASHBOARD_DIR, 'data', 'yahoo', f'{ticker}.json')
    if os.path.exists(ypath):
        with open(ypath) as f: yd = json.load(f)
        vals = yd.get('values', yd) if isinstance(yd, dict) else yd
        edf = pd.DataFrame(vals, columns=['date', 'close'])
        edf['date'] = pd.to_datetime(edf['date']); edf['close'] = pd.to_numeric(edf['close'], errors='coerce')
    else:
        import yfinance as yf
        raw_df = yf.download(ticker, start='1990-01-01', progress=False)
        edf = raw_df[['Close']].reset_index(); edf.columns = ['date', 'close']
        edf['date'] = pd.to_datetime(edf['date']).dt.tz_localize(None)
    edf = edf[edf['date'] >= INCEPTION[ticker]].dropna()
    equities[ticker] = edf.sort_values('date').reset_index(drop=True)

print("Data loaded.\n")

# ─── HELPERS ─────────────────────────────────────────────────────
def compute_fwd(prices, idx, days):
    end = idx + days
    if end >= len(prices): return np.nan
    return prices.iloc[end] / prices.iloc[idx] - 1

def kw_publication_date(obs_date):
    """
    Kim-Wright observation date → earliest available date.
    
    Fed publishes weekly, typically Tuesday, with data through prior Friday.
    So an observation from any day in week W is published on Tuesday of week W+1.
    
    Rule: find the Friday of obs_date's week, then add 4 calendar days = next Tuesday.
    """
    wd = obs_date.weekday()  # 0=Mon, 4=Fri
    days_to_friday = (4 - wd) % 7  # 0 if already Friday
    friday = obs_date + timedelta(days=days_to_friday)
    publication_tuesday = friday + timedelta(days=4)
    return publication_tuesday

def find_next_trading_day(date, date_index):
    """Find the next trading day on or after `date` in the date_index."""
    mask = date_index >= date
    if mask.any():
        return date_index[mask][0]
    return None

def extract_episodes_pubdate(signal_df, price_df, min_gap_days=60):
    """
    Extract episodes using publication-date execution.
    Signal computed on date t → Kim-Wright published on next Tuesday → 
    enter at that Tuesday's close (or next trading day if Tuesday is holiday).
    """
    sig = signal_df.copy()
    sig['is_strong_hawk'] = (sig['hawkish_path'] > 0.5) & (sig['delta_exp_4w'] > 0.25)
    
    # Build date→index mapping for price_df
    price_dates = price_df['date'].values
    price_date_index = pd.DatetimeIndex(price_dates)
    
    episodes = []
    last_exit_date = pd.Timestamp('1900-01-01')
    in_regime = False; signal_date = None; is_counted = False
    
    for i, row in sig.iterrows():
        if row['is_strong_hawk']:
            if not in_regime:
                if (row['date'] - last_exit_date).days >= min_gap_days:
                    in_regime = True
                    signal_date = row['date']
                    signal_row = row
                    is_counted = True
                else:
                    in_regime = True; is_counted = False
        else:
            if in_regime:
                last_exit_date = row['date']
                if is_counted and signal_date is not None:
                    pub_date = kw_publication_date(signal_date)
                    trade_date = find_next_trading_day(pub_date, price_date_index)
                    
                    if trade_date is not None:
                        trade_idx = price_df[price_df['date'] == trade_date].index
                        if len(trade_idx) > 0:
                            tidx = trade_idx[0]
                            ep = {
                                'signal_date': signal_date,
                                'pub_date': pub_date,
                                'trade_date': trade_date,
                                'trade_idx': tidx,
                                'hp': signal_row['hawkish_path'],
                                'delta_exp': signal_row['delta_exp_4w'],
                                'price': price_df.iloc[tidx]['close'],
                                'lag_days': (trade_date - signal_date).days,
                            }
                            for label, days in HORIZONS.items():
                                ep[f'fwd_{label}'] = compute_fwd(price_df['close'], tidx, days)
                            episodes.append(ep)
                in_regime = False
    
    # Handle still in regime at end
    if in_regime and is_counted and signal_date is not None:
        pub_date = kw_publication_date(signal_date)
        trade_date = find_next_trading_day(pub_date, price_date_index)
        if trade_date is not None:
            trade_idx = price_df[price_df['date'] == trade_date].index
            if len(trade_idx) > 0:
                tidx = trade_idx[0]
                ep = {
                    'signal_date': signal_date,
                    'pub_date': pub_date,
                    'trade_date': trade_date,
                    'trade_idx': tidx,
                    'hp': signal_row['hawkish_path'],
                    'delta_exp': signal_row['delta_exp_4w'],
                    'price': price_df.iloc[tidx]['close'],
                    'lag_days': (trade_date - signal_date).days,
                }
                for label, days in HORIZONS.items():
                    ep[f'fwd_{label}'] = compute_fwd(price_df['close'], tidx, days)
                episodes.append(ep)
    
    return pd.DataFrame(episodes)

def extract_episodes_simple(sig_df, price_df, min_gap_days=60, execution_lag=0):
    """Extract episodes with simple trading-day lag."""
    sig = sig_df.copy()
    sig['is_strong_hawk'] = (sig['hawkish_path'] > 0.5) & (sig['delta_exp_4w'] > 0.25)
    
    episodes = []
    last_exit_date = pd.Timestamp('1900-01-01')
    in_regime = False; entry_idx = None; is_counted = False
    
    for i, row in sig.iterrows():
        if row['is_strong_hawk']:
            if not in_regime:
                if (row['date'] - last_exit_date).days >= min_gap_days:
                    in_regime = True
                    entry_idx = i + execution_lag
                    is_counted = True
                else:
                    in_regime = True; is_counted = False
        else:
            if in_regime:
                last_exit_date = row['date']
                if is_counted and entry_idx < len(sig):
                    ep = {'entry_idx': entry_idx, 'entry_date': sig.iloc[entry_idx]['date'],
                          'price': price_df.iloc[entry_idx]['close'] if entry_idx < len(price_df) else np.nan}
                    for label, days in HORIZONS.items():
                        ep[f'fwd_{label}'] = compute_fwd(price_df['close'], entry_idx, days)
                    episodes.append(ep)
                in_regime = False
    
    if in_regime and is_counted and entry_idx is not None and entry_idx < len(sig):
        ep = {'entry_idx': entry_idx, 'entry_date': sig.iloc[entry_idx]['date'],
              'price': price_df.iloc[entry_idx]['close'] if entry_idx < len(price_df) else np.nan}
        for label, days in HORIZONS.items():
            ep[f'fwd_{label}'] = compute_fwd(price_df['close'], entry_idx, days)
        episodes.append(ep)
    
    return pd.DataFrame(episodes)


# ═══════════════════════════════════════════════════════════════════
# FIX 1: PUBLICATION-DATE BACKTEST
# ═══════════════════════════════════════════════════════════════════
print("=" * 90)
print("FIX 1: PUBLICATION-DATE EXECUTION")
print("=" * 90)
print("Kim-Wright observation → published next Tuesday → trade at Tuesday close")
print("This adds 4-8 calendar days of lag vs same-day execution.\n")

for ticker in ['QQQ', 'SPY']:
    edf = equities[ticker]
    sig_df = pd.merge(merged[['date','hawkish_path','delta_exp_4w','exp_short_1y','dff']],
                       edf[['date','close']], on='date', how='inner').sort_values('date').reset_index(drop=True)
    
    # Same-day baseline
    ep_t0 = extract_episodes_simple(sig_df, sig_df, min_gap_days=60, execution_lag=0)
    # Publication-date
    ep_pub = extract_episodes_pubdate(sig_df, edf, min_gap_days=60)
    
    print(f"  {ticker}:")
    print(f"    {'Execution':<25} {'N':>3} {'Avg Lag':>8} {'3M Mean':>9} {'3M %Neg':>8} {'6M Mean':>9} {'6M %Neg':>8}")
    print(f"    {'─'*68}")
    
    # t+0
    v3 = ep_t0['fwd_3M'].dropna(); v6 = ep_t0['fwd_6M'].dropna()
    print(f"    {'Same-day (t+0)':<25} {len(ep_t0):>3} {'0d':>8} "
          f"{v3.mean():>+8.2%} {(v3<0).mean():>7.0%} {v6.mean():>+8.2%} {(v6<0).mean():>7.0%}")
    
    # Publication-date
    if len(ep_pub) > 0:
        v3p = ep_pub['fwd_3M'].dropna(); v6p = ep_pub['fwd_6M'].dropna()
        avg_lag = ep_pub['lag_days'].mean()
        print(f"    {'Publication Tuesday':<25} {len(ep_pub):>3} {avg_lag:>6.1f}d "
              f"{v3p.mean():>+8.2%} {(v3p<0).mean():>7.0%} {v6p.mean():>+8.2%} {(v6p<0).mean():>7.0%}")
    
    # Detail table for pub-date
    if len(ep_pub) > 0 and ticker == 'QQQ':
        print(f"\n    Detailed publication-date episodes:")
        print(f"    {'#':>3} {'Signal':>12} {'Pub Tue':>12} {'Trade':>12} {'Lag':>4} {'Price':>7} {'3M':>8} {'6M':>8}")
        print(f"    {'─'*75}")
        for j, (_, ep) in enumerate(ep_pub.iterrows()):
            sig_d = ep['signal_date'].strftime('%Y-%m-%d')
            pub_d = ep['pub_date'].strftime('%Y-%m-%d')
            trd_d = ep['trade_date'].strftime('%Y-%m-%d') if pd.notna(ep['trade_date']) else 'N/A'
            f3 = f"{ep['fwd_3M']:>+7.1%}" if pd.notna(ep['fwd_3M']) else "    N/A"
            f6 = f"{ep['fwd_6M']:>+7.1%}" if pd.notna(ep['fwd_6M']) else "    N/A"
            print(f"    {j+1:>3} {sig_d:>12} {pub_d:>12} {trd_d:>12} {ep['lag_days']:>3}d "
                  f"${ep['price']:>6.0f} {f3} {f6}")
    print()


# ═══════════════════════════════════════════════════════════════════
# FIX 2: MATCHED-EPISODE PERMUTATION
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print("FIX 2: MATCHED-EPISODE PERMUTATION (100k iterations)")
print("=" * 90)
print("Two null models, both using ≥60 CALENDAR day gaps (not trading days):")
print("  (a) Random dates with ≥60 calendar-day spacing")
print("  (b) Circular block bootstrap (preserve real inter-episode gaps)\n")

for ticker in ['QQQ', 'SPY']:
    edf = equities[ticker]
    sig_df = pd.merge(merged[['date','hawkish_path','delta_exp_4w','exp_short_1y','dff']],
                       edf[['date','close']], on='date', how='inner').sort_values('date').reset_index(drop=True)
    
    # Real episodes
    real_ep = extract_episodes_simple(sig_df, sig_df, min_gap_days=60, execution_lag=0)
    n_ep = len(real_ep)
    if n_ep == 0: continue
    
    real_3m = real_ep['fwd_3M'].dropna().values
    real_6m = real_ep['fwd_6M'].dropna().values
    real_3m_mean = real_3m.mean()
    real_3m_neg = (real_3m < 0).mean()
    real_6m_mean = real_6m.mean()
    real_6m_neg = (real_6m < 0).mean()
    
    # Build calendar-day array for spacing computation
    dates = sig_df['date'].values
    max_idx_3m = len(sig_df) - HORIZONS['3M'] - 1
    max_idx_6m = len(sig_df) - HORIZONS['6M'] - 1
    
    # ─── (a) Calendar-day spacing permutation ─────────────────
    perm_3m_means_a = []
    perm_3m_negs_a = []
    perm_6m_means_a = []
    
    for _ in range(N_PERM):
        indices = []
        attempts = 0
        while len(indices) < n_ep and attempts < 500:
            candidate = np.random.randint(0, max_idx_6m)
            ok = True
            for existing in indices:
                # Use CALENDAR days, not trading days
                gap_cal = abs((dates[candidate] - dates[existing]) / np.timedelta64(1, 'D'))
                if gap_cal < 60:
                    ok = False; break
            if ok:
                indices.append(candidate)
            attempts += 1
        
        if len(indices) < n_ep: continue
        
        r3 = [compute_fwd(sig_df['close'], idx, HORIZONS['3M']) for idx in indices]
        r6 = [compute_fwd(sig_df['close'], idx, HORIZONS['6M']) for idx in indices]
        r3 = [x for x in r3 if not np.isnan(x)]
        r6 = [x for x in r6 if not np.isnan(x)]
        
        if len(r3) >= n_ep:
            perm_3m_means_a.append(np.mean(r3))
            perm_3m_negs_a.append(np.mean([x < 0 for x in r3]))
        if len(r6) >= n_ep:
            perm_6m_means_a.append(np.mean(r6))
    
    perm_3m_means_a = np.array(perm_3m_means_a)
    perm_3m_negs_a = np.array(perm_3m_negs_a)
    perm_6m_means_a = np.array(perm_6m_means_a)
    
    # ─── (b) Circular block bootstrap ────────────────────────
    # Preserve real inter-episode gaps, shift entire sequence
    real_indices = real_ep['entry_idx'].values
    real_gaps = np.diff(real_indices)  # gaps in trading days between consecutive episodes
    
    perm_3m_means_b = []
    perm_3m_negs_b = []
    perm_6m_means_b = []
    
    total_span = real_indices[-1] - real_indices[0]  # total trading-day span of real episodes
    
    for _ in range(N_PERM):
        # Pick a random starting index, then place episodes with same gaps
        max_start = len(sig_df) - total_span - HORIZONS['6M'] - 1
        if max_start <= 0: break
        
        start = np.random.randint(0, max_start)
        shifted_indices = [start]
        for gap in real_gaps:
            shifted_indices.append(shifted_indices[-1] + gap)
        
        # Check all valid
        if shifted_indices[-1] + HORIZONS['6M'] >= len(sig_df):
            continue
        
        r3 = [compute_fwd(sig_df['close'], idx, HORIZONS['3M']) for idx in shifted_indices]
        r6 = [compute_fwd(sig_df['close'], idx, HORIZONS['6M']) for idx in shifted_indices]
        r3 = [x for x in r3 if not np.isnan(x)]
        r6 = [x for x in r6 if not np.isnan(x)]
        
        if len(r3) >= n_ep:
            perm_3m_means_b.append(np.mean(r3))
            perm_3m_negs_b.append(np.mean([x < 0 for x in r3]))
        if len(r6) >= n_ep:
            perm_6m_means_b.append(np.mean(r6))
    
    perm_3m_means_b = np.array(perm_3m_means_b)
    perm_3m_negs_b = np.array(perm_3m_negs_b)
    perm_6m_means_b = np.array(perm_6m_means_b)
    
    # ─── Results ─────────────────────────────────────────────
    print(f"  {ticker} — {n_ep} episodes")
    print(f"    Real: 3M={real_3m_mean:+.2%}, 3M%neg={real_3m_neg:.0%}, 6M={real_6m_mean:+.2%}, 6M%neg={real_6m_neg:.0%}")
    
    if len(perm_3m_means_a) > 0:
        p3m_a = np.mean(perm_3m_means_a <= real_3m_mean)
        p3n_a = np.mean(perm_3m_negs_a >= real_3m_neg)
        p6m_a = np.mean(perm_6m_means_a <= real_6m_mean)
        print(f"\n    (a) Calendar-day spacing permutation ({len(perm_3m_means_a):,} valid iterations):")
        print(f"        3M mean: random avg={np.mean(perm_3m_means_a):+.2%}, p={p3m_a:.4f}")
        print(f"        3M %neg: random avg={np.mean(perm_3m_negs_a):.0%}, p={p3n_a:.4f}")
        print(f"        6M mean: random avg={np.mean(perm_6m_means_a):+.2%}, p={p6m_a:.4f}")
    
    if len(perm_3m_means_b) > 0:
        p3m_b = np.mean(perm_3m_means_b <= real_3m_mean)
        p3n_b = np.mean(perm_3m_negs_b >= real_3m_neg)
        p6m_b = np.mean(perm_6m_means_b <= real_6m_mean)
        print(f"\n    (b) Circular block bootstrap ({len(perm_3m_means_b):,} valid iterations):")
        print(f"        3M mean: random avg={np.mean(perm_3m_means_b):+.2%}, p={p3m_b:.4f}")
        print(f"        3M %neg: random avg={np.mean(perm_3m_negs_b):.0%}, p={p3n_b:.4f}")
        print(f"        6M mean: random avg={np.mean(perm_6m_means_b):+.2%}, p={p6m_b:.4f}")
    
    # Compare old vs new
    print(f"\n    Comparison (previous run used ≥42 trading-day spacing):")
    print(f"    ┌──────────────────────┬────────────┬────────────┬────────────┐")
    print(f"    │ Metric               │ Old (42td) │ CalDay(a)  │ Block(b)   │")
    print(f"    ├──────────────────────┼────────────┼────────────┼────────────┤")
    if len(perm_6m_means_a) > 0 and len(perm_6m_means_b) > 0:
        old_p = {'QQQ': {'3m': 0.1057, '3n': 0.0202, '6m': 0.0081},
                 'SPY': {'3m': 0.2377, '3n': 0.0377, '6m': 0.0157}}
        print(f"    │ 3M mean p-value      │ {old_p[ticker]['3m']:>10.4f} │ {p3m_a:>10.4f} │ {p3m_b:>10.4f} │")
        print(f"    │ 3M %neg p-value      │ {old_p[ticker]['3n']:>10.4f} │ {p3n_a:>10.4f} │ {p3n_b:>10.4f} │")
        print(f"    │ 6M mean p-value      │ {old_p[ticker]['6m']:>10.4f} │ {p6m_a:>10.4f} │ {p6m_b:>10.4f} │")
    print(f"    └──────────────────────┴────────────┴────────────┴────────────┘")
    print()


# ═══════════════════════════════════════════════════════════════════
# COMBINED: PUB-DATE + MATCHED PERMUTATION
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print("COMBINED: Publication-date execution + calendar-day permutation")
print("=" * 90)
print("The hardest test: does the signal survive when you can only trade")
print("AFTER the Kim-Wright data is actually published?\n")

for ticker in ['QQQ', 'SPY']:
    edf = equities[ticker]
    sig_df = pd.merge(merged[['date','hawkish_path','delta_exp_4w','exp_short_1y','dff']],
                       edf[['date','close']], on='date', how='inner').sort_values('date').reset_index(drop=True)
    
    ep_pub = extract_episodes_pubdate(sig_df, edf, min_gap_days=60)
    if len(ep_pub) == 0: continue
    
    n_ep = len(ep_pub)
    v3 = ep_pub['fwd_3M'].dropna()
    v6 = ep_pub['fwd_6M'].dropna()
    
    # Permutation against pub-date execution
    # Random dates from equity trading days with ≥60 cal-day spacing
    price_max_idx = len(edf) - HORIZONS['6M'] - 1
    price_dates = edf['date'].values
    
    perm_3m = []
    perm_6m = []
    
    for _ in range(N_PERM):
        indices = []
        attempts = 0
        while len(indices) < n_ep and attempts < 500:
            candidate = np.random.randint(0, price_max_idx)
            ok = True
            for existing in indices:
                gap_cal = abs((price_dates[candidate] - price_dates[existing]) / np.timedelta64(1, 'D'))
                if gap_cal < 60:
                    ok = False; break
            if ok:
                indices.append(candidate)
            attempts += 1
        if len(indices) < n_ep: continue
        
        r3 = [compute_fwd(edf['close'], idx, HORIZONS['3M']) for idx in indices]
        r6 = [compute_fwd(edf['close'], idx, HORIZONS['6M']) for idx in indices]
        r3 = [x for x in r3 if not np.isnan(x)]
        r6 = [x for x in r6 if not np.isnan(x)]
        
        if r3: perm_3m.append(np.mean(r3))
        if r6: perm_6m.append(np.mean(r6))
    
    perm_3m = np.array(perm_3m)
    perm_6m = np.array(perm_6m)
    
    pub_3m_mean = v3.mean()
    pub_6m_mean = v6.mean()
    pub_3m_neg = (v3 < 0).mean()
    pub_6m_neg = (v6 < 0).mean()
    
    p_3m = np.mean(perm_3m <= pub_3m_mean) if len(perm_3m) > 0 else np.nan
    p_6m = np.mean(perm_6m <= pub_6m_mean) if len(perm_6m) > 0 else np.nan
    
    print(f"  {ticker} — {n_ep} pub-date episodes")
    print(f"    3M: mean={pub_3m_mean:+.2%}, %neg={pub_3m_neg:.0%}, p={p_3m:.4f}")
    print(f"    6M: mean={pub_6m_mean:+.2%}, %neg={pub_6m_neg:.0%}, p={p_6m:.4f}")
    print()


print(f"\n{'='*90}")
print("SUMMARY")
print("=" * 90)
print("""
Fix 1 (Publication-date): Does the 4-8 day real-world lag kill the signal?
Fix 2 (Matched permutation): Does using proper calendar-day spacing change p-values?

If 6M QQQ pub-date p-value is still < 0.05, BOTH fixes pass.
""")
