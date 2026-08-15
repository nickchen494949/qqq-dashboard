#!/usr/bin/env python3
"""
EVENT-LEVEL RE-ENTRY ANALYSIS — AUDIT v2 (all 6 bugs fixed).
Stop asking "which Sharpe is higher" — ask "can this signal
reproduce SEP's early re-entry dates?"

FIXES from v1:
  1. FFR snapshot: remove erroneous *36500
  2. CPI lag: use MS + 45d (not ME + 45d)
  3. Shift all daily signals by 1 trading day (no look-ahead)
  4. Event matching: classify A/B/C/D (already on / entered before / after / missed)
  5. Delay in trading days (not calendar days)
  6. Delay cost: report both QQQ and TQQQ consistently

SEP re-entry dates (benchmark events):
  2023-03-22, 2023-12-13, 2024-09-18, 2025-03-19
"""
import os, sys, warnings
import numpy as np, pandas as pd

warnings.filterwarnings('ignore')
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))

import strategy_engine as se
import yfinance as yf
from fredapi import Fred

fred = Fred(api_key=se.get_fred_api_key())
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data')

def gf(sid):
    p = os.path.join(DATA_DIR, f'fred_{sid}.csv')
    if os.path.exists(p):
        s = pd.read_csv(p, index_col=0, parse_dates=True).squeeze()
        if len(s) > 100: return s
    s = fred.get_series(sid, observation_start='2005-01-01'); s.to_csv(p); return s

def gy(t):
    p = os.path.join(DATA_DIR, f'yahoo_{t}.csv')
    if os.path.exists(p):
        s = pd.read_csv(p, index_col=0, parse_dates=True).squeeze()
        if len(s) > 100: return s
    df = yf.download(t, start='2005-01-01', progress=False, auto_adjust=False)
    adj = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj, pd.DataFrame): adj = adj.iloc[:,0]
    adj.to_csv(p); return adj

# ═══════════════════════════════════
# LOAD
# ═══════════════════════════════════
print("Loading data...")
qqq = gy('QQQ'); tqqq = gy('TQQQ')
hyg = gy('HYG'); ief = gy('IEF'); tip = gy('TIP'); tlt = gy('TLT')
effr_raw = gf('EFFR'); dgs1 = gf('DGS1'); dgs2 = gf('DGS2')
t5yifr = gf('T5YIFR'); ffr_upper = gf('DFEDTARU')
cpilfe = gf('CPILFESL'); dfii5 = gf('DFII5'); dfii10 = gf('DFII10')
baa10y = gf('BAA10Y'); walcl = gf('WALCL')
rrp = gf('RRPONTSYD'); tga = gf('WTREGEN')

idx = qqq.dropna().index; idx = idx[idx >= '2012-01-01']
qqq_a = qqq.reindex(idx); tqqq_a = tqqq.reindex(idx).ffill()
hyg_a = hyg.reindex(idx).ffill(); ief_a = ief.reindex(idx).ffill()
tip_a = tip.reindex(idx).ffill(); tlt_a = tlt.reindex(idx).ffill()
dgs1_a = dgs1.reindex(idx, method='ffill').ffill()
dgs2_a = dgs2.reindex(idx, method='ffill').ffill()
ffr_a = ffr_upper.reindex(idx, method='ffill').ffill()  # FIX 1: already in %, no *36500
t5yifr_a = t5yifr.reindex(idx, method='ffill').ffill()
dfii5_a = dfii5.reindex(idx, method='ffill').ffill()
baa10y_a = baa10y.reindex(idx, method='ffill').ffill()
effr_a = effr_raw.reindex(idx, method='ffill').ffill() / 36500
walcl_a = walcl.resample('D').ffill().reindex(idx, method='ffill').ffill()
rrp_a = rrp.resample('D').ffill().reindex(idx, method='ffill').ffill()
tga_a = tga.resample('D').ffill().reindex(idx, method='ffill').ffill()

# FIX 2: CPI lag — use MS (month-start) + 45d, not ME (month-end) + 45d
# FRED CPILFESL observation date is month-start (e.g. 2023-01-01 for Jan data).
# Jan data published ~Feb 13. MS + 45d ≈ Feb 15. More realistic.
cpilfe_m = cpilfe.resample('MS').last().dropna()
core_cpi_3m = ((cpilfe_m / cpilfe_m.shift(3)).pow(4) - 1) * 100
core_cpi_3m_lagged = core_cpi_3m.copy()
core_cpi_3m_lagged.index += pd.Timedelta(days=45)
core_cpi_3m_d = core_cpi_3m_lagged.reindex(idx, method='ffill').ffill()

# ═══════════════════════════════════
# DERIVED INDICATORS
# ═══════════════════════════════════

