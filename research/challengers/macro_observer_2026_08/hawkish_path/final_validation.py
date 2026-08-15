#!/usr/bin/env python3
"""
Hawkish Repricing Signal — Final Validation
============================================
Three tests, signal definition unchanged:
  HP > 0.5% AND ΔExpectedRate_1Y_4w > 0.25%

Test 1: Block permutation (100k iterations)
  - Randomly draw 13 episodes with same spacing constraints
  - Compare real signal's 3M/6M returns against null distribution
  - Empirical p-value

Test 2: Next-day execution
  - Signal_t → Close_{t+1} instead of Close_t
  - Kim-Wright publishes with ~1-week lag; DFF publishes T+1
  - Tests whether 1-day execution lag destroys the signal

Test 3: Cooldown sensitivity
  - Run episode extraction with 20/40/60/90/120 day cooldowns
  - Check stability of results across definitions

Notes:
  - Kim-Wright data is current-vintage, not real-time-vintage
  - This is acknowledged as a limitation, not corrected here
  - ZLB split shown as exploratory, not primary
"""

import urllib.request, csv, json, os, sys
import pandas as pd, numpy as np
from scipy import stats

DASHBOARD_DIR = '/Users/happygolucky/projects/宏观观察器'
KW_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200533.csv"
HORIZONS = {'1M': 21, '3M': 63, '6M': 126, '12M': 252}
N_PERMUTATIONS = 100_000
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

# ─── HELPER FUNCTIONS ────────────────────────────────────────────
def compute_fwd(prices, idx, days):
    end = idx + days
    if end >= len(prices): return np.nan
    return prices.iloc[end] / prices.iloc[idx] - 1

def compute_mdd(prices, idx, days):
    end = idx + days
    if end >= len(prices): return np.nan
    window = prices.iloc[idx:end+1].values
    peak = window[0]; max_dd = 0
    for p in window[1:]:
        peak = max(peak, p); dd = (p - peak) / peak; max_dd = min(max_dd, dd)
    return max_dd

def extract_episodes(df, min_gap_days, execution_lag=0):
    """Extract episodes. execution_lag=0 means same-day, =1 means next-day."""
    df = df.copy()
    df['is_strong_hawk'] = (df['hawkish_path'] > 0.5) & (df['delta_exp_4w'] > 0.25)
    episodes = []
    last_exit_date = pd.Timestamp('1900-01-01')
    in_regime = False; entry_idx = None; is_counted = False

    for i, row in df.iterrows():
        if row['is_strong_hawk']:
            if not in_regime:
                if (row['date'] - last_exit_date).days >= min_gap_days:
                    in_regime = True
                    entry_idx = i + execution_lag  # lag by N days
                    is_counted = True
                else:
                    in_regime = True; is_counted = False
        else:
            if in_regime:
                last_exit_date = row['date']
                if is_counted and entry_idx < len(df):
                    entry_row = df.iloc[entry_idx]
                    ep = {'entry_date': entry_row['date'], 'entry_idx': entry_idx,
                          'hp': df.iloc[entry_idx - execution_lag]['hawkish_path'] if entry_idx >= execution_lag else np.nan,
                          'price': entry_row['close']}
                    for label, days in HORIZONS.items():
                        ep[f'fwd_{label}'] = compute_fwd(df['close'], entry_idx, days)
                        ep[f'mdd_{label}'] = compute_mdd(df['close'], entry_idx, days)
                    episodes.append(ep)
                in_regime = False

    if in_regime and is_counted and entry_idx is not None and entry_idx < len(df):
        entry_row = df.iloc[entry_idx]
        ep = {'entry_date': entry_row['date'], 'entry_idx': entry_idx,
              'hp': df.iloc[entry_idx - execution_lag]['hawkish_path'] if entry_idx >= execution_lag else np.nan,
              'price': entry_row['close']}
        for label, days in HORIZONS.items():
            ep[f'fwd_{label}'] = compute_fwd(df['close'], entry_idx, days)
            ep[f'mdd_{label}'] = compute_mdd(df['close'], entry_idx, days)
        episodes.append(ep)

    return pd.DataFrame(episodes)


