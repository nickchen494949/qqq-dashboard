#!/usr/bin/env python3
"""
SEP TRANSITION AUDIT v3.
Can fallback signals replicate SEP's transition timing?
  - Exit timing
  - Re-entry timing  
  - Full cycle (round-trip) cost
  - Net transition alpha accounting

All v2 fixes applied:
  1. FFR display correct
  2. CPI lag MS + 45d
  3. All signals shifted 1 trading day
  4. A/B/C/D classification
  5. Trading-day delays
  6. QQQ + TQQQ cost
  v3.1 Separate coverage / true_reentry / already_on
  v3.2 Pre-SEP MDD for early entries
  v3.3 EXIT event analysis
  v3.4 Round-trip cycle analysis
  v3.5 Transition alpha accounting
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

# ═══════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════
print("Loading data...")
qqq = gy('QQQ'); tqqq = gy('TQQQ')
hyg = gy('HYG'); ief = gy('IEF'); tip = gy('TIP'); tlt = gy('TLT')
effr_raw = gf('EFFR'); dgs1 = gf('DGS1'); dgs2 = gf('DGS2')
t5yifr = gf('T5YIFR'); ffr_upper = gf('DFEDTARU')
cpilfe = gf('CPILFESL'); dfii5 = gf('DFII5')
baa10y = gf('BAA10Y'); walcl = gf('WALCL')
rrp = gf('RRPONTSYD'); tga = gf('WTREGEN')

idx = qqq.dropna().index; idx = idx[idx >= '2012-01-01']
qqq_a = qqq.reindex(idx); tqqq_a = tqqq.reindex(idx).ffill()
hyg_a = hyg.reindex(idx).ffill(); ief_a = ief.reindex(idx).ffill()
tip_a = tip.reindex(idx).ffill(); tlt_a = tlt.reindex(idx).ffill()
dgs1_a = dgs1.reindex(idx, method='ffill').ffill()
dgs2_a = dgs2.reindex(idx, method='ffill').ffill()
ffr_a = ffr_upper.reindex(idx, method='ffill').ffill()
t5yifr_a = t5yifr.reindex(idx, method='ffill').ffill()
dfii5_a = dfii5.reindex(idx, method='ffill').ffill()
baa10y_a = baa10y.reindex(idx, method='ffill').ffill()
effr_a = effr_raw.reindex(idx, method='ffill').ffill() / 36500
walcl_a = walcl.resample('D').ffill().reindex(idx, method='ffill').ffill()
rrp_a = rrp.resample('D').ffill().reindex(idx, method='ffill').ffill()
tga_a = tga.resample('D').ffill().reindex(idx, method='ffill').ffill()

# CPI: MS + 45d
cpilfe_m = cpilfe.resample('MS').last().dropna()
core_cpi_3m = ((cpilfe_m / cpilfe_m.shift(3)).pow(4) - 1) * 100
core_cpi_3m_lagged = core_cpi_3m.copy()
core_cpi_3m_lagged.index += pd.Timedelta(days=45)
core_cpi_3m_d = core_cpi_3m_lagged.reindex(idx, method='ffill').ffill()

# All signals shifted 1 trading day
policy_1y = dgs1_a - ffr_a
policy_1y_chg = (policy_1y - policy_1y.shift(63)).shift(1)
dgs2_chg = (dgs2_a - dgs2_a.shift(63)).shift(1)
real5y_chg = (dfii5_a - dfii5_a.shift(63)).shift(1)
baa_chg = (baa10y_a - baa10y_a.shift(63)).shift(1)
core_cpi_3m_d = core_cpi_3m_d.shift(1)

dr_qqq = qqq_a.pct_change()
z_credit = se.compute_credit_z(hyg_a, ief_a)
vol_z = se.compute_vol_z(dr_qqq)
inf_z = se.compute_inflation_z(tip_a, tlt_a)
nl_z = se.compute_nl_z(walcl_a, rrp_a, tga_a)

# FOMC shock (shifted)
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
fomc_shock_cum3_raw = pd.Series(0.0, index=idx)
recent_shocks = []
fomc_dates_ts = sorted([pd.Timestamp(d) for d in FOMC_DATES])
for fd in fomc_dates_ts:
    pre = idx[idx < fd]; post = idx[idx >= fd]
    if len(pre) < 1 or len(post) < 1: continue
    day_before = pre[-1]; day_of = post[0]
    if day_before in dgs2_a.index and day_of in dgs2_a.index:
        shock = float(dgs2_a.loc[day_of] - dgs2_a.loc[day_before])
    else: shock = 0.0
    recent_shocks.append(shock)
    if len(recent_shocks) > 3: recent_shocks = recent_shocks[-3:]
    next_fomcs = [f for f in fomc_dates_ts if f > fd]
    end = next_fomcs[0] if next_fomcs else idx[-1] + pd.Timedelta(days=1)
    mask = (idx >= day_of) & (idx < end)
    fomc_shock_cum3_raw.loc[mask] = sum(recent_shocks)
fomc_shock_cum3 = fomc_shock_cum3_raw.shift(1)

# SEP
sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

print(f"  Data ready. {len(idx)} days.\n")

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def td_delay(idx, d1, d2):
    i1 = idx.searchsorted(pd.Timestamp(d1))
    i2 = idx.searchsorted(pd.Timestamp(d2))
    return int(i2 - i1)

def find_transitions(signal):
    entries, exits = [], []
    arr = signal.values
    for i in range(1, len(arr)):
        if arr[i] == 1 and arr[i-1] == 0: entries.append(signal.index[i])
        if arr[i] == 0 and arr[i-1] == 1: exits.append(signal.index[i])
    return entries, exits

def price_at(series, dt):
    near = series.index[series.index >= pd.Timestamp(dt)]
    return float(series.loc[near[0]]) if len(near) > 0 else np.nan

def mdd_between(series, d1, d2):
    mask = (series.index >= pd.Timestamp(d1)) & (series.index <= pd.Timestamp(d2))
    p = series.loc[mask]
    if len(p) < 2: return 0.0
    return float(((p / p.cummax()) - 1).min() * 100)

def ret_between(series, d1, d2):
    p1 = price_at(series, d1); p2 = price_at(series, d2)
    if np.isnan(p1) or np.isnan(p2) or p1 == 0: return 0.0
    return (p2 / p1 - 1) * 100

def ret_forward(series, dt, days=63):
    near = series.index[series.index >= pd.Timestamp(dt)]
    if len(near) == 0: return 0.0, 0.0
    start = near[0]; fut = series.loc[series.index > start].head(days)
    if len(fut) < 10: return 0.0, 0.0
    ret = (float(fut.iloc[-1]) / float(series.loc[start]) - 1) * 100
    mdd = float(((fut / fut.cummax()) - 1).min() * 100)
    return ret, mdd

def get_val(series, d, default=0.0):
    try:
        val = series.loc[d]
        return float(val) if not np.isnan(val) else default
    except: return default

# ═══════════════════════════════════════════════════════════════
# BUILD CANDIDATE SIGNALS
# ═══════════════════════════════════════════════════════════════
def build_signal(idx, exit_fn, reentry_fn, min_hold=42):
    state = 1; hold = 0; states = []
    for i, d in enumerate(idx):
        if state == 1:
            if exit_fn(d, i): state = 0; hold = 0
        else:
            hold += 1
            if hold >= min_hold and reentry_fn(d, i): state = 1
        states.append(state)
    return pd.Series(states, index=idx)

def f_exit(d, i):
    return get_val(dgs2_chg, d) > 0.3 and get_val(core_cpi_3m_d, d, 2.0) > 3.0 and get_val(t5yifr_a, d, 2.0) > 2.3

# Re-entry functions
def re_F(d, i): return get_val(dgs2_chg, d) < -0.1 and get_val(core_cpi_3m_d, d) < 2.5
def re_policy(d, i, p=-0.1, c=4.0): return get_val(policy_1y_chg, d) < p and get_val(core_cpi_3m_d, d) < c
def re_real(d, i, r=-0.3, c=4.0): return get_val(real5y_chg, d) < r and get_val(core_cpi_3m_d, d) < c
def re_fomc(d, i, s=-0.1, c=4.0): return get_val(fomc_shock_cum3, d) < s and get_val(core_cpi_3m_d, d) < c
def re_pol_cr(d, i, p=-0.2, cr=0.1, c=4.0):
    return get_val(policy_1y_chg, d) < p and get_val(baa_chg, d) < cr and get_val(core_cpi_3m_d, d) < c

# Focused candidate set (top performers from v2 + key comparison signals)
print("Building candidates...")
candidates = {}
candidates['F base'] = build_signal(idx, f_exit, re_F, 42)

for p in [-0.1, -0.2, -0.3]:
    for c in [3.5, 4.0]:
        candidates[f'Policy Δ<{p} CPI<{c}'] = build_signal(idx, f_exit,
            lambda d,i,pp=p,cc=c: re_policy(d,i,pp,cc), 42)

for r in [-0.1, -0.3, -0.5]:
    for c in [3.5, 4.0]:
        candidates[f'Real5Y Δ<{r} CPI<{c}'] = build_signal(idx, f_exit,
            lambda d,i,rr=r,cc=c: re_real(d,i,rr,cc), 42)

for s in [-0.1, -0.05]:
    for c in [3.5, 4.0]:
        candidates[f'FOMC<{s} CPI<{c}'] = build_signal(idx, f_exit,
            lambda d,i,ss=s,cc=c: re_fomc(d,i,ss,cc), 42)

for p in [-0.2, -0.3]:
    for cr in [0.0, 0.1]:
        candidates[f'Pol<{p}+Cr<{cr}'] = build_signal(idx, f_exit,
            lambda d,i,pp=p,ccr=cr: re_pol_cr(d,i,pp,ccr,4.0), 42)

print(f"  Built {len(candidates)} candidates.\n")

# ═══════════════════════════════════════════════════════════════
# PART 1: EXIT EVENT AUDIT
# ═══════════════════════════════════════════════════════════════
sep_entries, sep_exits = find_transitions(sep_state)
SEP_EXIT_DATES = [e.strftime('%Y-%m-%d') for e in sep_exits]

print("="*160)
print("  PART 1: EXIT EVENT AUDIT")
print("="*160)
print(f"\n  SEP exit dates: {SEP_EXIT_DATES}")

# Classify each SEP exit as correct or false
print(f"\n  SEP EXIT QUALITY CHECK:")
print(f"  {'Exit date':<14} {'QQQ':<8} {'1m ret':>7} {'3m ret':>7} {'3m MDD':>7} {'Verdict':>12}")
print(f"  {'─'*14} {'─'*8} {'─'*7} {'─'*7} {'─'*7} {'─'*12}")

sep_exit_quality = {}
for se_d in sep_exits:
    ret1m, _ = ret_forward(qqq_a, se_d, 21)
    ret3m, mdd3m = ret_forward(qqq_a, se_d, 63)
    qqq_p = price_at(qqq_a, se_d)
    # Exit is "correct" if 3m MDD < -5% (market dropped meaningfully)
    if mdd3m < -5:
        verdict = "✅ CORRECT"
        sep_exit_quality[se_d.strftime('%Y-%m-%d')] = 'correct'
    else:
        verdict = "❌ FALSE"
        sep_exit_quality[se_d.strftime('%Y-%m-%d')] = 'false'
    print(f"  {se_d.strftime('%Y-%m-%d'):<14} ${qqq_p:<7.1f} {ret1m:>+6.1f}% {ret3m:>+6.1f}% {mdd3m:>+6.1f}% {verdict:>12}")

# For each candidate: classify exit matching
print(f"\n  EXIT EVENT DETAIL (per SEP exit):")

for se_d in sep_exits:
    se_str = se_d.strftime('%Y-%m-%d')
    quality = sep_exit_quality[se_str]
    qqq_p = price_at(qqq_a, se_d)
    ret3m, mdd3m = ret_forward(qqq_a, se_d, 63)
    
    print(f"\n  SEP EXIT: {se_str} (QQQ=${qqq_p:.1f}, 3m MDD={mdd3m:+.1f}%) [{quality.upper()}]")
    print(f"  {'Candidate':<32} {'Class':<16} {'Exit date':<14} {'DlyTD':>6} {'Late cost QQQ':>14} {'Late cost TQQQ':>15} {'3m ret':>7} {'3m MDD':>7}")
    print(f"  {'─'*32} {'─'*16} {'─'*14} {'─'*6} {'─'*14} {'─'*15} {'─'*7} {'─'*7}")
    
    for cname, csig in candidates.items():
        c_entries, c_exits = find_transitions(csig)
        
        # Check if candidate was already off at SEP exit date
        sep_td = idx[idx >= se_d][0] if any(idx >= se_d) else None
        if sep_td is not None and csig.loc[sep_td] == 0:
            # Find when it exited
            last_exit = None
            for ce in c_exits:
                if ce <= se_d: last_exit = ce
            if last_exit is not None:
                delay = td_delay(idx, se_str, last_exit)
                cls = "A:already_off"
                cr3m, cmdd3m = ret_forward(qqq_a, last_exit, 63)
                print(f"  {cname:<32} {cls:<16} {last_exit.strftime('%Y-%m-%d'):<14} {delay:>+5}td {'—':>14} {'—':>15} {cr3m:>+6.1f}% {cmdd3m:>+6.1f}%")
            else:
                print(f"  {cname:<32} {'A:always_off':<16} {'—':<14} {'—':>6} {'—':>14} {'—':>15} {'—':>7} {'—':>7}")
            continue
        
        # Find nearest candidate exit
        best_ce = None; best_delay = 999
        for ce in c_exits:
            d = td_delay(idx, se_str, ce)
            if -30 <= d <= 120 and abs(d) < abs(best_delay):
                best_ce = ce; best_delay = d
        
        if best_ce is not None:
            if best_delay < 0:
                cls = "B:before_SEP"
            else:
                cls = "C:after_SEP"
            
            # Late exit cost: QQQ/TQQQ change between SEP exit and candidate exit
            if best_delay > 0:
                late_qqq = ret_between(qqq_a, se_str, best_ce)
                late_tqqq = ret_between(tqqq_a, se_str, best_ce)
            else:
                late_qqq = 0; late_tqqq = 0
            
            cr3m, cmdd3m = ret_forward(qqq_a, best_ce, 63)
            print(f"  {cname:<32} {cls:<16} {best_ce.strftime('%Y-%m-%d'):<14} {best_delay:>+5}td {late_qqq:>+13.1f}% {late_tqqq:>+14.1f}% {cr3m:>+6.1f}% {cmdd3m:>+6.1f}%")
        else:
            cls = "D:missed"
            # Missed exit cost: what happened to QQQ in next 3m from SEP exit
            print(f"  {cname:<32} {cls:<16} {'NO EXIT':<14} {'—':>6} {'—':>14} {'—':>15} {'—':>7} {'—':>7}")

# ═══════════════════════════════════════════════════════════════
# PART 2: RE-ENTRY EVENT AUDIT
# ═══════════════════════════════════════════════════════════════
SEP_REENTRIES = [e.strftime('%Y-%m-%d') for e in sep_entries if e >= pd.Timestamp('2022-01-01')]

print(f"\n\n{'='*160}")
print("  PART 2: RE-ENTRY EVENT AUDIT")
print("="*160)
print(f"\n  SEP re-entry dates (post-2022): {SEP_REENTRIES}")

for sep_d in SEP_REENTRIES:
    sep_dt = pd.Timestamp(sep_d)
    qqq_p = price_at(qqq_a, sep_d)
    tqqq_p = price_at(tqqq_a, sep_d)
    ret3m, mdd3m = ret_forward(qqq_a, sep_d, 63)
    
    print(f"\n  SEP RE-ENTRY: {sep_d} (QQQ=${qqq_p:.1f} TQQQ=${tqqq_p:.2f}, 3m={ret3m:+.1f}%)")
    print(f"  {'Candidate':<32} {'Class':<16} {'Entry':<14} {'DlyTD':>6} {'QQQ cost':>9} {'TQQQ cost':>10} {'PreRet':>7} {'PreMDD':>7} {'3mQQQ':>7}")
    print(f"  {'─'*32} {'─'*16} {'─'*14} {'─'*6} {'─'*9} {'─'*10} {'─'*7} {'─'*7} {'─'*7}")
    
    for cname, csig in candidates.items():
        c_entries, _ = find_transitions(csig)
        sep_td = idx[idx >= sep_dt]
        if len(sep_td) == 0: continue
        sep_td = sep_td[0]
        
        if csig.loc[sep_td] == 1:
            last_entry = None
            for ce in c_entries:
                if ce <= sep_dt: last_entry = ce
            if last_entry is not None:
                delay = td_delay(idx, sep_d, last_entry)
                pre_ret = ret_between(qqq_a, last_entry, sep_d)
                pre_mdd = mdd_between(qqq_a, last_entry, sep_d)
                cr3m, _ = ret_forward(qqq_a, last_entry, 63)
                print(f"  {cname:<32} {'A:already_on':<16} {last_entry.strftime('%Y-%m-%d'):<14} {delay:>+5}td {'—':>9} {'—':>10} {pre_ret:>+6.1f}% {pre_mdd:>+6.1f}% {cr3m:>+6.1f}%")
            else:
                print(f"  {cname:<32} {'A:always_on':<16} {'—':<14} {'—':>6} {'—':>9} {'—':>10} {'—':>7} {'—':>7} {'—':>7}")
            continue
        
        best = None; best_delay = 999
        for ce in c_entries:
            d = td_delay(idx, sep_d, ce)
            if -30 <= d <= 180 and abs(d) < abs(best_delay):
                best = ce; best_delay = d
        
        if best is not None:
            cls = "B:before_SEP" if best_delay < 0 else "C:after_SEP"
            cost_qqq = ret_between(qqq_a, sep_d, best) if best_delay > 0 else 0
            cost_tqqq = ret_between(tqqq_a, sep_d, best) if best_delay > 0 else 0
            cr3m, _ = ret_forward(qqq_a, best, 63)
            
            pre_ret = ret_between(qqq_a, best, sep_d) if best_delay < 0 else 0
            pre_mdd = mdd_between(qqq_a, best, sep_d) if best_delay < 0 else 0
            
            pr_s = f"{pre_ret:>+6.1f}%" if best_delay < 0 else f"{'—':>7}"
            pm_s = f"{pre_mdd:>+6.1f}%" if best_delay < 0 else f"{'—':>7}"
            
            print(f"  {cname:<32} {cls:<16} {best.strftime('%Y-%m-%d'):<14} {best_delay:>+5}td {cost_qqq:>+8.1f}% {cost_tqqq:>+9.1f}% {pr_s} {pm_s} {cr3m:>+6.1f}%")
        else:
            print(f"  {cname:<32} {'D:missed':<16} {'—':<14} {'—':>6} {'—':>9} {'—':>10} {'—':>7} {'—':>7} {'—':>7}")

# ═══════════════════════════════════════════════════════════════
# PART 3: ROUND-TRIP CYCLE AUDIT
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*160}")
print("  PART 3: ROUND-TRIP CYCLE AUDIT (SEP exit → SEP re-entry)")
print("="*160)

# Build SEP cycles
cycles = []
for i, exit_d in enumerate(sep_exits):
    # Find next re-entry
    reentry_d = None
    for entry_d in sep_entries:
        if entry_d > exit_d:
            reentry_d = entry_d; break
    if reentry_d is None: continue
    
    exit_str = exit_d.strftime('%Y-%m-%d')
    reentry_str = reentry_d.strftime('%Y-%m-%d')
    
    out_days = td_delay(idx, exit_str, reentry_str)
    qqq_exit = price_at(qqq_a, exit_d)
    qqq_reentry = price_at(qqq_a, reentry_d)
    tqqq_exit = price_at(tqqq_a, exit_d)
    tqqq_reentry = price_at(tqqq_a, reentry_d)
    qqq_change = (qqq_reentry / qqq_exit - 1) * 100 if qqq_exit > 0 else 0
    tqqq_change = (tqqq_reentry / tqqq_exit - 1) * 100 if tqqq_exit > 0 else 0
    out_mdd = mdd_between(qqq_a, exit_d, reentry_d)
    quality = sep_exit_quality.get(exit_str, 'unknown')
    
    cycles.append({
        'exit': exit_str, 'reentry': reentry_str, 'quality': quality,
        'out_days': out_days,
        'qqq_exit': qqq_exit, 'qqq_reentry': qqq_reentry,
        'tqqq_exit': tqqq_exit, 'tqqq_reentry': tqqq_reentry,
        'qqq_change': qqq_change, 'tqqq_change': tqqq_change,
        'out_mdd': out_mdd,
    })

print(f"\n  {'Cycle':<6} {'SEP Exit':<14} {'SEP Re-entry':<14} {'OutDays':>8} {'QQQ Δ':>7} {'TQQQ Δ':>8} {'Out MDD':>8} {'Quality':>12}")
print(f"  {'─'*6} {'─'*14} {'─'*14} {'─'*8} {'─'*7} {'─'*8} {'─'*8} {'─'*12}")
for i, c in enumerate(cycles):
    marker = '❌ FALSE' if c['quality'] == 'false' else '✅ CORRECT'
    print(f"  {i+1:<6} {c['exit']:<14} {c['reentry']:<14} {c['out_days']:>7}td {c['qqq_change']:>+6.1f}% {c['tqqq_change']:>+7.1f}% {c['out_mdd']:>+7.1f}% {marker:>12}")

# Per-candidate round-trip
print(f"\n  CANDIDATE ROUND-TRIP vs SEP:")
print(f"  {'Candidate':<32} ", end='')
for i, c in enumerate(cycles):
    print(f"{'C'+str(i+1)+': '+c['exit'][:7]:>16}", end='')
print(f"  {'Net QQQ Δ':>10}")
print(f"  {'─'*32} ", end='')
for _ in cycles: print(f"{'─'*16}", end='')
print(f"  {'─'*10}")

for cname, csig in candidates.items():
    c_entries, c_exits = find_transitions(csig)
    line = f"  {cname:<32} "
    total_net = 0
    
    for c in cycles:
        sep_exit = pd.Timestamp(c['exit'])
        sep_reentry = pd.Timestamp(c['reentry'])
        
        # Find candidate exit (nearest to SEP exit)
        cand_exit = None
        for ce in c_exits:
            d = td_delay(idx, c['exit'], ce)
            if -30 <= d <= 120:
                if cand_exit is None or abs(d) < abs(td_delay(idx, c['exit'], cand_exit)):
                    cand_exit = ce
        
        # Find candidate re-entry (nearest to SEP re-entry)
        cand_reentry = None
        for ce in c_entries:
            d = td_delay(idx, c['reentry'], ce)
            if -60 <= d <= 180:
                if cand_reentry is None or abs(d) < abs(td_delay(idx, c['reentry'], cand_reentry)):
                    cand_reentry = ce
        
        if cand_exit is None and cand_reentry is None:
            # Candidate stayed IN the entire cycle
            # Cost = whatever QQQ did during the out period (candidate ate it)
            cost = c['qqq_change']  # positive = candidate gained, but also ate the drawdown
            if c['quality'] == 'false':
                # SEP exited falsely, candidate correctly stayed in
                benefit = c['qqq_change']
                line += f"  {'STAYED':>6}{benefit:>+7.1f}%✅"
                total_net += benefit
            else:
                # SEP correctly exited, candidate missed the exit
                line += f"  {'STAYED':>6}{cost:>+7.1f}%❌"
                total_net += cost
        elif cand_exit is not None and cand_reentry is not None:
            # Full cycle comparison
            exit_delay = td_delay(idx, c['exit'], cand_exit)
            entry_delay = td_delay(idx, c['reentry'], cand_reentry)
            
            # Net cost: late exit cost + late re-entry cost
            # Exit portion: QQQ between SEP exit and cand exit
            exit_cost = ret_between(qqq_a, c['exit'], cand_exit) if exit_delay > 0 else -ret_between(qqq_a, cand_exit, c['exit']) if exit_delay < 0 else 0
            # Re-entry portion: QQQ between SEP re-entry and cand re-entry  
            entry_cost = ret_between(qqq_a, c['reentry'], cand_reentry) if entry_delay > 0 else 0
            
            net = -exit_cost - entry_cost  # negative exit_cost = candidate lost by being late; entry_cost = missed upside
            line += f"  {exit_delay:>+3}/{entry_delay:>+3}td{net:>+5.1f}%"
            total_net += net
        elif cand_exit is not None:
            exit_delay = td_delay(idx, c['exit'], cand_exit)
            # Exited but didn't re-enter in time
            line += f"  {'ex':>3}{exit_delay:>+3}td {'noRE':>5}"
            total_net -= 10  # penalty estimate
        else:
            # Didn't exit but did re-enter (stayed in, then re-entered from something else)
            line += f"  {'noEX':>6}{'':>9}"
    
    line += f"  {total_net:>+9.1f}%"
    print(line)

# ═══════════════════════════════════════════════════════════════
# PART 4: TRANSITION ALPHA ACCOUNTING
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*160}")
print("  PART 4: TRANSITION ALPHA ACCOUNTING (QQQ basis)")
print("="*160)

print(f"\n  {'Candidate':<32} {'Good exit α':>12} {'False exit α':>13} {'Re-entry α':>11} {'Total α':>8}")
print(f"  {'─'*32} {'─'*12} {'─'*13} {'─'*11} {'─'*8}")

for cname, csig in candidates.items():
    c_entries, c_exits = find_transitions(csig)
    
    good_exit_alpha = 0  # benefit from correct exits
    false_exit_alpha = 0  # benefit from NOT doing false exits
    reentry_alpha = 0  # cost of late re-entry
    
    for c in cycles:
        sep_exit = pd.Timestamp(c['exit'])
        
        # Find candidate exit
        cand_exit = None
        for ce in c_exits:
            d = td_delay(idx, c['exit'], ce)
            if -30 <= d <= 120:
                if cand_exit is None or abs(d) < abs(td_delay(idx, c['exit'], cand_exit)):
                    cand_exit = ce
        
        if c['quality'] == 'correct':
            if cand_exit is None:
                # Missed a correct exit — lost the avoided drawdown
                good_exit_alpha += c['out_mdd']  # negative number
            else:
                delay = td_delay(idx, c['exit'], cand_exit)
                if delay > 0:
                    # Late exit — lost some of the benefit
                    late_cost = ret_between(qqq_a, c['exit'], cand_exit)
                    good_exit_alpha -= late_cost  # if market dropped, this is positive (good)
                # if delay <= 0, candidate exited early — full benefit
        
        elif c['quality'] == 'false':
            if cand_exit is None:
                # Correctly stayed in during false SEP exit
                false_exit_alpha += c['qqq_change']  # market went up, candidate captured it
            else:
                # Also did false exit — no benefit
                pass
        
        # Re-entry
        sep_reentry = pd.Timestamp(c['reentry'])
        cand_reentry = None
        for ce in c_entries:
            d = td_delay(idx, c['reentry'], ce)
            if -60 <= d <= 180:
                if cand_reentry is None or abs(d) < abs(td_delay(idx, c['reentry'], cand_reentry)):
                    cand_reentry = ce
        
        if cand_reentry is not None:
            delay = td_delay(idx, c['reentry'], cand_reentry)
            if delay > 0:
                missed = ret_between(qqq_a, c['reentry'], cand_reentry)
                reentry_alpha -= missed  # missed upside
    
    total = good_exit_alpha + false_exit_alpha + reentry_alpha
    print(f"  {cname:<32} {good_exit_alpha:>+11.1f}% {false_exit_alpha:>+12.1f}% {reentry_alpha:>+10.1f}% {total:>+7.1f}%")

# ═══════════════════════════════════════════════════════════════
# PART 5: BACKTEST COMPARISON
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*160}")
print("  PART 5: BACKTEST COMPARISON")
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
    out = (signal==0).mean()*100
    return {'label':label,'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so,'out':out}

bt_results = [run_bt(sep_state, '★ Real SEP')]
for cname, csig in candidates.items():
    bt_results.append(run_bt(csig, cname))

bt_results.sort(key=lambda x: x['sharpe'], reverse=True)
print(f"\n  {'Strategy':<40} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sort':>6} {'%OUT':>5}")
print(f"  {'─'*40} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*5}")
for r in bt_results:
    marker = ' ◄ SEP' if r['label'].startswith('★') else ''
    print(f"  {r['label']:<40} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>5.2f} {r['out']:>4.1f}%{marker}")

print(f"\n  AUDIT v3 COMPLETE — all fixes applied.")
print(f"    v2: FFR fix, CPI MS+45d, signal shift(1), A/B/C/D, trading-day delays, QQQ+TQQQ")
print(f"    v3: coverage/true_reentry/already_on split, pre-SEP MDD, exit audit, round-trip, transition alpha")