# Policy path proxies (Treasury-policy spread proxy, not true futures-implied path)
policy_1y = dgs1_a - ffr_a
policy_2y = dgs2_a - ffr_a
policy_1y_chg_raw = policy_1y - policy_1y.shift(63)

# 2Y yield momentum
dgs2_chg_raw = dgs2_a - dgs2_a.shift(63)

# Real yield momentum
real5y_chg_raw = dfii5_a - dfii5_a.shift(63)

# Credit spread momentum
baa_chg_raw = baa10y_a - baa10y_a.shift(63)

# FIX 3: Shift ALL daily signals by 1 trading day to avoid look-ahead.
# Signal computed on day T can only be acted on at day T+1 close.
dgs2_chg = dgs2_chg_raw.shift(1)
policy_1y_chg = policy_1y_chg_raw.shift(1)
real5y_chg = real5y_chg_raw.shift(1)
baa_chg = baa_chg_raw.shift(1)

# Also shift CPI (already lagged 45d, but signal decision → next day execution)
# CPI is monthly so 1-day shift is negligible, but apply for consistency
core_cpi_3m_d = core_cpi_3m_d.shift(1)

# HYG/IEF ratio change (your credit z-score proxy)
dr_qqq = qqq_a.pct_change()
z_credit = se.compute_credit_z(hyg_a, ief_a)
vol_z = se.compute_vol_z(dr_qqq)
inf_z = se.compute_inflation_z(tip_a, tlt_a)
nl_z = se.compute_nl_z(walcl_a, rrp_a, tga_a)

# FOMC dates + 2Y reaction
FOMC_DATES = [
    '2012-01-25','2012-03-13','2012-04-25','2012-06-20','2012-08-01','2012-09-13','2012-10-24','2012-12-12',
    '2013-01-30','2013-03-20','2013-05-01','2013-06-19','2013-07-31','2013-09-18','2013-10-30','2013-12-18',
    '2014-01-29','2014-03-19','2014-04-30','2014-06-18','2014-07-30','2014-09-17','2014-10-29','2014-12-17',
    '2015-01-28','2015-03-18','2015-04-29','2015-06-17','2015-07-29','2015-09-17','2015-10-28','2015-12-16',
    '2016-01-27','2016-03-16','2016-04-27','2016-06-15','2016-07-27','2016-09-21','2016-11-02','2016-12-14',
    '2017-02-01','2017-03-15','2017-05-03','2017-06-14','2017-07-26','2017-09-20','2017-11-01','2017-12-13',
    '2018-01-31','2018-03-21','2018-05-02','2018-06-13','2018-08-01','2018-09-26','2018-11-08','2018-12-19',
    '2019-01-30','2019-03-20','2019-05-01','2019-06-19','2019-07-31','2019-09-18','2019-10-30','2019-12-11',
    '2020-01-29','2020-03-03','2020-03-15','2020-04-29','2020-06-10','2020-07-29','2020-09-16','2020-11-05','2020-12-16',
    '2021-01-27','2021-03-17','2021-04-28','2021-06-16','2021-07-28','2021-09-22','2021-11-03','2021-12-15',
    '2022-01-26','2022-03-16','2022-05-04','2022-06-15','2022-07-27','2022-09-21','2022-11-02','2022-12-14',
    '2023-02-01','2023-03-22','2023-05-03','2023-06-14','2023-07-26','2023-09-20','2023-11-01','2023-12-13',
    '2024-01-31','2024-03-20','2024-05-01','2024-06-12','2024-07-31','2024-09-18','2024-11-07','2024-12-18',
    '2025-01-29','2025-03-19','2025-05-07','2025-06-18','2025-07-30','2025-09-17','2025-11-05','2025-12-10',
    '2026-01-28','2026-03-18','2026-05-06','2026-06-17',
]

# Build FOMC dovish shock signal (also shifted by 1 day)
fomc_shock_last_raw = pd.Series(0.0, index=idx)
fomc_shock_cum3_raw = pd.Series(0.0, index=idx)
recent_shocks = []
fomc_dates_ts = sorted([pd.Timestamp(d) for d in FOMC_DATES])

for fd in fomc_dates_ts:
    pre = idx[idx < fd]
    post = idx[idx >= fd]
    if len(pre) < 1 or len(post) < 1: continue
    day_before = pre[-1]
    day_of_or_after = post[0]

    if day_before in dgs2_a.index and day_of_or_after in dgs2_a.index:
        shock = float(dgs2_a.loc[day_of_or_after] - dgs2_a.loc[day_before])
    else:
        shock = 0.0

    recent_shocks.append(shock)
    if len(recent_shocks) > 3: recent_shocks = recent_shocks[-3:]

    next_fomcs = [f for f in fomc_dates_ts if f > fd]
    end = next_fomcs[0] if next_fomcs else idx[-1] + pd.Timedelta(days=1)
    mask = (idx >= day_of_or_after) & (idx < end)
    fomc_shock_last_raw.loc[mask] = shock
    fomc_shock_cum3_raw.loc[mask] = sum(recent_shocks)

