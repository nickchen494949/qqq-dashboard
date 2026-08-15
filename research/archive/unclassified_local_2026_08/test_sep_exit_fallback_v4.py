#!/usr/bin/env python3
"""
EXIT FALLBACK AUDIT v4.
Now we know: re-entry is solved (Real5Y). The gap is EXIT.

Can public signals replicate SEP's exit timing?
  2021-09-22 (all candidates 41td late)
  2023-06-14 (all candidates missed)
  2024-06-12 (all candidates missed/already_off)
  2024-12-18 (all candidates +4td late, OK)

Test 8 exit rules (X1-X8) paired with Real5Y re-entry.
All v2/v3 fixes: MS+45d CPI, shift(1), trading-day delays.
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

# ═══════════════════════════════════════════════════
# LOAD
# ═══════════════════════════════════════════════════
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
core_cpi_1m = ((cpilfe_m / cpilfe_m.shift(1)).pow(12) - 1) * 100
core_cpi_3m_lagged = core_cpi_3m.copy()
core_cpi_3m_lagged.index += pd.Timedelta(days=45)
core_cpi_3m_d = core_cpi_3m_lagged.reindex(idx, method='ffill').ffill()
core_cpi_1m_lagged = core_cpi_1m.copy()
core_cpi_1m_lagged.index += pd.Timedelta(days=45)
core_cpi_1m_d = core_cpi_1m_lagged.reindex(idx, method='ffill').ffill()

# CPI acceleration: is 3m CPI rising? (current vs 3m ago)
core_cpi_3m_mom = core_cpi_3m.diff(3)
core_cpi_3m_mom_lagged = core_cpi_3m_mom.copy()
core_cpi_3m_mom_lagged.index += pd.Timedelta(days=45)
core_cpi_accel_d = core_cpi_3m_mom_lagged.reindex(idx, method='ffill').ffill()

# Policy path
policy_1y = dgs1_a - ffr_a

# ALL signals shifted 1 trading day
dgs2_chg_3m = (dgs2_a - dgs2_a.shift(63)).shift(1)
dgs2_chg_1m = (dgs2_a - dgs2_a.shift(21)).shift(1)
real5y_chg_3m = (dfii5_a - dfii5_a.shift(63)).shift(1)
real5y_chg_1m = (dfii5_a - dfii5_a.shift(21)).shift(1)
policy_1y_chg_3m = (policy_1y - policy_1y.shift(63)).shift(1)
policy_1y_chg_1m = (policy_1y - policy_1y.shift(21)).shift(1)
baa_chg_3m = (baa10y_a - baa10y_a.shift(63)).shift(1)
core_cpi_3m_d = core_cpi_3m_d.shift(1)
core_cpi_1m_d = core_cpi_1m_d.shift(1)
core_cpi_accel_d = core_cpi_accel_d.shift(1)
t5yifr_shifted = t5yifr_a.shift(1)

# QQQ trend signals (shifted)
qqq_sma100 = qqq_a.rolling(100).mean().shift(1)
qqq_ret_20d = qqq_a.pct_change(20).shift(1) * 100
qqq_high = qqq_a.expanding().max().shift(1)
qqq_dd_from_high = ((qqq_a.shift(1) / qqq_high) - 1) * 100

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
fomc_shock_last_raw = pd.Series(0.0, index=idx)
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
    fomc_shock_last_raw.loc[mask] = shock
    fomc_shock_cum3_raw.loc[mask] = sum(recent_shocks)
fomc_shock_cum3 = fomc_shock_cum3_raw.shift(1)
fomc_shock_last = fomc_shock_last_raw.shift(1)

# SEP
sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

print(f"  Data ready. {len(idx)} days.\n")

# ═══════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════
def td_delay(idx, d1, d2):
    return int(idx.searchsorted(pd.Timestamp(d2)) - idx.searchsorted(pd.Timestamp(d1)))

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

def ret_forward(series, dt, days=63):
    near = series.index[series.index >= pd.Timestamp(dt)]
    if len(near) == 0: return 0.0, 0.0
    start = near[0]; fut = series.loc[series.index > start].head(days)
    if len(fut) < 5: return 0.0, 0.0
    ret = (float(fut.iloc[-1]) / float(series.loc[start]) - 1) * 100
    mdd = float(((fut / fut.cummax()) - 1).min() * 100)
    return ret, mdd

def gv(series, d, default=0.0):
    try:
        val = series.loc[d]
        return float(val) if not np.isnan(val) else default
    except: return default

# ═══════════════════════════════════════════════════
# INDICATOR SNAPSHOT at each SEP exit
# ═══════════════════════════════════════════════════
sep_entries, sep_exits = find_transitions(sep_state)
SEP_EXIT_DATES = [e.strftime('%Y-%m-%d') for e in sep_exits]

print("="*160)
print("  INDICATOR SNAPSHOT AT EACH SEP EXIT (shifted T-1 values = what signal sees)")
print("="*160)

print(f"\n  {'Date':<14} {'2Y1mΔ':>7} {'2Y3mΔ':>7} {'R5Y3mΔ':>8} {'Pol1YΔ':>7} {'CPI3m':>6} {'CPI1m':>6} {'CPIacc':>7} {'5Y5Y':>5} {'FOMCshk':>8} {'FOMCcm3':>8} {'QQQ20d':>8} {'QQQdd':>7}")
print(f"  {'─'*14} {'─'*7} {'─'*7} {'─'*8} {'─'*7} {'─'*6} {'─'*6} {'─'*7} {'─'*5} {'─'*8} {'─'*8} {'─'*8} {'─'*7}")

for se_d in sep_exits:
    nd = idx[idx >= se_d][0] if any(idx >= se_d) else None
    if nd is None: continue
    print(f"  {se_d.strftime('%Y-%m-%d'):<14} {gv(dgs2_chg_1m,nd):>+6.2f} {gv(dgs2_chg_3m,nd):>+6.2f} {gv(real5y_chg_3m,nd):>+7.2f} {gv(policy_1y_chg_3m,nd):>+6.2f} {gv(core_cpi_3m_d,nd):>5.1f} {gv(core_cpi_1m_d,nd):>5.1f} {gv(core_cpi_accel_d,nd):>+6.2f} {gv(t5yifr_shifted,nd):>4.2f} {gv(fomc_shock_last,nd):>+7.2f} {gv(fomc_shock_cum3,nd):>+7.2f} {gv(qqq_ret_20d,nd):>+7.1f} {gv(qqq_dd_from_high,nd):>+6.1f}")

# ═══════════════════════════════════════════════════
# BUILD EXIT RULES
# ═══════════════════════════════════════════════════
print(f"\n\n{'='*160}")
print("  EXIT RULE GRID — testing X1–X8 variants")
print("="*160)

# Fixed re-entry: Real5Y Δ<-0.3, CPI<3.5 (proven best from v3)
def best_reentry(d, i):
    return gv(real5y_chg_3m, d) < -0.3 and gv(core_cpi_3m_d, d) < 3.5

def build_signal(idx, exit_fn, min_hold=42):
    state = 1; hold = 0; states = []
    for i, d in enumerate(idx):
        if state == 1:
            if exit_fn(d, i): state = 0; hold = 0
        else:
            hold += 1
            if hold >= min_hold and best_reentry(d, i): state = 1
        states.append(state)
    return pd.Series(states, index=idx)

# Exit rule definitions
exit_rules = {}

# Original F exit (baseline)
exit_rules['F_base: 2Y3m>0.3 & CPI>3.0 & 5Y5Y>2.3'] = lambda d,i: (
    gv(dgs2_chg_3m, d) > 0.3 and gv(core_cpi_3m_d, d) > 3.0 and gv(t5yifr_shifted, d) > 2.3)

# X1: 2Y 1m shock (fast)
for th in [0.15, 0.20, 0.25, 0.30]:
    for cpi_th in [2.5, 3.0]:
        exit_rules[f'X1: 2Y1m>{th} & CPI>{cpi_th}'] = (
            lambda d,i,t=th,c=cpi_th: gv(dgs2_chg_1m, d) > t and gv(core_cpi_3m_d, d) > c)

# X2: 2Y 3m (orig F rate leg, but looser CPI)
for th in [0.25, 0.30]:
    for cpi_th in [2.0, 2.5, 3.0]:
        exit_rules[f'X2: 2Y3m>{th} & CPI>{cpi_th}'] = (
            lambda d,i,t=th,c=cpi_th: gv(dgs2_chg_3m, d) > t and gv(core_cpi_3m_d, d) > c)

# X3: Real yield rising (most relevant for QQQ)
for th in [0.20, 0.30, 0.40]:
    for cpi_th in [2.0, 2.5, 3.0]:
        exit_rules[f'X3: R5Y3m>{th} & CPI>{cpi_th}'] = (
            lambda d,i,t=th,c=cpi_th: gv(real5y_chg_3m, d) > t and gv(core_cpi_3m_d, d) > c)

# X4: Policy repricing hawkish
for th in [0.05, 0.10, 0.15]:
    for cpi_th in [2.5, 3.0]:
        exit_rules[f'X4: Pol1Y>{th} & CPI>{cpi_th}'] = (
            lambda d,i,t=th,c=cpi_th: gv(policy_1y_chg_3m, d) > t and gv(core_cpi_3m_d, d) > c)

# X5: FOMC hawkish shock
for th in [0.05, 0.10, 0.15]:
    for cpi_th in [2.5, 3.0]:
        exit_rules[f'X5: FOMCcum3>{th} & CPI>{cpi_th}'] = (
            lambda d,i,t=th,c=cpi_th: gv(fomc_shock_cum3, d) > t and gv(core_cpi_3m_d, d) > c)

# X6: CPI alone (inflation pressure without rate confirmation)
exit_rules['X6: CPI1m>4 OR CPI3m>3'] = lambda d,i: gv(core_cpi_1m_d, d) > 4.0 or gv(core_cpi_3m_d, d) > 3.0
exit_rules['X6: CPI3m>2.5 & CPIacc>0'] = lambda d,i: gv(core_cpi_3m_d, d) > 2.5 and gv(core_cpi_accel_d, d) > 0
exit_rules['X6: CPI3m>3 & CPIacc>0'] = lambda d,i: gv(core_cpi_3m_d, d) > 3.0 and gv(core_cpi_accel_d, d) > 0

# X7: OR logic (rate shock OR real yield shock, with CPI guard)
for cpi_th in [2.0, 2.5, 3.0]:
    exit_rules[f'X7: (2Y1m>0.20 OR R5Y3m>0.30) & CPI>{cpi_th}'] = (
        lambda d,i,c=cpi_th: (gv(dgs2_chg_1m, d) > 0.20 or gv(real5y_chg_3m, d) > 0.30) and gv(core_cpi_3m_d, d) > c)
    exit_rules[f'X7: (2Y3m>0.25 OR R5Y3m>0.25) & CPI>{cpi_th}'] = (
        lambda d,i,c=cpi_th: (gv(dgs2_chg_3m, d) > 0.25 or gv(real5y_chg_3m, d) > 0.25) and gv(core_cpi_3m_d, d) > c)

# X7b: Triple OR (rate OR real OR FOMC, with low CPI guard)
for cpi_th in [2.0, 2.5]:
    exit_rules[f'X7b: (2Y1m>0.20 OR R5Y>0.30 OR FOMC>0.10) & CPI>{cpi_th}'] = (
        lambda d,i,c=cpi_th: (gv(dgs2_chg_1m, d) > 0.20 or gv(real5y_chg_3m, d) > 0.30 or gv(fomc_shock_cum3, d) > 0.10) and gv(core_cpi_3m_d, d) > c)

# X8: Macro exit OR QQQ trend break
for cpi_th in [2.5, 3.0]:
    exit_rules[f'X8: (2Y3m>0.3 & CPI>{cpi_th}) OR QQQ20d<-8%'] = (
        lambda d,i,c=cpi_th: (gv(dgs2_chg_3m, d) > 0.3 and gv(core_cpi_3m_d, d) > c) or gv(qqq_ret_20d, d) < -8)
    exit_rules[f'X8: (R5Y3m>0.3 & CPI>{cpi_th}) OR QQQdd<-10%'] = (
        lambda d,i,c=cpi_th: (gv(real5y_chg_3m, d) > 0.3 and gv(core_cpi_3m_d, d) > c) or gv(qqq_dd_from_high, d) < -10)

print(f"  {len(exit_rules)} exit rules to test.\n")

# ═══════════════════════════════════════════════════
# BUILD SIGNALS & SCORE EXIT MATCHING
# ═══════════════════════════════════════════════════

results = []
for rname, efn in exit_rules.items():
    sig = build_signal(idx, efn, 42)
    c_entries, c_exits = find_transitions(sig)
    
    exit_hits = 0; exit_delays = []; false_exits = 0
    total_late_cost_qqq = 0
    exit_detail = []
    
    for se_d in sep_exits:
        se_str = se_d.strftime('%Y-%m-%d')
        se_near = idx[idx >= se_d][0] if any(idx >= se_d) else None
        if se_near is None: continue
        
        # Check 3m MDD to validate SEP exit quality
        ret3m, mdd3m = ret_forward(qqq_a, se_d, 63)
        is_correct = mdd3m < -5
        
        # Find nearest candidate exit
        best_ce = None; best_delay = 999
        for ce in c_exits:
            d = td_delay(idx, se_str, ce)
            if -30 <= d <= 120 and abs(d) < abs(best_delay):
                best_ce = ce; best_delay = d
        
        # Check if already off
        if sig.loc[se_near] == 0 and best_ce is None:
            last_exit = None
            for ce in c_exits:
                if ce <= se_d: last_exit = ce
            if last_exit is not None:
                best_ce = last_exit
                best_delay = td_delay(idx, se_str, last_exit)
        
        if best_ce is not None and -60 <= best_delay <= 60:
            exit_hits += 1
            exit_delays.append(best_delay)
            if best_delay > 0:
                late_qqq = (price_at(qqq_a, best_ce) / price_at(qqq_a, se_d) - 1) * 100
                total_late_cost_qqq += late_qqq
            exit_detail.append((se_str, best_ce.strftime('%Y-%m-%d'), best_delay, is_correct))
        else:
            exit_detail.append((se_str, 'MISSED', 999, is_correct))
    
    # False exits: candidate exits not near any SEP exit
    for ce in c_exits:
        near_any = False
        for se_d in sep_exits:
            if abs(td_delay(idx, se_d.strftime('%Y-%m-%d'), ce)) < 60:
                near_any = True; break
        if not near_any:
            # Check if false exit (market went up after)
            ret1m, _ = ret_forward(qqq_a, ce, 21)
            if ret1m > 3: false_exits += 1
    
    out_pct = (sig == 0).mean() * 100
    avg_delay = np.mean(exit_delays) if exit_delays else 999
    
    # Backtest
    eq = None
    r = se.run_backtest(
        idx, dr_qqq, None, None, effr_a,
        z_credit, vol_z, sig,
        inf_z=inf_z, nl_z=nl_z,
        use_sep=True, use_overlay=True,
    )
    eq = r['equity']; ny = len(eq)/252
    cagr = (eq.iloc[-1]**(1/ny)-1)*100
    mdd = ((eq/eq.expanding().max())-1).min()*100
    dret = eq.pct_change().dropna()
    sh = dret.mean()/dret.std()*np.sqrt(252) if dret.std()>0 else 0
    
    results.append({
        'name': rname, 'exit_hits': exit_hits, 'avg_delay': avg_delay,
        'late_cost': total_late_cost_qqq, 'false_exits': false_exits,
        'out_pct': out_pct, 'cagr': cagr, 'mdd': mdd, 'sharpe': sh,
        'exit_detail': exit_detail, 'total_exits': len(c_exits),
    })

# Sort: exit_hits desc, then sharpe desc
results.sort(key=lambda x: (-x['exit_hits'], -x['sharpe']))

# ═══════════════════════════════════════════════════
# RESULTS TABLE
# ═══════════════════════════════════════════════════
print(f"\n  TOP EXIT RULES (sorted by exit hits, then Sharpe):")
print(f"  {'Rank':<4} {'Exit Rule':<48} {'ExHit':>6} {'AvgDly':>7} {'Late$':>7} {'FalseX':>7} {'Sharpe':>7} {'CAGR':>7} {'%OUT':>5}")
print(f"  {'─'*4} {'─'*48} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*5}")

for i, r in enumerate(results[:40]):
    marker = ''
    if r['exit_hits'] >= 4 and r['false_exits'] <= 2 and r['sharpe'] > 1.45:
        marker = ' ✅'
    elif r['exit_hits'] >= 4 and r['sharpe'] > 1.40:
        marker = ' ⚠️'
    print(f"  {i+1:<4} {r['name']:<48} {r['exit_hits']:>4}/{len(sep_exits)} {r['avg_delay']:>5.0f}td {r['late_cost']:>+6.1f}% {r['false_exits']:>6} {r['sharpe']:>7.2f} {r['cagr']:>+6.1f}% {r['out_pct']:>4.1f}%{marker}")

# ═══════════════════════════════════════════════════
# DETAILED EXIT EVENT TABLE for best exit rules
# ═══════════════════════════════════════════════════
print(f"\n{'='*160}")
print("  DETAILED EXIT EVENTS — best exit rules vs SEP")
print("="*160)

# Pick top unique strategies
seen = set()
top = []
for r in results:
    key = (r['exit_hits'], round(r['sharpe'], 1))
    if key not in seen and len(top) < 8:
        top.append(r)
        seen.add(key)

# Add SEP baseline
print(f"\n  {'Rule':<48}", end='')
for se_d in sep_exits:
    print(f"  {se_d.strftime('%Y-%m-%d'):>14}", end='')
print(f"  {'Sharpe':>7}")
print(f"  {'─'*48}", end='')
for _ in sep_exits: print(f"  {'─'*14}", end='')
print(f"  {'─'*7}")

print(f"  {'★ Real SEP':<48}", end='')
for se_d in sep_exits:
    print(f"  {'ON TIME':>14}", end='')
_, sep_bt = find_transitions(sep_state)
r_sep = se.run_backtest(idx, dr_qqq, None, None, effr_a, z_credit, vol_z, sep_state,
    inf_z=inf_z, nl_z=nl_z, use_sep=True, use_overlay=True)
eq_s = r_sep['equity']; ny = len(eq_s)/252
sh_s = eq_s.pct_change().dropna(); sh_s = sh_s.mean()/sh_s.std()*np.sqrt(252)
print(f"  {sh_s:>7.2f}")

for r in top:
    print(f"  {r['name']:<48}", end='')
    for ed in r['exit_detail']:
        if ed[1] == 'MISSED':
            print(f"  {'MISSED':>14}", end='')
        else:
            delay = ed[2]
            print(f"  {delay:>+5}td {'✅' if abs(delay)<=20 else '⚠️':>7}", end='')
    print(f"  {r['sharpe']:>7.2f}")

# ═══════════════════════════════════════════════════
# COMBINED: best exit + Real5Y reentry vs SEP
# ═══════════════════════════════════════════════════
print(f"\n{'='*160}")
print("  FINAL: best exit rules + Real5Y re-entry vs SEP")
print("="*160)

print(f"\n  All use re-entry: Real5Y Δ<-0.3, CPI<3.5")
print(f"\n  {'Strategy':<48} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'%OUT':>5} {'ExHit':>6} {'FalseX':>7}")
print(f"  {'─'*48} {'─'*7} {'─'*7} {'─'*7} {'─'*5} {'─'*6} {'─'*7}")

# SEP
cagr_sep = (eq_s.iloc[-1]**(1/(len(eq_s)/252))-1)*100
mdd_sep = ((eq_s/eq_s.expanding().max())-1).min()*100
out_sep = (sep_state==0).mean()*100
print(f"  {'★ Real SEP':<48} {cagr_sep:>+6.1f}% {mdd_sep:>6.1f}% {sh_s:>7.2f} {out_sep:>4.1f}% {'4/4':>6} {'0':>7}")

for r in sorted(top[:8], key=lambda x: x['sharpe'], reverse=True):
    print(f"  {r['name']:<48} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['out_pct']:>4.1f}% {r['exit_hits']:>4}/{len(sep_exits)} {r['false_exits']:>6}")

print(f"\n  AUDIT v4 COMPLETE.")
print(f"    Fixed re-entry: Real5Y Δ<-0.3, CPI<3.5 (proven best from v3)")
print(f"    Testing: 8 exit rule families × multiple thresholds")
print(f"    All signals shifted 1 trading day, CPI MS+45d")