# ═══════════════════════════════════════════════════════════════════
# TEST 1: BLOCK PERMUTATION
# ═══════════════════════════════════════════════════════════════════
print("=" * 80)
print("TEST 1: BLOCK PERMUTATION (N=100,000 iterations)")
print("=" * 80)
print("Null hypothesis: picking 13 random dates with ≥60-day spacing")
print("would produce equally bad QQQ returns.\n")

for ticker in ['QQQ', 'SPY']:
    edf = equities[ticker]
    df = pd.merge(merged[['date','hawkish_path','delta_exp_4w','exp_short_1y','dff']],
                   edf[['date','close']], on='date', how='inner').sort_values('date').reset_index(drop=True)

    # Real episodes
    real_ep = extract_episodes(df, min_gap_days=60, execution_lag=0)
    n_episodes = len(real_ep)

    if n_episodes == 0:
        print(f"  {ticker}: No episodes found, skipping.")
        continue

    real_3m_mean = real_ep['fwd_3M'].dropna().mean()
    real_3m_neg_pct = (real_ep['fwd_3M'].dropna() < 0).mean()
    real_6m_mean = real_ep['fwd_6M'].dropna().mean()
    real_6m_neg_pct = (real_ep['fwd_6M'].dropna() < 0).mean()

    print(f"  {ticker} — Real signal: {n_episodes} episodes")
    print(f"    3M mean={real_3m_mean:+.2%}, %neg={real_3m_neg_pct:.0%}")
    print(f"    6M mean={real_6m_mean:+.2%}, %neg={real_6m_neg_pct:.0%}")

    # Eligible indices: must have 3M forward data available
    max_idx = len(df) - HORIZONS['6M'] - 1  # ensure 6M data exists
    eligible = np.arange(0, max_idx)

    # Permutation: draw n_episodes random indices with ≥60 calendar day spacing
    perm_3m_means = []
    perm_3m_neg_pcts = []
    perm_6m_means = []

    min_gap_trading = 42  # ~60 calendar days ≈ 42 trading days

    for _ in range(N_PERMUTATIONS):
        # Draw first index uniformly
        indices = []
        attempts = 0
        while len(indices) < n_episodes and attempts < 500:
            candidate = np.random.randint(0, max_idx)
            # Check spacing from all existing indices
            ok = True
            for existing in indices:
                if abs(candidate - existing) < min_gap_trading:
                    ok = False
                    break
            if ok:
                indices.append(candidate)
            attempts += 1

        if len(indices) < n_episodes:
            continue

        rets_3m = [compute_fwd(df['close'], idx, HORIZONS['3M']) for idx in indices]
        rets_6m = [compute_fwd(df['close'], idx, HORIZONS['6M']) for idx in indices]
        rets_3m = [r for r in rets_3m if not np.isnan(r)]
        rets_6m = [r for r in rets_6m if not np.isnan(r)]

        if len(rets_3m) > 0:
            perm_3m_means.append(np.mean(rets_3m))
            perm_3m_neg_pcts.append(np.mean([r < 0 for r in rets_3m]))
        if len(rets_6m) > 0:
            perm_6m_means.append(np.mean(rets_6m))

    perm_3m_means = np.array(perm_3m_means)
    perm_3m_neg_pcts = np.array(perm_3m_neg_pcts)
    perm_6m_means = np.array(perm_6m_means)

    # Empirical p-values (one-tailed: how often is random WORSE than signal?)
    p_3m_mean = np.mean(perm_3m_means <= real_3m_mean)
    p_3m_neg = np.mean(perm_3m_neg_pcts >= real_3m_neg_pct)
    p_6m_mean = np.mean(perm_6m_means <= real_6m_mean)

    print(f"\n    Permutation results ({len(perm_3m_means):,} valid iterations):")
    print(f"    ┌─────────────────┬──────────────┬────────────────┬─────────────┐")
    print(f"    │ Metric          │ Real Signal  │ Random Mean    │ p-value     │")
    print(f"    ├─────────────────┼──────────────┼────────────────┼─────────────┤")
    print(f"    │ 3M mean return  │ {real_3m_mean:>+10.2%}  │ {np.mean(perm_3m_means):>+12.2%}  │ {p_3m_mean:>9.4f}   │")
    print(f"    │ 3M % negative   │ {real_3m_neg_pct:>10.0%}  │ {np.mean(perm_3m_neg_pcts):>12.0%}  │ {p_3m_neg:>9.4f}   │")
    print(f"    │ 6M mean return  │ {real_6m_mean:>+10.2%}  │ {np.mean(perm_6m_means):>+12.2%}  │ {p_6m_mean:>9.4f}   │")
    print(f"    └─────────────────┴──────────────┴────────────────┴─────────────┘")
    print(f"    Random 3M mean distribution: p5={np.percentile(perm_3m_means,5):+.2%}, "
          f"p25={np.percentile(perm_3m_means,25):+.2%}, "
          f"p50={np.percentile(perm_3m_means,50):+.2%}, "
          f"p75={np.percentile(perm_3m_means,75):+.2%}, "
          f"p95={np.percentile(perm_3m_means,95):+.2%}")