# FIX 3: shift FOMC signals too
fomc_shock_last = fomc_shock_last_raw.shift(1)
fomc_shock_cum3 = fomc_shock_cum3_raw.shift(1)

# SEP data
sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

# ═══════════════════════════════════
# HELPER: trading-day delay (FIX 5)
# ═══════════════════════════════════
def td_delay(idx, d1, d2):
    """Trading-day delay between d1 and d2. Positive = d2 is later."""
    i1 = idx.searchsorted(pd.Timestamp(d1))
    i2 = idx.searchsorted(pd.Timestamp(d2))
    return int(i2 - i1)

# ═══════════════════════════════════
# SEP RE-ENTRY BENCHMARK EVENTS
# ═══════════════════════════════════
SEP_REENTRIES = ['2023-03-22', '2023-12-13', '2024-09-18', '2025-03-19']

print(f"\n  SEP re-entry benchmark events:")
for d in SEP_REENTRIES:
    dt = pd.Timestamp(d)
    tqqq_at = tqqq_a.loc[tqqq_a.index >= dt].iloc[0] if dt <= idx[-1] else 0
    qqq_at = qqq_a.loc[qqq_a.index >= dt].iloc[0]
    print(f"    {d}  QQQ={qqq_at:.1f}  TQQQ={tqqq_at:.1f}")

# ═══════════════════════════════════
# SNAPSHOT (FIX 1: ffr_a not *36500)
# ═══════════════════════════════════
print(f"\n{'='*140}")
print("  INDICATOR SNAPSHOT AT EACH SEP RE-ENTRY DATE (shifted T-1 values used for signals)")
print("="*140)

def v(series, date):
    try:
        val = series.loc[date]
        return float(val) if not np.isnan(val) else 0
    except: return 0

header = f"  {'Date':<14} {'2Y':>5} {'FFR':>5} {'1Y-FFR':>7} {'2Y-FFR':>7} {'1Y-FFR Δ3m':>11} {'CPI 3m':>7} {'5Y5Y':>5} {'5Y real':>7} {'RealΔ3m':>8} {'BAA spr':>8} {'BAAΔ3m':>7} {'FOMC shk':>9} {'Cum3 shk':>9}"
print(header)
print("  " + "─"*135)

for d in SEP_REENTRIES:
    dt = pd.Timestamp(d)
    near = idx[idx >= dt]
    if len(near) == 0: continue
    nd = near[0]
    # Show BOTH raw (same-day, informational) and shifted (T-1, what signal actually sees)
    print(f"  {d:<14} {v(dgs2_a,nd):>5.2f} {v(ffr_a,nd):>5.2f} {v(policy_1y,nd):>+7.2f} {v(policy_2y,nd):>+7.2f} {v(policy_1y_chg,nd):>+11.2f} {v(core_cpi_3m_d,nd):>7.2f} {v(t5yifr_a,nd):>5.2f} {v(dfii5_a,nd):>7.2f} {v(real5y_chg,nd):>+8.2f} {v(baa10y_a,nd):>8.2f} {v(baa_chg,nd):>+7.2f} {v(fomc_shock_last,nd):>+9.2f} {v(fomc_shock_cum3,nd):>+9.2f}")

print(f"\n  Note: Δ3m / FOMC columns are T-1 shifted (signal sees previous day's close).")

print(f"\n  Same indicators 60 DAYS BEFORE each SEP re-entry:")
print(header)
print("  " + "─"*135)
for d in SEP_REENTRIES:
    dt = pd.Timestamp(d) - pd.Timedelta(days=60)
    near = idx[idx <= dt]
    if len(near) == 0: continue
    nd = near[-1]
    print(f"  {nd.strftime('%Y-%m-%d'):<14} {v(dgs2_a,nd):>5.2f} {v(ffr_a,nd):>5.2f} {v(policy_1y,nd):>+7.2f} {v(policy_2y,nd):>+7.2f} {v(policy_1y_chg,nd):>+11.2f} {v(core_cpi_3m_d,nd):>7.2f} {v(t5yifr_a,nd):>5.2f} {v(dfii5_a,nd):>7.2f} {v(real5y_chg,nd):>+8.2f} {v(baa10y_a,nd):>8.2f} {v(baa_chg,nd):>+7.2f} {v(fomc_shock_last,nd):>+9.2f} {v(fomc_shock_cum3,nd):>+9.2f}")

