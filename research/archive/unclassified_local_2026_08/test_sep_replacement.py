#!/usr/bin/env python3
"""
Find the best SEP replacement using daily/monthly data.
Same logic: state machine with trigger/recover hysteresis.

SEP logic:
  EXIT: rate_up AND pce > 2.0 AND pce_up (quarterly)
  ENTER: rate_down (quarterly)

Candidates:
  A. 2Y yield momentum + 5Y5Y breakeven level
  B. 2Y yield momentum + Core CPI 3m annualized
  C. Fed funds rate change + 5Y5Y breakeven
  D. 2Y-FFR spread (market expects hikes) + breakeven
  E. Pure 2Y yield z-score
  F. Pure 5Y5Y breakeven z-score
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
    s = fred.get_series(sid, observation_start='2005-01-01')
    s.to_csv(p)
    return s

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
# LOAD DATA
# ═══════════════════════════════════
print("Loading data...")
qqq = gy('QQQ')
hyg = gy('HYG'); ief = gy('IEF')
tip = gy('TIP'); tlt = gy('TLT')

# FRED series
effr_raw = gf('EFFR')
dgs2 = gf('DGS2')        # 2Y Treasury yield
t5yifr = gf('T5YIFR')    # 5Y5Y forward inflation expectation
ffr_upper = gf('DFEDTARU') # Fed funds target rate upper bound
cpilfe = gf('CPILFESL')   # Core CPI (monthly, index level)
walcl = gf('WALCL'); rrp = gf('RRPONTSYD'); tga = gf('WTREGEN')

idx = qqq.dropna().index
idx = idx[idx >= '2012-01-01']
qqq_a = qqq.reindex(idx)
hyg_a = hyg.reindex(idx).ffill(); ief_a = ief.reindex(idx).ffill()
tip_a = tip.reindex(idx).ffill(); tlt_a = tlt.reindex(idx).ffill()
effr_a = effr_raw.reindex(idx, method='ffill').ffill() / 36500
dgs2_a = dgs2.reindex(idx, method='ffill').ffill()
t5yifr_a = t5yifr.reindex(idx, method='ffill').ffill()
ffr_a = ffr_upper.reindex(idx, method='ffill').ffill()
walcl_a = walcl.resample('D').ffill().reindex(idx, method='ffill').ffill()
rrp_a = rrp.resample('D').ffill().reindex(idx, method='ffill').ffill()
tga_a = tga.resample('D').ffill().reindex(idx, method='ffill').ffill()

# Core CPI 3-month annualized rate
cpilfe_m = cpilfe.resample('ME').last().dropna()
core_cpi_3m = (cpilfe_m / cpilfe_m.shift(3)).pow(4) - 1  # annualized
core_cpi_3m = core_cpi_3m * 100  # percent
core_cpi_3m_d = core_cpi_3m.reindex(idx, method='ffill').ffill()

dr_qqq = qqq_a.pct_change()

# Z-score signals (for overlay comparison)
z_credit = se.compute_credit_z(hyg_a, ief_a)
vol_z = se.compute_vol_z(dr_qqq)
inf_z = se.compute_inflation_z(tip_a, tlt_a)
nl_z = se.compute_nl_z(walcl_a, rrp_a, tga_a)

# Real SEP
sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

print(f"  Index: {idx[0].strftime('%Y-%m-%d')} to {idx[-1].strftime('%Y-%m-%d')} ({len(idx)} days)")
print(f"  SEP OUT days: {(sep_state==0).sum()} ({(sep_state==0).mean()*100:.1f}%)")

# ═══════════════════════════════════
# BUILD SEP REPLACEMENT SIGNALS
# ═══════════════════════════════════

# Helper: monthly resampled for quarterly-like comparison
dgs2_m = dgs2_a.resample('ME').last()  # monthly 2Y
t5yifr_m = t5yifr_a.resample('ME').last()
ffr_m = ffr_a.resample('ME').last()

def build_signal_A(idx, enter_th, exit_th, lookback=63):
    """2Y yield 3-month momentum + 5Y5Y breakeven level.
    EXIT: 2Y rising (3m change > enter_th bps) AND 5Y5Y > breakeven_th
    ENTER: 2Y falling (3m change < exit_th bps) AND 5Y5Y < breakeven_exit"""
    dgs2_chg = dgs2_a - dgs2_a.shift(lookback)  # 3-month change in 2Y yield
    state = 1  # start IN
    states = []
    for i, d in enumerate(idx):
        chg = dgs2_chg.loc[d] if d in dgs2_chg.index and not np.isnan(dgs2_chg.loc[d]) else 0
        be = t5yifr_a.loc[d] if d in t5yifr_a.index and not np.isnan(t5yifr_a.loc[d]) else 2.0
        if state == 1:  # IN
            if chg > enter_th and be > 2.5:
                state = 0  # EXIT
        else:  # OUT
            if chg < exit_th and be < 2.3:
                state = 1  # ENTER
        states.append(state)
    return pd.Series(states, index=idx)

def build_signal_B(idx, rate_enter, rate_exit, cpi_enter, cpi_exit):
    """2Y yield momentum + Core CPI 3m annualized.
    Mimics SEP: rate up + inflation high → EXIT"""
    dgs2_chg = dgs2_a - dgs2_a.shift(63)
    state = 1
    states = []
    for d in idx:
        chg = dgs2_chg.loc[d] if d in dgs2_chg.index and not np.isnan(dgs2_chg.loc[d]) else 0
        cpi = core_cpi_3m_d.loc[d] if d in core_cpi_3m_d.index and not np.isnan(core_cpi_3m_d.loc[d]) else 2.0
        if state == 1:
            if chg > rate_enter and cpi > cpi_enter:
                state = 0
        else:
            if chg < rate_exit or cpi < cpi_exit:
                state = 1
        states.append(state)
    return pd.Series(states, index=idx)

def build_signal_C(idx, spread_enter, spread_exit, be_enter, be_exit):
    """2Y - FFR spread (market pricing hikes) + 5Y5Y breakeven.
    When 2Y > FFR, market expects rate hikes → hawkish."""
    spread = dgs2_a - ffr_a  # positive = market expects hikes
    state = 1
    states = []
    for d in idx:
        sp = spread.loc[d] if d in spread.index and not np.isnan(spread.loc[d]) else 0
        be = t5yifr_a.loc[d] if d in t5yifr_a.index and not np.isnan(t5yifr_a.loc[d]) else 2.0
        if state == 1:
            if sp > spread_enter and be > be_enter:
                state = 0
        else:
            if sp < spread_exit or be < be_exit:
                state = 1
        states.append(state)
    return pd.Series(states, index=idx)

def build_signal_D(idx, enter_z, exit_z, min_hold=21):
    """Pure 2Y yield Z-score with hysteresis + min hold."""
    dgs2_z = (dgs2_a - dgs2_a.rolling(252).mean()) / dgs2_a.rolling(252).std()
    state = 1; hold = 0
    states = []
    for d in idx:
        z = dgs2_z.loc[d] if d in dgs2_z.index and not np.isnan(dgs2_z.loc[d]) else 0
        if state == 1:
            if z > enter_z:
                state = 0; hold = 0
        else:
            hold += 1
            if hold >= min_hold and z < exit_z:
                state = 1
        states.append(state)
    return pd.Series(states, index=idx)

def build_signal_E(idx, enter_th, exit_th, min_hold=42):
    """5Y5Y breakeven with hysteresis + min hold."""
    state = 1; hold = 0
    states = []
    for d in idx:
        be = t5yifr_a.loc[d] if d in t5yifr_a.index and not np.isnan(t5yifr_a.loc[d]) else 2.0
        if state == 1:
            if be > enter_th:
                state = 0; hold = 0
        else:
            hold += 1
            if hold >= min_hold and be < exit_th:
                state = 1
        states.append(state)
    return pd.Series(states, index=idx)

def build_signal_F(idx, rate_chg_enter, cpi_enter, be_enter, rate_chg_exit, cpi_exit, be_exit, min_hold=42):
    """Combined: 2Y momentum + CPI + breakeven. Most SEP-like.
    EXIT: 2Y rising fast + CPI hot + breakeven high
    ENTER: any condition reverses + min hold"""
    dgs2_chg = dgs2_a - dgs2_a.shift(63)
    state = 1; hold = 0
    states = []
    for d in idx:
        chg = dgs2_chg.loc[d] if d in dgs2_chg.index and not np.isnan(dgs2_chg.loc[d]) else 0
        cpi = core_cpi_3m_d.loc[d] if d in core_cpi_3m_d.index and not np.isnan(core_cpi_3m_d.loc[d]) else 2.0
        be = t5yifr_a.loc[d] if d in t5yifr_a.index and not np.isnan(t5yifr_a.loc[d]) else 2.0
        if state == 1:
            if chg > rate_chg_enter and cpi > cpi_enter and be > be_enter:
                state = 0; hold = 0
        else:
            hold += 1
            if hold >= min_hold and chg < rate_chg_exit and cpi < cpi_exit:
                state = 1
        states.append(state)
    return pd.Series(states, index=idx)

# ═══════════════════════════════════
# BACKTEST
# ═══════════════════════════════════
def run_bt(signal, label):
    """Run full backtest with SEP replaced by signal, overlay ON."""
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
    
    out_pct = (signal==0).mean()*100
    switches = np.sum(np.diff(signal.values)!=0)
    
    return {'label':label,'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so,
            'out_pct':out_pct,'switches':switches,'equity':eq}

# ═══════════════════════════════════
# RUN ALL CANDIDATES
# ═══════════════════════════════════
print("\nRunning backtests...")

results = []

# Baseline: real SEP
r0 = run_bt(sep_state, '★ Real SEP')
results.append(r0)

# No SEP (always IN)
always_in = pd.Series(1, index=idx)
r_nosep = run_bt(always_in, 'No SEP (always IN)')
results.append(r_nosep)

# A: 2Y momentum + 5Y5Y breakeven
for enter_th in [0.3, 0.5, 0.7]:
    for exit_th in [-0.3, -0.1, 0.0]:
        sig = build_signal_A(idx, enter_th, exit_th)
        r = run_bt(sig, f'A: 2Y_mom>{enter_th}/5Y5Y | exit<{exit_th}')
        results.append(r)

# B: 2Y momentum + Core CPI
for re in [0.3, 0.5]:
    for rx in [-0.2, 0.0]:
        for ce in [3.5, 4.0]:
            for cx in [2.5, 3.0]:
                sig = build_signal_B(idx, re, rx, ce, cx)
                r = run_bt(sig, f'B: 2Y>{re},CPI>{ce} | 2Y<{rx},CPI<{cx}')
                results.append(r)

# C: 2Y-FFR spread + breakeven
for se_val in [0.0, 0.2, 0.4]:
    for sx in [-0.3, -0.1]:
        for be_e in [2.4, 2.6]:
            for be_x in [2.1, 2.3]:
                sig = build_signal_C(idx, se_val, sx, be_e, be_x)
                r = run_bt(sig, f'C: spr>{se_val},be>{be_e} | spr<{sx},be<{be_x}')
                results.append(r)

# D: Pure 2Y Z-score
for ez in [1.0, 1.5, 2.0]:
    for xz in [0.0, 0.5]:
        for mh in [21, 42]:
            sig = build_signal_D(idx, ez, xz, mh)
            r = run_bt(sig, f'D: 2Yz>{ez} exit<{xz} hold={mh}')
            results.append(r)

# E: Pure 5Y5Y breakeven
for et in [2.4, 2.5, 2.6]:
    for xt in [2.1, 2.2, 2.3]:
        for mh in [21, 42]:
            sig = build_signal_E(idx, et, xt, mh)
            r = run_bt(sig, f'E: 5Y5Y>{et} exit<{xt} hold={mh}')
            results.append(r)

# F: Combined (most SEP-like)
for rce in [0.3, 0.5]:
    for cie in [3.0, 3.5]:
        for bie in [2.3, 2.5]:
            for rcx in [-0.1, 0.1]:
                for cix in [2.5, 3.0]:
                    sig = build_signal_F(idx, rce, cie, bie, rcx, cix, 2.3, 42)
                    r = run_bt(sig, f'F: 2Y>{rce},CPI>{cie},BE>{bie}')
                    results.append(r)

# ═══════════════════════════════════
# RESULTS
# ═══════════════════════════════════
print(f"\n{'='*110}")
print("  SEP REPLACEMENT CANDIDATES — sorted by Sharpe")
print("="*110)

# Filter: must have been OUT at least 5% of the time (not trivial)
valid = [r for r in results if r['out_pct'] > 3 or r['label'].startswith('★') or r['label'].startswith('No')]
valid.sort(key=lambda x: x['sharpe'], reverse=True)

print(f"\n  {'Rank':<5} {'Strategy':<45} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sort':>6} {'%OUT':>6} {'Sw':>4}")
print(f"  {'─'*5} {'─'*45} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*6} {'─'*4}")

for i, r in enumerate(valid[:25]):
    marker = ''
    if r['label'].startswith('★'):
        marker = ' ◄ YOUR STRATEGY'
    elif r['sharpe'] > r0['sharpe']:
        marker = ' ✅'
    print(f"  {i+1:<5} {r['label']:<45} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>5.2f} {r['out_pct']:>5.1f}% {r['switches']:>4}{marker}")

# Best per category
print(f"\n  BEST PER CATEGORY:")
for prefix, name in [('A:', '2Y mom + 5Y5Y'), ('B:', '2Y mom + CPI'), 
                      ('C:', '2Y-FFR + BE'), ('D:', 'Pure 2Y Z'),
                      ('E:', 'Pure 5Y5Y'), ('F:', 'Combined')]:
    cat = [r for r in valid if r['label'].startswith(prefix)]
    if cat:
        best = max(cat, key=lambda x: x['sharpe'])
        vs = best['sharpe'] - r0['sharpe']
        icon = '✅' if vs > 0 else '❌'
        print(f"    {icon} {name:<20} Sharpe={best['sharpe']:.2f} (vs SEP {vs:+.2f})  {best['label']}")

# Correlation of signals with real SEP
print(f"\n  SIGNAL CORRELATION WITH REAL SEP:")
for prefix in ['A:', 'B:', 'C:', 'D:', 'E:', 'F:']:
    cat = [r for r in results if r['label'].startswith(prefix)]
    if cat:
        best = max(cat, key=lambda x: x['sharpe'])
        # Rebuild best signal for correlation
        # Just check agreement rate
        pass

# Year by year for top 3 vs SEP
top3 = [r for r in valid if not r['label'].startswith('★') and not r['label'].startswith('No')][:3]
print(f"\n  YEAR-BY-YEAR: Top candidates vs Real SEP")
print(f"  {'Year':>6} {'SEP':>8}", end='')
for t in top3:
    short = t['label'][:20]
    print(f" {short:>22}", end='')
print()
print(f"  {'─'*6} {'─'*8}", end='')
for _ in top3: print(f" {'─'*22}", end='')
print()

for y in sorted(set(idx.year)):
    m = idx.year == y
    if m.sum() < 50: continue
    e0 = r0['equity'].loc[idx[m]]
    c0 = (e0.iloc[-1]/e0.iloc[0]-1)*100
    print(f"  {y:>6} {c0:>+7.1f}%", end='')
    for t in top3:
        et = t['equity'].loc[idx[m]]
        ct = (et.iloc[-1]/et.iloc[0]-1)*100
        d = ct - c0
        icon = '✅' if d > 5 else ('❌' if d < -5 else '  ')
        print(f" {ct:>+7.1f}% ({d:>+5.1f}%){icon}", end='')
    print()
