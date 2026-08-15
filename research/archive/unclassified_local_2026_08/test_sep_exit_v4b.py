#!/usr/bin/env python3
"""
EXIT THRESHOLD v4b — tiny focused test.
Only 3 variants of F_base exit, all with Real5Y re-entry.

V1: 5Y5Y >= 2.25 (from 2.30)
V2: 5Y5Y >= 2.25 OR Real5Y 3m > 0.30 (soft confirm)
V3: No 5Y5Y gate at all (just 2Y3m + CPI)

Question: does 2023-06 get caught? Does it create false exits?
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

print("Loading data...")
qqq = gy('QQQ'); tqqq = gy('TQQQ')
hyg = gy('HYG'); ief = gy('IEF'); tip = gy('TIP'); tlt = gy('TLT')
effr_raw = gf('EFFR'); dgs2 = gf('DGS2')
t5yifr = gf('T5YIFR'); dfii5 = gf('DFII5')
baa10y = gf('BAA10Y'); walcl = gf('WALCL')
rrp = gf('RRPONTSYD'); tga = gf('WTREGEN')

idx = qqq.dropna().index; idx = idx[idx >= '2012-01-01']
qqq_a = qqq.reindex(idx); tqqq_a = tqqq.reindex(idx).ffill()
hyg_a = hyg.reindex(idx).ffill(); ief_a = ief.reindex(idx).ffill()
tip_a = tip.reindex(idx).ffill(); tlt_a = tlt.reindex(idx).ffill()
dgs2_a = dgs2.reindex(idx, method='ffill').ffill()
t5yifr_a = t5yifr.reindex(idx, method='ffill').ffill()
dfii5_a = dfii5.reindex(idx, method='ffill').ffill()
effr_a = effr_raw.reindex(idx, method='ffill').ffill() / 36500
walcl_a = walcl.resample('D').ffill().reindex(idx, method='ffill').ffill()
rrp_a = rrp.resample('D').ffill().reindex(idx, method='ffill').ffill()
tga_a = tga.resample('D').ffill().reindex(idx, method='ffill').ffill()

# CPI: MS + 45d
cpilfe = gf('CPILFESL')
cpilfe_m = cpilfe.resample('MS').last().dropna()
core_cpi_3m = ((cpilfe_m / cpilfe_m.shift(3)).pow(4) - 1) * 100
core_cpi_3m_lagged = core_cpi_3m.copy()
core_cpi_3m_lagged.index += pd.Timedelta(days=45)
core_cpi_3m_d = core_cpi_3m_lagged.reindex(idx, method='ffill').ffill()

# Shift all signals by 1 day
dgs2_chg_3m = (dgs2_a - dgs2_a.shift(63)).shift(1)
real5y_chg_3m = (dfii5_a - dfii5_a.shift(63)).shift(1)
t5yifr_s = t5yifr_a.shift(1)
core_cpi_3m_d = core_cpi_3m_d.shift(1)

dr_qqq = qqq_a.pct_change()
z_credit = se.compute_credit_z(hyg_a, ief_a)
vol_z = se.compute_vol_z(dr_qqq)
inf_z = se.compute_inflation_z(tip_a, tlt_a)
nl_z = se.compute_nl_z(walcl_a, rrp_a, tga_a)

# SEP
sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

print(f"  Data ready. {len(idx)} days.\n")

def gv(s, d, default=0.0):
    try:
        v = s.loc[d]; return float(v) if not np.isnan(v) else default
    except: return default

def td_delay(idx, d1, d2):
    return int(idx.searchsorted(pd.Timestamp(d2)) - idx.searchsorted(pd.Timestamp(d1)))

def find_transitions(signal):
    entries, exits = [], []
    arr = signal.values
    for i in range(1, len(arr)):
        if arr[i] == 1 and arr[i-1] == 0: entries.append(signal.index[i])
        if arr[i] == 0 and arr[i-1] == 1: exits.append(signal.index[i])
    return entries, exits

def ret_forward(series, dt, days=63):
    near = series.index[series.index >= pd.Timestamp(dt)]
    if len(near) == 0: return 0.0, 0.0
    start = near[0]; fut = series.loc[series.index > start].head(days)
    if len(fut) < 5: return 0.0, 0.0
    ret = (float(fut.iloc[-1]) / float(series.loc[start]) - 1) * 100
    mdd = float(((fut / fut.cummax()) - 1).min() * 100)
    return ret, mdd

def price_at(series, dt):
    near = series.index[series.index >= pd.Timestamp(dt)]
    return float(series.loc[near[0]]) if len(near) > 0 else np.nan

# Fixed re-entry: Real5Y
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

# ═══════════════════════════════════════════════════
# 5Y5Y VALUE AT 2023-06-14
# ═══════════════════════════════════════════════════
print("="*120)
print("  5Y5Y BREAKEVEN AROUND SEP EXIT DATES")
print("="*120)

sep_entries, sep_exits = find_transitions(sep_state)
for se_d in sep_exits:
    nd = idx[idx >= se_d][0]
    raw = float(t5yifr_a.loc[nd]) if nd in t5yifr_a.index else 0
    shifted = gv(t5yifr_s, nd)
    print(f"  {se_d.strftime('%Y-%m-%d')}: 5Y5Y raw={raw:.3f}  shifted(T-1)={shifted:.3f}  2Y3mΔ={gv(dgs2_chg_3m,nd):+.3f}  CPI3m={gv(core_cpi_3m_d,nd):.2f}  R5Y3mΔ={gv(real5y_chg_3m,nd):+.3f}")

# ═══════════════════════════════════════════════════
# EXIT VARIANTS
# ═══════════════════════════════════════════════════
print(f"\n{'='*120}")
print("  EXIT THRESHOLD VARIANTS")
print("="*120)

variants = {}

# Original F_base
variants['F_base (5Y5Y>2.30)'] = lambda d,i: (
    gv(dgs2_chg_3m, d) > 0.30 and gv(core_cpi_3m_d, d) > 3.0 and gv(t5yifr_s, d) > 2.30)

# V1: lower threshold
for th in [2.20, 2.25, 2.15, 2.10]:
    variants[f'V1: 5Y5Y>{th}'] = (
        lambda d,i,t=th: gv(dgs2_chg_3m, d) > 0.30 and gv(core_cpi_3m_d, d) > 3.0 and gv(t5yifr_s, d) > t)

# V2: soft confirm (5Y5Y OR Real5Y rising)
for th in [2.20, 2.25]:
    for rth in [0.25, 0.30, 0.35]:
        variants[f'V2: 5Y5Y>{th} OR R5Y>{rth}'] = (
            lambda d,i,t=th,r=rth: gv(dgs2_chg_3m, d) > 0.30 and gv(core_cpi_3m_d, d) > 3.0 and (gv(t5yifr_s, d) > t or gv(real5y_chg_3m, d) > r))

# V3: no 5Y5Y gate
variants['V3: no 5Y5Y (2Y3m+CPI only)'] = lambda d,i: (
    gv(dgs2_chg_3m, d) > 0.30 and gv(core_cpi_3m_d, d) > 3.0)

# V3b: lower CPI threshold, no 5Y5Y
variants['V3b: 2Y3m>0.30 & CPI>2.5'] = lambda d,i: (
    gv(dgs2_chg_3m, d) > 0.30 and gv(core_cpi_3m_d, d) > 2.5)

# V3c: lower 2Y threshold, no 5Y5Y
variants['V3c: 2Y3m>0.25 & CPI>3.0'] = lambda d,i: (
    gv(dgs2_chg_3m, d) > 0.25 and gv(core_cpi_3m_d, d) > 3.0)

print(f"  {len(variants)} variants to test.\n")

results = []
for vname, efn in variants.items():
    sig = build_signal(idx, efn, 42)
    c_entries, c_exits = find_transitions(sig)
    
    exit_detail = []
    false_exits = 0
    
    for se_d in sep_exits:
        se_str = se_d.strftime('%Y-%m-%d')
        se_near = idx[idx >= se_d][0] if any(idx >= se_d) else None
        if se_near is None: continue
        
        # Find match
        best_ce = None; best_delay = 999
        for ce in c_exits:
            d = td_delay(idx, se_str, ce)
            if -60 <= d <= 120 and abs(d) < abs(best_delay):
                best_ce = ce; best_delay = d
        
        if sig.loc[se_near] == 0 and best_ce is None:
            for ce in c_exits:
                if ce <= se_d:
                    d = td_delay(idx, se_str, ce)
                    if -120 <= d and abs(d) < abs(best_delay):
                        best_ce = ce; best_delay = d
        
        if best_ce is not None:
            exit_detail.append((se_str, best_ce.strftime('%Y-%m-%d'), best_delay))
        else:
            exit_detail.append((se_str, 'MISSED', 999))
    
    for ce in c_exits:
        near_any = False
        for se_d in sep_exits:
            if abs(td_delay(idx, se_d.strftime('%Y-%m-%d'), ce)) < 60:
                near_any = True; break
        if not near_any:
            r1m, _ = ret_forward(qqq_a, ce, 21)
            if r1m > 3: false_exits += 1
    
    # Backtest
    r = se.run_backtest(idx, dr_qqq, None, None, effr_a, z_credit, vol_z, sig,
        inf_z=inf_z, nl_z=nl_z, use_sep=True, use_overlay=True)
    eq = r['equity']; ny = len(eq)/252
    cagr = (eq.iloc[-1]**(1/ny)-1)*100
    mdd = ((eq/eq.expanding().max())-1).min()*100
    dret = eq.pct_change().dropna()
    sh = dret.mean()/dret.std()*np.sqrt(252) if dret.std()>0 else 0
    dn = dret[dret<0]; ds = np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
    so = dret.mean()/ds*np.sqrt(252)
    out_pct = (sig == 0).mean() * 100
    
    results.append({
        'name': vname, 'cagr': cagr, 'mdd': mdd, 'sharpe': sh, 'sortino': so,
        'out_pct': out_pct, 'false_exits': false_exits,
        'exit_detail': exit_detail, 'total_exits': len(c_exits),
    })

results.sort(key=lambda x: x['sharpe'], reverse=True)

# SEP baseline
r_sep = se.run_backtest(idx, dr_qqq, None, None, effr_a, z_credit, vol_z, sep_state,
    inf_z=inf_z, nl_z=nl_z, use_sep=True, use_overlay=True)
eq_s = r_sep['equity']; ny = len(eq_s)/252
cagr_sep = (eq_s.iloc[-1]**(1/ny)-1)*100
mdd_sep = ((eq_s/eq_s.expanding().max())-1).min()*100
dret_sep = eq_s.pct_change().dropna()
sh_sep = dret_sep.mean()/dret_sep.std()*np.sqrt(252)

print(f"\n  {'Variant':<42} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5} {'FalseX':>7} {'TotalX':>7}  Exit events")
print(f"  {'─'*42} {'─'*7} {'─'*7} {'─'*7} {'─'*5} {'─'*7} {'─'*7}  {'─'*50}")

print(f"  {'★ Real SEP':<42} {sh_sep:>7.2f} {cagr_sep:>+6.1f}% {mdd_sep:>6.1f}% {(sep_state==0).mean()*100:>4.1f}% {'0':>7} {'—':>7}  all ON TIME")

for r in results:
    events = '  '.join([f"{e[0][:7]}:{e[2]:+d}td" if e[1]!='MISSED' else f"{e[0][:7]}:MISS" for e in r['exit_detail']])
    marker = ''
    if r['sharpe'] > sh_sep - 0.05 and r['false_exits'] <= 1:
        marker = ' ✅'
    elif r['sharpe'] > sh_sep - 0.10:
        marker = ' ⚠️'
    print(f"  {r['name']:<42} {r['sharpe']:>7.2f} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['out_pct']:>4.1f}% {r['false_exits']:>6} {r['total_exits']:>6}  {events}{marker}")

# Year-by-year for top 3
print(f"\n  YEAR-BY-YEAR: SEP vs top variants")
top3 = [r for r in results[:3]]

# Build equity curves
eq_sep = r_sep['equity']
eqs = {}
for r in top3:
    sig = build_signal(idx, variants[r['name']], 42)
    bt = se.run_backtest(idx, dr_qqq, None, None, effr_a, z_credit, vol_z, sig,
        inf_z=inf_z, nl_z=nl_z, use_sep=True, use_overlay=True)
    eqs[r['name']] = bt['equity']

print(f"\n  {'Year':<8} {'SEP':>8}", end='')
for r in top3: print(f"  {r['name'][:20]:>22}", end='')
print()
print(f"  {'─'*8} {'─'*8}", end='')
for _ in top3: print(f"  {'─'*22}", end='')
print()

for year in range(2012, 2027):
    mask = idx.year == year
    if mask.sum() == 0: continue
    
    yr_sep = eq_sep.loc[mask]
    sep_yr_ret = (float(yr_sep.iloc[-1]) / float(yr_sep.iloc[0]) - 1) * 100
    print(f"  {year:<8} {sep_yr_ret:>+7.1f}%", end='')
    
    for r in top3:
        yr_eq = eqs[r['name']].loc[mask]
        yr_ret = (float(yr_eq.iloc[-1]) / float(yr_eq.iloc[0]) - 1) * 100
        diff = yr_ret - sep_yr_ret
        marker = '✅' if abs(diff) < 3 else ('⚠️' if diff > 0 else '❌')
        print(f"  {yr_ret:>+7.1f}% ({diff:>+5.1f}){marker}", end='')
    print()