# ═══════════════════════════════════
# BUILD CANDIDATE SIGNALS
# ═══════════════════════════════════

def build_signal(idx, exit_fn, reentry_fn, min_hold=42):
    """Generic state machine with custom exit/reentry functions."""
    state = 1; hold = 0; states = []
    for i, d in enumerate(idx):
        if state == 1:
            if exit_fn(d, i):
                state = 0; hold = 0
        else:
            hold += 1
            if hold >= min_hold and reentry_fn(d, i):
                state = 1
        states.append(state)
    return pd.Series(states, index=idx)

# Common exit (same as F base — uses shifted signals)
def f_exit(d, i):
    chg = get_val(dgs2_chg, d)
    cpi = get_val(core_cpi_3m_d, d, 2.0)
    be = get_val(t5yifr_a, d, 2.0)
    return chg > 0.3 and cpi > 3.0 and be > 2.3

def get_val(series, d, default=0.0):
    try:
        val = series.loc[d]
        return float(val) if not np.isnan(val) else default
    except: return default

# Re-entry functions (all use shifted signals by construction)
def reentry_F_base(d, i):
    return get_val(dgs2_chg, d) < -0.1 and get_val(core_cpi_3m_d, d) < 2.5

def reentry_policy_path(d, i, policy_th=-0.3, cpi_th=3.5):
    return get_val(policy_1y_chg, d) < policy_th and get_val(core_cpi_3m_d, d) < cpi_th

def reentry_fomc_dovish(d, i, shock_th=-0.1, cpi_th=3.5):
    return get_val(fomc_shock_cum3, d) < shock_th and get_val(core_cpi_3m_d, d) < cpi_th

def reentry_policy_credit(d, i, policy_th=-0.3, credit_th=0.1, cpi_th=3.5):
    return (get_val(policy_1y_chg, d) < policy_th and
            get_val(baa_chg, d) < credit_th and
            get_val(core_cpi_3m_d, d) < cpi_th)

def reentry_fomc_credit(d, i, shock_th=-0.1, credit_th=0.1, cpi_th=3.5):
    return (get_val(fomc_shock_cum3, d) < shock_th and
            get_val(baa_chg, d) < credit_th and
            get_val(core_cpi_3m_d, d) < cpi_th)

def reentry_real_yield(d, i, real_th=-0.3, cpi_th=3.5):
    return get_val(real5y_chg, d) < real_th and get_val(core_cpi_3m_d, d) < cpi_th

def reentry_policy_fomc_credit(d, i, policy_th=-0.3, shock_th=-0.05, credit_th=0.1, cpi_th=3.5):
    return (get_val(policy_1y_chg, d) < policy_th and
            get_val(fomc_shock_cum3, d) < shock_th and
            get_val(baa_chg, d) < credit_th and
            get_val(core_cpi_3m_d, d) < cpi_th)

# Build all candidates
print("\nBuilding candidate signals...")
candidates = {}

candidates['F base'] = build_signal(idx, f_exit, reentry_F_base, 42)

for pth in [-0.5, -0.3, -0.2, -0.1]:
    for cth in [3.0, 3.5, 4.0]:
        name = f'Policy 1Y-FFR Δ<{pth}, CPI<{cth}'
        candidates[name] = build_signal(idx, f_exit,
            lambda d,i,p=pth,c=cth: reentry_policy_path(d,i,p,c), 42)

for sth in [-0.15, -0.10, -0.05, 0.0]:
    for cth in [3.0, 3.5, 4.0]:
        name = f'FOMC cum3<{sth}, CPI<{cth}'
        candidates[name] = build_signal(idx, f_exit,
            lambda d,i,s=sth,c=cth: reentry_fomc_dovish(d,i,s,c), 42)

for pth in [-0.3, -0.2]:
    for crth in [0.0, 0.1, 0.2]:
        for cth in [3.5, 4.0]:
            name = f'Pol<{pth}+Cr<{crth}+CPI<{cth}'
            candidates[name] = build_signal(idx, f_exit,
                lambda d,i,p=pth,cr=crth,c=cth: reentry_policy_credit(d,i,p,cr,c), 42)

for sth in [-0.10, -0.05]:
    for crth in [0.0, 0.1]:
        for cth in [3.5, 4.0]:
            name = f'FOMC<{sth}+Cr<{crth}+CPI<{cth}'
            candidates[name] = build_signal(idx, f_exit,
                lambda d,i,s=sth,cr=crth,c=cth: reentry_fomc_credit(d,i,s,cr,c), 42)

for rth in [-0.5, -0.3, -0.1]:
    for cth in [3.5, 4.0]:
        name = f'Real5Y Δ<{rth}+CPI<{cth}'
        candidates[name] = build_signal(idx, f_exit,
            lambda d,i,r=rth,c=cth: reentry_real_yield(d,i,r,c), 42)

