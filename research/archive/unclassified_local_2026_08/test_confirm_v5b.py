#!/usr/bin/env python3
"""
FINAL CONFIRMATION v5b.
Mini grid: abs exit (5Y5Y: 2.20/2.25/2.30) × z-score reentry grid × z-window.
Goal: confirm 1.50+ is a plateau, not a spike.
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

print("Loading...")
qqq = gy('QQQ'); tqqq = gy('TQQQ')
hyg = gy('HYG'); ief = gy('IEF'); tip = gy('TIP'); tlt = gy('TLT')
effr_raw = gf('EFFR'); dgs2 = gf('DGS2')
t5yifr = gf('T5YIFR'); dfii5 = gf('DFII5')
walcl = gf('WALCL'); rrp = gf('RRPONTSYD'); tga = gf('WTREGEN')
cpilfe = gf('CPILFESL')

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

cpilfe_m = cpilfe.resample('MS').last().dropna()
core_cpi_3m = ((cpilfe_m / cpilfe_m.shift(3)).pow(4) - 1) * 100
core_cpi_3m_lagged = core_cpi_3m.copy()
core_cpi_3m_lagged.index += pd.Timedelta(days=45)
core_cpi_3m_d = core_cpi_3m_lagged.reindex(idx, method='ffill').ffill()

dgs2_chg_3m = (dgs2_a - dgs2_a.shift(63)).shift(1)
real5y_chg_3m = (dfii5_a - dfii5_a.shift(63)).shift(1)
t5yifr_s = t5yifr_a.shift(1)
core_cpi_3m_d = core_cpi_3m_d.shift(1)

dr_qqq = qqq_a.pct_change()
z_credit = se.compute_credit_z(hyg_a, ief_a)
vol_z = se.compute_vol_z(dr_qqq)
inf_z = se.compute_inflation_z(tip_a, tlt_a)
nl_z = se.compute_nl_z(walcl_a, rrp_a, tga_a)

sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

print(f"  Ready. {len(idx)} days.\n")

def gv(s, d, default=0.0):
    try:
        v = s.loc[d]; return float(v) if not np.isnan(v) else default
    except: return default

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

def run_bt(signal):
    r = se.run_backtest(idx, dr_qqq, None, None, effr_a, z_credit, vol_z, signal,
        inf_z=inf_z, nl_z=nl_z, use_sep=True, use_overlay=True)
    eq = r['equity']; ny = len(eq)/252
    cagr = (eq.iloc[-1]**(1/ny)-1)*100
    mdd = ((eq/eq.expanding().max())-1).min()*100
    dret = eq.pct_change().dropna()
    sh = dret.mean()/dret.std()*np.sqrt(252) if dret.std()>0 else 0
    dn = dret[dret<0]; ds = np.sqrt((dn**2).mean()) if len(dn)>0 else 1e-10
    so = dret.mean()/ds*np.sqrt(252)
    return sh, cagr, mdd, (signal==0).mean()*100, so

sh_sep, cagr_sep, mdd_sep, out_sep, so_sep = run_bt(sep_state)

# ═══════════════════════════════════════════════════
# GRID: exit 5Y5Y × reentry z-params × z-window
# ═══════════════════════════════════════════════════
print("="*130)
print("  CONFIRMATION GRID: abs exit × z-score re-entry × z-window")
print("="*130)

results = []

for zwin in [378, 504, 630, 756]:  # 1.5y, 2y, 2.5y, 3y
    # Build z-scores for this window
    r5y_z = ((real5y_chg_3m - real5y_chg_3m.rolling(zwin).mean()) / real5y_chg_3m.rolling(zwin).std()).fillna(0)
    cpi_z = ((core_cpi_3m_d - core_cpi_3m_d.rolling(zwin).mean()) / core_cpi_3m_d.rolling(zwin).std()).fillna(0)
    
    for t5y_th in [2.20, 2.25, 2.30]:
        for rz_th in [-0.8, -1.0, -1.2, -1.5]:
            for cz_th in [-0.25, 0.0, 0.25]:
                efn = lambda d,i,t=t5y_th: gv(dgs2_chg_3m,d)>0.30 and gv(core_cpi_3m_d,d)>3.0 and gv(t5yifr_s,d)>t
                rfn = lambda d,i,rz=rz_th,cz=cz_th,rz_s=r5y_z,cz_s=cpi_z: gv(rz_s,d)<rz and gv(cz_s,d)<cz
                sig = build_signal(idx, efn, rfn, 42)
                sh, cagr, mdd, out, so = run_bt(sig)
                results.append({
                    'zwin': zwin, 't5y': t5y_th, 'rz': rz_th, 'cz': cz_th,
                    'sharpe': sh, 'cagr': cagr, 'mdd': mdd, 'out': out, 'sortino': so
                })

results.sort(key=lambda x: x['sharpe'], reverse=True)

print(f"\n  ★ SEP: Sharpe={sh_sep:.2f} CAGR={cagr_sep:+.1f}% MDD={mdd_sep:.1f}% Sortino={so_sep:.2f}")
print(f"\n  {'Rank':<5} {'Zwin':>5} {'5Y5Y':>5} {'R5Yz':>5} {'CPIz':>5} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'Sort':>6} {'%OUT':>5}")
print(f"  {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*5}")

for i, r in enumerate(results[:30]):
    mark = ' ✅' if r['sharpe'] >= sh_sep - 0.03 else (' ⚠️' if r['sharpe'] >= sh_sep - 0.08 else '')
    print(f"  {i+1:<5} {r['zwin']:>4}d {r['t5y']:>5.2f} {r['rz']:>5.1f} {r['cz']:>+4.2f} {r['sharpe']:>7.2f} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sortino']:>5.2f} {r['out']:>4.1f}%{mark}")

# ═══════════════════════════════════════════════════
# PLATEAU CHECK: how many configs above each Sharpe level?
# ═══════════════════════════════════════════════════
print(f"\n  PLATEAU CHECK:")
total = len(results)
for level in [1.50, 1.48, 1.45, 1.40, 1.35]:
    count = sum(1 for r in results if r['sharpe'] >= level)
    pct = count / total * 100
    bar = '█' * int(pct)
    print(f"    Sharpe ≥ {level:.2f}: {count:>4}/{total} ({pct:>5.1f}%) {bar}")

# ═══════════════════════════════════════════════════
# STABILITY: Sharpe range per parameter
# ═══════════════════════════════════════════════════
print(f"\n  PARAMETER STABILITY (Sharpe range across all combos):")
for param, key in [('z-window', 'zwin'), ('5Y5Y threshold', 't5y'), ('R5Y z-thresh', 'rz'), ('CPI z-thresh', 'cz')]:
    vals = sorted(set(r[key] for r in results))
    print(f"\n    {param}:")
    for v in vals:
        subset = [r['sharpe'] for r in results if r[key] == v]
        mn, mx, md = min(subset), max(subset), np.median(subset)
        bar = '█' * int(md * 20)
        print(f"      {v:>7}: median={md:.2f}  range={mn:.2f}–{mx:.2f}  {bar}")

# ═══════════════════════════════════════════════════
# TOP 5: year-by-year vs SEP
# ═══════════════════════════════════════════════════
print(f"\n\n{'='*130}")
print("  TOP 5 vs SEP: year-by-year")
print("="*130)

sep_eq = se.run_backtest(idx, dr_qqq, None, None, effr_a, z_credit, vol_z, sep_state,
    inf_z=inf_z, nl_z=nl_z, use_sep=True, use_overlay=True)['equity']

top5 = results[:5]
top5_eqs = []
for r in top5:
    zwin = r['zwin']
    r5y_z = ((real5y_chg_3m - real5y_chg_3m.rolling(zwin).mean()) / real5y_chg_3m.rolling(zwin).std()).fillna(0)
    cpi_z = ((core_cpi_3m_d - core_cpi_3m_d.rolling(zwin).mean()) / core_cpi_3m_d.rolling(zwin).std()).fillna(0)
    efn = lambda d,i,t=r['t5y']: gv(dgs2_chg_3m,d)>0.30 and gv(core_cpi_3m_d,d)>3.0 and gv(t5yifr_s,d)>t
    rfn = lambda d,i,rz=r['rz'],cz=r['cz'],rz_s=r5y_z,cz_s=cpi_z: gv(rz_s,d)<rz and gv(cz_s,d)<cz
    sig = build_signal(idx, efn, rfn, 42)
    eq = se.run_backtest(idx, dr_qqq, None, None, effr_a, z_credit, vol_z, sig,
        inf_z=inf_z, nl_z=nl_z, use_sep=True, use_overlay=True)['equity']
    top5_eqs.append((r, eq))

# Print header
hdr = f"  {'Year':<6} {'SEP':>8}"
for i, (r, _) in enumerate(top5_eqs):
    hdr += f"  #{i+1:>22}"
print(hdr)
print(f"  {'─'*6} {'─'*8}" + f"  {'─'*22}" * len(top5_eqs))

for year in range(2012, 2027):
    mask = idx.year == year
    if mask.sum() == 0: continue
    yr_sep = sep_eq.loc[mask]
    sep_yr = (float(yr_sep.iloc[-1]) / float(yr_sep.iloc[0]) - 1) * 100
    line = f"  {year:<6} {sep_yr:>+7.1f}%"
    for r, eq in top5_eqs:
        yr_eq = eq.loc[mask]
        yr_ret = (float(yr_eq.iloc[-1]) / float(yr_eq.iloc[0]) - 1) * 100
        diff = yr_ret - sep_yr
        m = '✅' if abs(diff) < 3 else ('⚠️' if abs(diff) < 10 else '❌')
        line += f"  {yr_ret:>+7.1f}%({diff:>+5.1f}){m}"
    print(line)

print(f"\n  Top 5 configs:")
for i, (r, _) in enumerate(top5_eqs):
    print(f"    #{i+1}: zwin={r['zwin']}d  5Y5Y>{r['t5y']:.2f}  R5Yz<{r['rz']:.1f}  CPIz<{r['cz']:+.2f}  Sharpe={r['sharpe']:.2f}")

print(f"\n  CONFIRMATION COMPLETE.")