# ═══════════════════════════════════════════════════════════════════
# TEST 2: NEXT-DAY EXECUTION
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("TEST 2: EXECUTION LAG (t+0 vs t+1 vs t+2)")
print("=" * 80)
print("Kim-Wright updates weekly; DFF publishes T+1 morning.")
print("Testing whether 1-2 day execution lag destroys the signal.\n")

for ticker in ['QQQ', 'SPY']:
    edf = equities[ticker]
    df = pd.merge(merged[['date','hawkish_path','delta_exp_4w','exp_short_1y','dff']],
                   edf[['date','close']], on='date', how='inner').sort_values('date').reset_index(drop=True)

    print(f"  {ticker}:")
    print(f"    {'Lag':<6} {'N':>4} {'3M Mean':>9} {'3M %Neg':>8} {'6M Mean':>9} {'6M %Neg':>8}")
    print(f"    {'─'*50}")

    for lag in [0, 1, 2]:
        ep = extract_episodes(df, min_gap_days=60, execution_lag=lag)
        if len(ep) == 0:
            print(f"    t+{lag:<3}  {0:>4}      N/A      N/A      N/A      N/A")
            continue
        v3 = ep['fwd_3M'].dropna(); v6 = ep['fwd_6M'].dropna()
        print(f"    t+{lag:<3}  {len(ep):>4} {v3.mean():>+8.2%} {(v3<0).mean():>7.0%} "
              f"{v6.mean():>+8.2%} {(v6<0).mean():>7.0%}")


# ═══════════════════════════════════════════════════════════════════
# TEST 3: COOLDOWN SENSITIVITY
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("TEST 3: COOLDOWN SENSITIVITY (20 / 40 / 60 / 90 / 120 days)")
print("=" * 80)
print("Does the result depend on the specific choice of 60-day gap?\n")

for ticker in ['QQQ', 'SPY']:
    edf = equities[ticker]
    df = pd.merge(merged[['date','hawkish_path','delta_exp_4w','exp_short_1y','dff']],
                   edf[['date','close']], on='date', how='inner').sort_values('date').reset_index(drop=True)

    print(f"  {ticker}:")
    print(f"    {'Cooldown':>8} {'N':>4} {'3M Mean':>9} {'3M Med':>8} {'3M %Neg':>8} {'6M Mean':>9} {'6M %Neg':>8}")
    print(f"    {'─'*60}")

    for gap in [20, 40, 60, 90, 120]:
        ep = extract_episodes(df, min_gap_days=gap, execution_lag=0)
        if len(ep) == 0:
            print(f"    {gap:>5}d   {0:>4}")
            continue
        v3 = ep['fwd_3M'].dropna(); v6 = ep['fwd_6M'].dropna()
        if len(v3) == 0: continue
        print(f"    {gap:>5}d   {len(ep):>4} {v3.mean():>+8.2%} {v3.median():>+7.2%} "
              f"{(v3<0).mean():>7.0%} {v6.mean():>+8.2%} {(v6<0).mean():>7.0%}")


# ═══════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("FINAL SUMMARY")
print("=" * 80)
print("""
Signal: HP > 0.5% AND ΔExpectedRate_1Y_4w > 0.25%
Data: Kim-Wright (current vintage, 1990-2026) + FRED DFF
Primary result: 13 QQQ episodes (60-day gap)

Caveats acknowledged:
  1. Kim-Wright = current vintage, not real-time vintage
  2. DFF < 0.5% split is exploratory, not primary
  3. N=13 episodes; 95% CI for hit rate is wide
  4. 3M/6M windows may partially overlap between episodes
""")