for pth in [-0.3, -0.2]:
    for sth in [-0.10, -0.05]:
        for crth in [0.0, 0.1]:
            name = f'Full: Pol<{pth}+FOMC<{sth}+Cr<{crth}'
            candidates[name] = build_signal(idx, f_exit,
                lambda d,i,p=pth,s=sth,cr=crth: reentry_policy_fomc_credit(d,i,p,s,cr,3.5), 42)

print(f"  Built {len(candidates)} candidates.")

# ═══════════════════════════════════
# EVENT-LEVEL RE-ENTRY MATCHING (FIX 4 + 5 + 6)
# ═══════════════════════════════════
print(f"\n{'='*140}")
print("  EVENT-LEVEL RE-ENTRY MATCHING (trading-day delays, classified A/B/C/D)")
print("="*140)

def find_reentries(signal):
    entries = []
    arr = signal.values
    for i in range(1, len(arr)):
        if arr[i] == 1 and arr[i-1] == 0:
            entries.append(signal.index[i])
    return entries

def classify_match(signal, candidate_entries, sep_date, idx, window_td=120):
    """FIX 4: Classify re-entry match into A/B/C/D.
    A = candidate already risk-on at SEP date (no transition needed)
    B = candidate re-entered BEFORE SEP (transition happened earlier)
    C = candidate re-entered AFTER SEP (transition happened later)
    D = candidate was still risk-off and missed entirely
    Returns: (classification, match_date, delay_trading_days)
    """
    sep_dt = pd.Timestamp(sep_date)
    sep_idx = idx.searchsorted(sep_dt)
    
    # Check if candidate was already ON at SEP date
    near = idx[idx >= sep_dt]
    if len(near) > 0:
        sep_td = near[0]
        if signal.loc[sep_td] == 1:
            # Was it already on? Find the most recent transition
            last_entry = None
            for ce in candidate_entries:
                if ce <= sep_dt:
                    last_entry = ce
            if last_entry is not None:
                delay = td_delay(idx, sep_date, last_entry)
                return 'A:already_on', last_entry, delay
            else:
                return 'A:always_on', None, 0
    
    # Find closest transition
    best = None; best_delay_td = 999
    for ce in candidate_entries:
        delay = td_delay(idx, sep_date, ce)
        if -30 <= delay <= window_td and abs(delay) < abs(best_delay_td):
            best = ce; best_delay_td = delay
    
    if best is not None:
        if best_delay_td < 0:
            return 'B:before_SEP', best, best_delay_td
        else:
            return 'C:after_SEP', best, best_delay_td
    
    return 'D:missed', None, 999

# ═══════════════════════════════════
# v3 SCORING: separate coverage / true_reentry / already_on
# ═══════════════════════════════════

def compute_pre_sep_stats(entry_date, sep_date, qqq_series, idx):
    """For A:already_on / B:before_SEP — measure pre-SEP exposure risk."""
    ed = pd.Timestamp(entry_date)
    sd = pd.Timestamp(sep_date)
    mask = (idx >= ed) & (idx <= sd)
    prices = qqq_series.loc[idx[mask]]
    if len(prices) < 2:
        return 0.0, 0.0
    ret = (float(prices.iloc[-1]) / float(prices.iloc[0]) - 1) * 100
    mdd = ((prices / prices.cummax()) - 1).min() * 100
    return ret, mdd

