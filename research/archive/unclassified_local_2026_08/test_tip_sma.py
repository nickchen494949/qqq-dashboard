#!/usr/bin/env python3
"""
TIP SMA TEST.
1. TIP > SMA = risk-on, TIP < SMA = risk-off (pure TIP)
2. TIP SMA as exit/re-entry combined with other signals
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
qqq = gy('QQQ'); tqqq = gy('TQQQ'); tip = gy('TIP'); tlt = gy('TLT')
hyg = gy('HYG'); ief = gy('IEF')
effr_raw = gf('EFFR'); dgs2 = gf('DGS2'); t5yifr = gf('T5YIFR')
dfii5 = gf('DFII5'); walcl = gf('WALCL'); rrp = gf('RRPONTSYD')
tga = gf('WTREGEN'); cpilfe = gf('CPILFESL')

idx = qqq.dropna().index; idx = idx[idx >= '2012-01-01']
qqq_a = qqq.reindex(idx); tqqq_a = tqqq.reindex(idx).ffill()
tip_a = tip.reindex(idx).ffill(); tlt_a = tlt.reindex(idx).ffill()
hyg_a = hyg.reindex(idx).ffill(); ief_a = ief.reindex(idx).ffill()
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

# Shift
dgs2_chg_3m = (dgs2_a - dgs2_a.shift(63)).shift(1)
real5y_chg_3m = (dfii5_a - dfii5_a.shift(63)).shift(1)
t5yifr_s = t5yifr_a.shift(1)
core_cpi_3m_d = core_cpi_3m_d.shift(1)

# TIP SMAs (shifted 1 day)
tip_s = tip_a.shift(1)
tip_tlt = (tip_a / tlt_a).shift(1)

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

def find_transitions(signal):
    entries, exits = [], []
    arr = signal.values
    for i in range(1, len(arr)):
        if arr[i] == 1 and arr[i-1] == 0: entries.append(signal.index[i])
        if arr[i] == 0 and arr[i-1] == 1: exits.append(signal.index[i])
    return entries, exits

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
    return sh, cagr, mdd, (signal==0).mean()*100, so, eq

sh_sep, cagr_sep, mdd_sep, out_sep, so_sep, eq_sep = run_bt(sep_state)

# ═══════════════════════════════════════════════════
# PART 1: PURE TIP — TIP > SMA = on, TIP < SMA = off
# ═══════════════════════════════════════════════════
print("="*120)
print("  PART 1: PURE TIP — TIP price vs SMA")
print("="*120)

print(f"\n  ★ SEP: Sharpe={sh_sep:.2f} CAGR={cagr_sep:+.1f}% MDD={mdd_sep:.1f}%\n")
print(f"  {'Signal':<45} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'Sort':>6} {'%OUT':>5} {'#Trades':>8}")
print(f"  {'─'*45} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*5} {'─'*8}")

for sma_len in [50, 100, 150, 200, 252]:
    tip_sma = tip_s.rolling(sma_len).mean()
    # Pure: TIP > SMA = on
    sig = (tip_s > tip_sma).astype(int).reindex(idx).fillna(1)
    sh, cagr, mdd, out, so, _ = run_bt(sig)
    entries, exits = find_transitions(sig)
    print(f"  {'TIP > SMA'+str(sma_len):<45} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}% {len(entries):>7}")

# TIP/TLT ratio vs SMA
print()
for sma_len in [50, 100, 150, 200, 252]:
    ratio_sma = tip_tlt.rolling(sma_len).mean()
    sig = (tip_tlt > ratio_sma).astype(int).reindex(idx).fillna(1)
    sh, cagr, mdd, out, so, _ = run_bt(sig)
    entries, exits = find_transitions(sig)
    print(f"  {'TIP/TLT > SMA'+str(sma_len):<45} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}% {len(entries):>7}")

# ═══════════════════════════════════════════════════
# PART 2: TIP SMA with min_hold (reduce whipsaw)
# ═══════════════════════════════════════════════════
print(f"\n{'='*120}")
print("  PART 2: TIP SMA with min_hold (reduce whipsaw)")
print("="*120)

print(f"\n  {'Signal':<45} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'Sort':>6} {'%OUT':>5} {'#Trades':>8}")
print(f"  {'─'*45} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*5} {'─'*8}")

for sma_len in [100, 150, 200]:
    for min_hold in [21, 42, 63]:
        tip_sma = tip_s.rolling(sma_len).mean()
        
        def build_tip_signal(idx, tip_s, tip_sma, min_hold):
            state = 1; hold = 999; states = []
            for d in idx:
                t = gv(tip_s, d); m = gv(tip_sma, d)
                if t == 0 or m == 0:
                    states.append(state); continue
                if state == 1:
                    if t < m:
                        state = 0; hold = 0
                else:
                    hold += 1
                    if hold >= min_hold and t > m:
                        state = 1
                states.append(state)
            return pd.Series(states, index=idx)
        
        sig = build_tip_signal(idx, tip_s, tip_sma, min_hold)
        sh, cagr, mdd, out, so, _ = run_bt(sig)
        entries, _ = find_transitions(sig)
        print(f"  {'TIP SMA'+str(sma_len)+' hold'+str(min_hold)+'d':<45} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}% {len(entries):>7}")

# Same for TIP/TLT ratio
print()
for sma_len in [100, 150, 200]:
    for min_hold in [21, 42, 63]:
        ratio_sma = tip_tlt.rolling(sma_len).mean()
        
        def build_ratio_signal(idx, ratio, ratio_sma, min_hold):
            state = 1; hold = 999; states = []
            for d in idx:
                r = gv(ratio, d); m = gv(ratio_sma, d)
                if r == 0 or m == 0:
                    states.append(state); continue
                if state == 1:
                    if r < m:
                        state = 0; hold = 0
                else:
                    hold += 1
                    if hold >= min_hold and r > m:
                        state = 1
                states.append(state)
            return pd.Series(states, index=idx)
        
        sig = build_ratio_signal(idx, tip_tlt, ratio_sma, min_hold)
        sh, cagr, mdd, out, so, _ = run_bt(sig)
        entries, _ = find_transitions(sig)
        print(f"  {'TIP/TLT SMA'+str(sma_len)+' hold'+str(min_hold)+'d':<45} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}% {len(entries):>7}")

# ═══════════════════════════════════════════════════
# PART 3: TIP as exit, Real5Y as re-entry (and vice versa)
# ═══════════════════════════════════════════════════
print(f"\n{'='*120}")
print("  PART 3: HYBRID — TIP exit + Real5Y re-entry / F exit + TIP re-entry")
print("="*120)

def make_reentry_r5y(d, i):
    return gv(real5y_chg_3m, d) < -0.30 and gv(core_cpi_3m_d, d) < 3.5

def make_f_exit(d, i):
    return gv(dgs2_chg_3m, d) > 0.30 and gv(core_cpi_3m_d, d) > 3.0 and gv(t5yifr_s, d) > 2.25

print(f"\n  {'Signal':<55} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'Sort':>6} {'%OUT':>5}")
print(f"  {'─'*55} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*5}")

# A: TIP SMA exit + Real5Y re-entry
for sma_len in [100, 150, 200]:
    tip_sma = tip_s.rolling(sma_len).mean()
    def tip_exit(d, i, ts=tip_s, tm=tip_sma):
        return gv(ts, d) < gv(tm, d) and gv(tm, d) > 0
    
    def build_hybrid(idx, exit_fn, reentry_fn, min_hold=42):
        state = 1; hold = 0; states = []
        for i, d in enumerate(idx):
            if state == 1:
                if exit_fn(d, i): state = 0; hold = 0
            else:
                hold += 1
                if hold >= min_hold and reentry_fn(d, i): state = 1
            states.append(state)
        return pd.Series(states, index=idx)
    
    sig = build_hybrid(idx, tip_exit, make_reentry_r5y, 42)
    sh, cagr, mdd, out, so, _ = run_bt(sig)
    print(f"  {'TIP<SMA'+str(sma_len)+' exit + Real5Y re-entry':<55} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}%")

# A2: TIP/TLT ratio SMA exit + Real5Y re-entry
for sma_len in [100, 150, 200]:
    ratio_sma = tip_tlt.rolling(sma_len).mean()
    def ratio_exit(d, i, r=tip_tlt, rm=ratio_sma):
        return gv(r, d) < gv(rm, d) and gv(rm, d) > 0
    
    sig = build_hybrid(idx, ratio_exit, make_reentry_r5y, 42)
    sh, cagr, mdd, out, so, _ = run_bt(sig)
    print(f"  {'TIP/TLT<SMA'+str(sma_len)+' exit + Real5Y re-entry':<55} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}%")

# B: F exit + TIP SMA re-entry
for sma_len in [100, 150, 200]:
    tip_sma = tip_s.rolling(sma_len).mean()
    def tip_reentry(d, i, ts=tip_s, tm=tip_sma):
        return gv(ts, d) > gv(tm, d) and gv(tm, d) > 0
    
    sig = build_hybrid(idx, make_f_exit, tip_reentry, 42)
    sh, cagr, mdd, out, so, _ = run_bt(sig)
    print(f"  {'F exit + TIP>SMA'+str(sma_len)+' re-entry':<55} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}%")

# B2: F exit + TIP/TLT ratio SMA re-entry
for sma_len in [100, 150, 200]:
    ratio_sma = tip_tlt.rolling(sma_len).mean()
    def ratio_reentry(d, i, r=tip_tlt, rm=ratio_sma):
        return gv(r, d) > gv(rm, d) and gv(rm, d) > 0
    
    sig = build_hybrid(idx, make_f_exit, ratio_reentry, 42)
    sh, cagr, mdd, out, so, _ = run_bt(sig)
    print(f"  {'F exit + TIP/TLT>SMA'+str(sma_len)+' re-entry':<55} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}%")

# C: TIP SMA exit + TIP SMA re-entry (full TIP)
for sma_len in [100, 150, 200]:
    tip_sma = tip_s.rolling(sma_len).mean()
    def tip_exit_c(d, i, ts=tip_s, tm=tip_sma):
        return gv(ts, d) < gv(tm, d) and gv(tm, d) > 0
    def tip_reentry_c(d, i, ts=tip_s, tm=tip_sma):
        return gv(ts, d) > gv(tm, d) and gv(tm, d) > 0
    
    sig = build_hybrid(idx, tip_exit_c, tip_reentry_c, 42)
    sh, cagr, mdd, out, so, _ = run_bt(sig)
    print(f"  {'TIP SMA'+str(sma_len)+' both exit+re-entry':<55} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}%")

# ═══════════════════════════════════════════════════
# PART 4: BEST vs SEP year-by-year
# ═══════════════════════════════════════════════════
print(f"\n{'='*120}")
print("  PART 4: COMPARISON — SEP vs F+R5Y vs best TIP configs")
print("="*120)

# Rebuild key signals for year-by-year
configs = {}

# SEP
configs['★ SEP'] = sep_state

# F exit + R5Y re-entry (current best)
def build_hybrid_g(idx, exit_fn, reentry_fn, min_hold=42):
    state = 1; hold = 0; states = []
    for i, d in enumerate(idx):
        if state == 1:
            if exit_fn(d, i): state = 0; hold = 0
        else:
            hold += 1
            if hold >= min_hold and reentry_fn(d, i): state = 1
        states.append(state)
    return pd.Series(states, index=idx)

configs['F exit + R5Y re-entry'] = build_hybrid_g(idx, make_f_exit, make_reentry_r5y, 42)

# Pure TIP SMA (best from part 1/2)
for sma_len in [100, 150, 200]:
    tip_sma = tip_s.rolling(sma_len).mean()
    def te(d,i,ts=tip_s,tm=tip_sma): return gv(ts,d)<gv(tm,d) and gv(tm,d)>0
    def tr(d,i,ts=tip_s,tm=tip_sma): return gv(ts,d)>gv(tm,d) and gv(tm,d)>0
    configs[f'TIP SMA{sma_len} pure'] = build_hybrid_g(idx, te, tr, 42)

# TIP/TLT SMA exit + R5Y re-entry
for sma_len in [100, 150, 200]:
    ratio_sma = tip_tlt.rolling(sma_len).mean()
    def re(d,i,r=tip_tlt,rm=ratio_sma): return gv(r,d)<gv(rm,d) and gv(rm,d)>0
    configs[f'TIP/TLT<SMA{sma_len}+R5Y'] = build_hybrid_g(idx, re, make_reentry_r5y, 42)

# F exit + TIP re-entry
for sma_len in [100, 150, 200]:
    tip_sma = tip_s.rolling(sma_len).mean()
    def tr2(d,i,ts=tip_s,tm=tip_sma): return gv(ts,d)>gv(tm,d) and gv(tm,d)>0
    configs[f'F exit+TIP>SMA{sma_len}'] = build_hybrid_g(idx, make_f_exit, tr2, 42)

print(f"\n  {'Strategy':<40} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'Sort':>6} {'%OUT':>5}")
print(f"  {'─'*40} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*5}")

bt_all = []
for name, sig in configs.items():
    sh, cagr, mdd, out, so, eq = run_bt(sig)
    bt_all.append((name, sh, cagr, mdd, out, so, eq))

bt_all.sort(key=lambda x: x[1], reverse=True)
for name, sh, cagr, mdd, out, so, eq in bt_all:
    mark = ' ◄' if name.startswith('★') else ''
    print(f"  {name:<40} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {so:>5.2f} {out:>4.1f}%{mark}")

# Year-by-year for top 5
print(f"\n  Year-by-year (top 5):")
top5 = bt_all[:5]
hdr = f"  {'Year':<6} "
for name, *_ in top5: hdr += f"  {name[:18]:>20}"
print(hdr)
print(f"  {'─'*6} " + f"  {'─'*20}" * len(top5))

for year in range(2012, 2027):
    mask = idx.year == year
    if mask.sum() == 0: continue
    line = f"  {year:<6} "
    for name, sh, cagr, mdd, out, so, eq in top5:
        yr = eq.loc[mask]
        yr_ret = (float(yr.iloc[-1]) / float(yr.iloc[0]) - 1) * 100
        line += f"  {yr_ret:>+7.1f}%{'':>11}"
    print(line)

print(f"\n  TIP SMA TEST COMPLETE.")