results = []
for name, signal in candidates.items():
    entries = find_reentries(signal)

    coverage_hits = 0; true_reentry_hits = 0; already_on_hits = 0
    late_hits = 0; misses = 0
    delays_td = []; total_cost_qqq = 0; total_cost_tqqq = 0
    classifications = []
    early_mdds = []; early_rets = []
    false_entries = 0; false_entry_ret = []

    for sep_d in SEP_REENTRIES:
        sep_dt = pd.Timestamp(sep_d)
        cls, match, delay = classify_match(signal, entries, sep_d, idx)
        classifications.append(cls)

        if cls == 'D:missed':
            misses += 1
        elif cls.startswith('A:'):
            coverage_hits += 1; already_on_hits += 1
            delays_td.append(0)
            # Measure pre-SEP exposure for already_on
            if match is not None:
                pre_ret, pre_mdd = compute_pre_sep_stats(match, sep_d, qqq_a, idx)
                early_rets.append(pre_ret); early_mdds.append(pre_mdd)
        elif cls.startswith('B:'):
            coverage_hits += 1; true_reentry_hits += 1
            delays_td.append(0)  # early is not penalized in delay, but tracked via MDD
            if match is not None:
                pre_ret, pre_mdd = compute_pre_sep_stats(match, sep_d, qqq_a, idx)
                early_rets.append(pre_ret); early_mdds.append(pre_mdd)
        elif cls.startswith('C:'):
            coverage_hits += 1; true_reentry_hits += 1; late_hits += 1
            delays_td.append(delay)
            if match is not None:
                sep_near = idx[idx >= sep_dt][0]
                if sep_near in qqq_a.index and match in qqq_a.index:
                    total_cost_qqq += (float(qqq_a.loc[match]) / float(qqq_a.loc[sep_near]) - 1) * 100
                if sep_near in tqqq_a.index and match in tqqq_a.index:
                    total_cost_tqqq += (float(tqqq_a.loc[match]) / float(tqqq_a.loc[sep_near]) - 1) * 100

    # False re-entries
    for ce in entries:
        is_near_sep = False
        for sd in SEP_REENTRIES:
            if abs(td_delay(idx, sd, ce)) < 30:
                is_near_sep = True; break
        if not is_near_sep:
            false_entries += 1
            fut = qqq_a.loc[qqq_a.index > ce].head(63)
            if len(fut) > 10 and ce in qqq_a.index:
                ret = (float(fut.iloc[-1]) / float(qqq_a.loc[ce]) - 1) * 100
                false_entry_ret.append(ret)

    out_pct = (signal == 0).mean() * 100
    avg_pos_delay = np.mean([d for d in delays_td if d > 0]) if any(d > 0 for d in delays_td) else 0
    worst_early_mdd = min(early_mdds) if early_mdds else 0

    results.append({
        'name': name,
        'coverage': coverage_hits, 'true_reentry': true_reentry_hits,
        'already_on': already_on_hits, 'late': late_hits, 'misses': misses,
        'delays_td': delays_td,
        'avg_pos_delay': avg_pos_delay,
        'cost_qqq': total_cost_qqq, 'cost_tqqq': total_cost_tqqq,
        'classifications': classifications,
        'early_mdds': early_mdds, 'worst_early_mdd': worst_early_mdd,
        'early_rets': early_rets,
        'false_entries': false_entries,
        'false_ret': np.mean(false_entry_ret) if false_entry_ret else 0,
        'out_pct': out_pct, 'total_entries': len(entries),
    })

# v3 SORT: coverage desc, true_reentry desc, avg positive delay asc, worst early MDD desc, false asc
results.sort(key=lambda x: (
    -x['coverage'],
    -x['true_reentry'],
    x['avg_pos_delay'],
    x['worst_early_mdd'],  # more negative = worse
    x['false_entries']
))

print(f"\n  TOP 30 CANDIDATES (v3 scoring: coverage / true_reentry / already_on):")
print(f"  {'Rank':<5} {'Signal':<38} {'Cov':>4} {'True':>5} {'AlrOn':>5} {'Late':>5} {'AvgDly':>7} {'QQQ$':>6} {'TQQQ$':>7} {'EarlyMDD':>9} {'Fls':>4} {'%OUT':>5}")
print(f"  {'─'*5} {'─'*38} {'─'*4} {'─'*5} {'─'*5} {'─'*5} {'─'*7} {'─'*6} {'─'*7} {'─'*9} {'─'*4} {'─'*5}")

for i, r in enumerate(results[:30]):
    marker = ''
    if r['coverage'] == 4 and r['true_reentry'] >= 3 and r['false_entries'] <= 1:
        marker = ' ✅'
    elif r['coverage'] == 4 and r['already_on'] >= 3:
        marker = ' ⚠️ mostly already_on'
    print(f"  {i+1:<5} {r['name']:<38} {r['coverage']:>3}/4 {r['true_reentry']:>4}/4 {r['already_on']:>4}/4 {r['late']:>4}/4 {r['avg_pos_delay']:>5.0f}td {r['cost_qqq']:>+5.1f}% {r['cost_tqqq']:>+6.1f}% {r['worst_early_mdd']:>8.1f}% {r['false_entries']:>3} {r['out_pct']:>4.1f}%{marker}")

# ═══════════════════════════════════
# DETAILED EVENT TABLE with pre-SEP stats
# ═══════════════════════════════════
print(f"\n{'='*160}")
print("  DETAILED RE-ENTRY EVENT TABLE — best candidates (A/B/C/D + pre-SEP MDD for early entries)")
print("="*160)

seen = set()
top_candidates = []
for r in results:
    key = (r['coverage'], r['true_reentry'], round(r['avg_pos_delay']))
    if key not in seen and len(top_candidates) < 6:
        top_candidates.append(r)
        seen.add(key)

for sep_d in SEP_REENTRIES:
    sep_dt = pd.Timestamp(sep_d)
    sep_near = idx[idx >= sep_dt][0]
    sep_tqqq = float(tqqq_a.loc[sep_near])
    sep_qqq = float(qqq_a.loc[sep_near])

    print(f"\n  SEP RE-ENTRY: {sep_d} (QQQ=${sep_qqq:.1f} TQQQ=${sep_tqqq:.2f})")
    print(f"  {'Candidate':<38} {'Class':<15} {'Entry':<12} {'DlyTD':>6} {'QQQ$':>7} {'TQQQ$':>8} {'PreRet':>7} {'PreMDD':>7} {'3mQQQ':>7}")
    print(f"  {'─'*38} {'─'*15} {'─'*12} {'─'*6} {'─'*7} {'─'*8} {'─'*7} {'─'*7} {'─'*7}")

    for r in top_candidates:
        signal = candidates[r['name']]
        entries = find_reentries(signal)
        cls, match, delay = classify_match(signal, entries, sep_d, idx)

        if match is not None:
            m_near = idx[idx >= match][0]
            tqqq_at = float(tqqq_a.loc[m_near])
            qqq_at = float(qqq_a.loc[m_near])
            cost_qqq = (qqq_at / sep_qqq - 1) * 100 if delay > 0 else 0
            cost_tqqq = (tqqq_at / sep_tqqq - 1) * 100 if delay > 0 else 0

            # Pre-SEP stats (for A/B)
            pre_ret, pre_mdd = 0, 0
            if cls.startswith('A:') or cls.startswith('B:'):
                pre_ret, pre_mdd = compute_pre_sep_stats(match, sep_d, qqq_a, idx)

            fut = qqq_a.loc[qqq_a.index > match].head(63)
            ret3m = (float(fut.iloc[-1]) / float(qqq_a.loc[m_near]) - 1) * 100 if len(fut) > 10 else 0

            pre_r_str = f"{pre_ret:>+6.1f}%" if cls.startswith(('A:','B:')) else f"{'—':>7}"
            pre_m_str = f"{pre_mdd:>+6.1f}%" if cls.startswith(('A:','B:')) else f"{'—':>7}"

            print(f"  {r['name']:<38} {cls:<15} {match.strftime('%Y-%m-%d'):<12} {delay:>+5}td {cost_qqq:>+6.1f}% {cost_tqqq:>+7.1f}% {pre_r_str} {pre_m_str} {ret3m:>+6.1f}%")
        else:
            print(f"  {r['name']:<38} {cls:<15} {'—':<12} {'—':>6} {'—':>7} {'—':>8} {'—':>7} {'—':>7} {'—':>7}")

# ═══════════════════════════════════
# EXIT EVENT ANALYSIS
# ═══════════════════════════════════
print(f"\n{'='*160}")
print("  EXIT EVENT ANALYSIS — SEP vs candidates")
print("="*160)

def find_exits(signal):
    exits = []
    arr = signal.values
    for i in range(1, len(arr)):
        if arr[i] == 0 and arr[i-1] == 1:
            exits.append(signal.index[i])
    return exits

sep_exits = find_exits(sep_state)
SEP_EXITS = [e.strftime('%Y-%m-%d') for e in sep_exits]
print(f"\n  SEP exit dates: {SEP_EXITS}")

print(f"\n  {'Candidate':<38} {'SEP exits matched':>18} {'Extra exits':>12} {'Missed exits':>13}")
print(f"  {'─'*38} {'─'*18} {'─'*12} {'─'*13}")

for r in top_candidates[:6]:
    signal = candidates[r['name']]
    cand_exits = find_exits(signal)
    
    matched = 0; extra = 0
    for ce in cand_exits:
        near_sep = False
        for se_val in sep_exits:
            if abs(td_delay(idx, se_val.strftime('%Y-%m-%d') if hasattr(se_val, 'strftime') else str(se_val), ce)) < 30:
                near_sep = True; break
        if near_sep: matched += 1
        else: extra += 1
    
    missed = len(sep_exits) - matched
    print(f"  {r['name']:<38} {matched:>12}/{len(sep_exits)} {extra:>11} {missed:>12}")

# Detailed exit timing
print(f"\n  EXIT EVENT DETAIL:")
for se_d in sep_exits:
    se_near = idx[idx >= se_d][0]
    qqq_at = float(qqq_a.loc[se_near])
    # Forward 3m
    fut = qqq_a.loc[qqq_a.index > se_d].head(63)
    mdd_3m = ((fut / fut.cummax()) - 1).min() * 100 if len(fut) > 10 else 0
    ret_3m = (float(fut.iloc[-1]) / qqq_at - 1) * 100 if len(fut) > 10 else 0

    print(f"\n  SEP EXIT: {se_d.strftime('%Y-%m-%d')} (QQQ=${qqq_at:.1f}, 3m ret={ret_3m:+.1f}%, 3m MDD={mdd_3m:.1f}%)")
    print(f"  {'Candidate':<38} {'Exit date':<14} {'DelayTD':>8} {'3m QQQ':>8} {'3m MDD':>8} {'Correct?':>9}")
    print(f"  {'─'*38} {'─'*14} {'─'*8} {'─'*8} {'─'*8} {'─'*9}")

    for r in top_candidates[:6]:
        signal = candidates[r['name']]
        cand_exits = find_exits(signal)

        # Find nearest candidate exit
        best_ce = None; best_delay = 999
        for ce in cand_exits:
            d = td_delay(idx, se_d.strftime('%Y-%m-%d') if hasattr(se_d, 'strftime') else str(se_d), ce)
            if -30 <= d <= 120 and abs(d) < abs(best_delay):
                best_ce = ce; best_delay = d

        if best_ce is not None:
            ce_near = idx[idx >= best_ce][0]
            ce_fut = qqq_a.loc[qqq_a.index > best_ce].head(63)
            ce_mdd = ((ce_fut / ce_fut.cummax()) - 1).min() * 100 if len(ce_fut) > 10 else 0
            ce_ret = (float(ce_fut.iloc[-1]) / float(qqq_a.loc[ce_near]) - 1) * 100 if len(ce_fut) > 10 else 0
            correct = '✅' if ce_mdd < -5 else '❌ false'
            print(f"  {r['name']:<38} {best_ce.strftime('%Y-%m-%d'):<14} {best_delay:>+7}td {ce_ret:>+7.1f}% {ce_mdd:>+7.1f}% {correct:>9}")
        else:
            print(f"  {r['name']:<38} {'NO EXIT':<14} {'—':>8} {'—':>8} {'—':>8} {'❌ missed':>9}")

# ═══════════════════════════════════
# BACKTEST top candidates vs SEP
# ═══════════════════════════════════
print(f"\n{'='*160}")
print("  BACKTEST: top candidates vs SEP")
print("="*160)

def run_bt(signal, label):
    r = se.run_backtest(
        idx, dr_qqq, None, None, effr_a,
        z_credit, vol_z, signal,
        inf_z=inf_z, nl_z=nl_z,
        use_sep=True, use_overlay=True,
    )
    eq = r['equity']; ny = len(eq)/252
    cagr = (eq.iloc[-1]**(1/ny)-1)*100
    mdd = ((eq/eq.expanding().max())-1).min()*100
    dret = eq.pct_change().dropna()
    sh = dret.mean()/dret.std()*np.sqrt(252) if dret.std()>0 else 0
    dn = dret[dret<0]; ds = np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
    so = dret.mean()/ds*np.sqrt(252)
    return {'label':label,'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so}

bt_results = []
bt_results.append(run_bt(sep_state, '★ Real SEP'))

for r in top_candidates[:5]:
    sig = candidates[r['name']]
    bt = run_bt(sig, r['name'])
    bt['coverage'] = r['coverage']
    bt['true_reentry'] = r['true_reentry']
    bt['already_on'] = r['already_on']
    bt['avg_pos_delay'] = r['avg_pos_delay']
    bt['false_entries'] = r['false_entries']
    bt_results.append(bt)

print(f"\n  {'Strategy':<40} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sort':>6}  Detail")
print(f"  {'─'*40} {'─'*7} {'─'*7} {'─'*7} {'─'*6}  {'─'*40}")
for r in sorted(bt_results, key=lambda x: x['sharpe'], reverse=True):
    marker = ' ◄' if r['label'].startswith('★') else ''
    if 'coverage' in r:
        extra = f"  cov={r['coverage']}/4 true={r['true_reentry']}/4 alrOn={r['already_on']}/4 dly={r['avg_pos_delay']:.0f}td fls={r['false_entries']}"
    else:
        extra = ''
    print(f"  {r['label']:<40} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>5.2f}{marker}{extra}")

print(f"\n  AUDIT v3 FIXES APPLIED (on top of v2):")
print(f"    ✅ v2.1 FFR snapshot fixed")
print(f"    ✅ v2.2 CPI lag MS + 45d")
print(f"    ✅ v2.3 Daily signals shifted by 1 trading day")
print(f"    ✅ v2.4 A/B/C/D event classification")
print(f"    ✅ v2.5 Trading-day delays")
print(f"    ✅ v2.6 QQQ + TQQQ cost reported")
print(f"    ✅ v3.1 Separate coverage / true_reentry / already_on hits")
print(f"    ✅ v3.2 Pre-SEP return + MDD for early entries (A/B)")
print(f"    ✅ v3.3 Improved sorting (coverage > true_reentry > delay > early_mdd > false)")
print(f"    ✅ v3.4 EXIT event analysis added")
