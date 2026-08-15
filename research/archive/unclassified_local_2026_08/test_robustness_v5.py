#!/usr/bin/env python3
"""
ROBUSTNESS TEST v5.
1. Sensitivity: sweep each threshold independently, check Sharpe stability
2. Z-score: replace absolute thresholds with rolling z-scores
3. Combined: z-score exit + z-score re-entry
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

# All shifted 1 day
dgs2_chg_3m = (dgs2_a - dgs2_a.shift(63)).shift(1)
real5y_chg_3m = (dfii5_a - dfii5_a.shift(63)).shift(1)
t5yifr_s = t5yifr_a.shift(1)
core_cpi_3m_d = core_cpi_3m_d.shift(1)

# Z-scores (rolling 504 = 2 years)
ZWIN = 504
dgs2_chg_z = ((dgs2_chg_3m - dgs2_chg_3m.rolling(ZWIN).mean()) / dgs2_chg_3m.rolling(ZWIN).std()).fillna(0)
real5y_chg_z = ((real5y_chg_3m - real5y_chg_3m.rolling(ZWIN).mean()) / real5y_chg_3m.rolling(ZWIN).std()).fillna(0)
cpi_z = ((core_cpi_3m_d - core_cpi_3m_d.rolling(ZWIN).mean()) / core_cpi_3m_d.rolling(ZWIN).std()).fillna(0)
t5yifr_z = ((t5yifr_s - t5yifr_s.rolling(ZWIN).mean()) / t5yifr_s.rolling(ZWIN).std()).fillna(0)

dr_qqq = qqq_a.pct_change()
z_credit = se.compute_credit_z(hyg_a, ief_a)
vol_z = se.compute_vol_z(dr_qqq)
inf_z = se.compute_inflation_z(tip_a, tlt_a)
nl_z = se.compute_nl_z(walcl_a, rrp_a, tga_a)

sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

print(f"  Data ready. {len(idx)} days.\n")

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
    out = (signal==0).mean()*100
    return sh, cagr, mdd, out

# SEP baseline
sh_sep, cagr_sep, mdd_sep, out_sep = run_bt(sep_state)
print(f"  ★ SEP baseline: Sharpe={sh_sep:.2f} CAGR={cagr_sep:+.1f}% MDD={mdd_sep:.1f}%\n")

# ═══════════════════════════════════════════════════
# PART 1: SENSITIVITY — sweep each parameter
# ═══════════════════════════════════════════════════
print("="*120)
print("  PART 1: SENSITIVITY — one parameter at a time, others fixed at base")
print("="*120)

# Base: exit = 2Y3m>0.30 & CPI>3.0 & 5Y5Y>2.30, reentry = R5Y<-0.30 & CPI<3.5
def make_exit(dgs2_th, cpi_th, t5y_th):
    return lambda d,i: gv(dgs2_chg_3m,d)>dgs2_th and gv(core_cpi_3m_d,d)>cpi_th and gv(t5yifr_s,d)>t5y_th

def make_reentry(r5y_th, cpi_th):
    return lambda d,i: gv(real5y_chg_3m,d)<r5y_th and gv(core_cpi_3m_d,d)<cpi_th

# Sweep exit 2Y3m threshold
print(f"\n  EXIT: 2Y 3m change threshold (CPI=3.0, 5Y5Y=2.30 fixed)")
print(f"  {'2Y3m th':>8} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5}  bar")
print(f"  {'─'*8} {'─'*7} {'─'*7} {'─'*7} {'─'*5}  {'─'*30}")
for th in [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
    sig = build_signal(idx, make_exit(th, 3.0, 2.30), make_reentry(-0.30, 3.5), 42)
    sh, cagr, mdd, out = run_bt(sig)
    bar = '█' * int(sh * 20)
    mark = ' ◄ base' if th == 0.30 else ''
    print(f"  {th:>8.2f} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {out:>4.1f}%  {bar}{mark}")

# Sweep exit CPI threshold
print(f"\n  EXIT: CPI 3m threshold (2Y3m=0.30, 5Y5Y=2.30 fixed)")
print(f"  {'CPI th':>8} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5}  bar")
print(f"  {'─'*8} {'─'*7} {'─'*7} {'─'*7} {'─'*5}  {'─'*30}")
for th in [2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0]:
    sig = build_signal(idx, make_exit(0.30, th, 2.30), make_reentry(-0.30, 3.5), 42)
    sh, cagr, mdd, out = run_bt(sig)
    bar = '█' * int(sh * 20)
    mark = ' ◄ base' if th == 3.0 else ''
    print(f"  {th:>8.2f} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {out:>4.1f}%  {bar}{mark}")

# Sweep exit 5Y5Y threshold
print(f"\n  EXIT: 5Y5Y breakeven threshold (2Y3m=0.30, CPI=3.0 fixed)")
print(f"  {'5Y5Y th':>8} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5}  bar")
print(f"  {'─'*8} {'─'*7} {'─'*7} {'─'*7} {'─'*5}  {'─'*30}")
for th in [2.00, 2.10, 2.15, 2.20, 2.25, 2.30, 2.35, 2.40, 2.50]:
    sig = build_signal(idx, make_exit(0.30, 3.0, th), make_reentry(-0.30, 3.5), 42)
    sh, cagr, mdd, out = run_bt(sig)
    bar = '█' * int(sh * 20)
    mark = ' ◄ base' if th == 2.30 else ''
    print(f"  {th:>8.2f} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {out:>4.1f}%  {bar}{mark}")

# Sweep reentry R5Y threshold
print(f"\n  RE-ENTRY: Real 5Y change threshold (CPI=3.5 fixed)")
print(f"  {'R5Y th':>8} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5}  bar")
print(f"  {'─'*8} {'─'*7} {'─'*7} {'─'*7} {'─'*5}  {'─'*30}")
for th in [-0.10, -0.15, -0.20, -0.25, -0.30, -0.35, -0.40, -0.50]:
    sig = build_signal(idx, make_exit(0.30, 3.0, 2.30), make_reentry(th, 3.5), 42)
    sh, cagr, mdd, out = run_bt(sig)
    bar = '█' * int(sh * 20)
    mark = ' ◄ base' if th == -0.30 else ''
    print(f"  {th:>8.2f} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {out:>4.1f}%  {bar}{mark}")

# Sweep reentry CPI threshold
print(f"\n  RE-ENTRY: CPI threshold (R5Y=-0.30 fixed)")
print(f"  {'CPI th':>8} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5}  bar")
print(f"  {'─'*8} {'─'*7} {'─'*7} {'─'*7} {'─'*5}  {'─'*30}")
for th in [2.5, 3.0, 3.25, 3.5, 3.75, 4.0, 4.5, 5.0]:
    sig = build_signal(idx, make_exit(0.30, 3.0, 2.30), make_reentry(-0.30, th), 42)
    sh, cagr, mdd, out = run_bt(sig)
    bar = '█' * int(sh * 20)
    mark = ' ◄ base' if th == 3.5 else ''
    print(f"  {th:>8.2f} {sh:>7.2f} {cagr:>+6.1f}% {mdd:>6.1f}% {out:>4.1f}%  {bar}{mark}")

# ═══════════════════════════════════════════════════
# PART 2: Z-SCORE BASED SIGNALS
# ═══════════════════════════════════════════════════
print(f"\n\n{'='*120}")
print("  PART 2: Z-SCORE SIGNALS (rolling 2-year, regime-adaptive)")
print("="*120)

# Exit z-score
print(f"\n  Z-SCORE EXIT: 2Y_z > X AND CPI_z > Y AND 5Y5Y_z > Z")
print(f"  {'2Y_z':>5} {'CPI_z':>6} {'5Y5Y_z':>7} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5}")
print(f"  {'─'*5} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*5}")

z_exit_results = []
for dz in [0.5, 1.0, 1.5, 2.0]:
    for cz in [0.5, 1.0, 1.5]:
        for tz in [0.0, 0.5, 1.0]:
            efn = lambda d,i,dz_=dz,cz_=cz,tz_=tz: (
                gv(dgs2_chg_z,d) > dz_ and gv(cpi_z,d) > cz_ and gv(t5yifr_z,d) > tz_)
            rfn = lambda d,i: gv(real5y_chg_3m,d) < -0.30 and gv(core_cpi_3m_d,d) < 3.5
            sig = build_signal(idx, efn, rfn, 42)
            sh, cagr, mdd, out = run_bt(sig)
            z_exit_results.append((dz, cz, tz, sh, cagr, mdd, out))

z_exit_results.sort(key=lambda x: x[3], reverse=True)
for r in z_exit_results[:15]:
    mark = ' ✅' if r[3] > sh_sep - 0.08 else ''
    print(f"  {r[0]:>5.1f} {r[1]:>6.1f} {r[2]:>7.1f} {r[3]:>7.2f} {r[4]:>+6.1f}% {r[5]:>6.1f}% {r[6]:>4.1f}%{mark}")

# Re-entry z-score
print(f"\n  Z-SCORE RE-ENTRY: R5Y_z < -X AND CPI_z < Y")
print(f"  {'R5Y_z':>6} {'CPI_z':>6} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5}")
print(f"  {'─'*6} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*5}")

z_re_results = []
for rz in [0.5, 1.0, 1.5, 2.0]:
    for cz in [-1.0, -0.5, 0.0, 0.5]:
        efn = lambda d,i: gv(dgs2_chg_3m,d) > 0.30 and gv(core_cpi_3m_d,d) > 3.0 and gv(t5yifr_s,d) > 2.30
        rfn = lambda d,i,rz_=rz,cz_=cz: gv(real5y_chg_z,d) < -rz_ and gv(cpi_z,d) < cz_
        sig = build_signal(idx, efn, rfn, 42)
        sh, cagr, mdd, out = run_bt(sig)
        z_re_results.append((rz, cz, sh, cagr, mdd, out))

z_re_results.sort(key=lambda x: x[2], reverse=True)
for r in z_re_results[:10]:
    mark = ' ✅' if r[2] > sh_sep - 0.08 else ''
    print(f"  {r[0]:>6.1f} {r[1]:>6.1f} {r[2]:>7.2f} {r[3]:>+6.1f}% {r[4]:>6.1f}% {r[5]:>4.1f}%{mark}")

# ═══════════════════════════════════════════════════
# PART 3: FULL Z-SCORE (both exit and re-entry)
# ═══════════════════════════════════════════════════
print(f"\n\n{'='*120}")
print("  PART 3: FULL Z-SCORE — best exit z + best re-entry z")
print("="*120)

# Take top 3 exit z configs × top 3 re-entry z configs
top_exit_z = z_exit_results[:5]
top_re_z = z_re_results[:5]

print(f"\n  {'Exit z':>25} {'Re-entry z':>20} {'Sharpe':>7} {'CAGR':>7} {'MDD':>7} {'%OUT':>5}")
print(f"  {'─'*25} {'─'*20} {'─'*7} {'─'*7} {'─'*7} {'─'*5}")

full_z = []
for ez in top_exit_z:
    for rz in top_re_z:
        efn = lambda d,i,dz_=ez[0],cz_=ez[1],tz_=ez[2]: (
            gv(dgs2_chg_z,d) > dz_ and gv(cpi_z,d) > cz_ and gv(t5yifr_z,d) > tz_)
        rfn = lambda d,i,rz_=rz[0],cz_=rz[1]: gv(real5y_chg_z,d) < -rz_ and gv(cpi_z,d) < cz_
        sig = build_signal(idx, efn, rfn, 42)
        sh, cagr, mdd, out = run_bt(sig)
        label_e = f"2Y>{ez[0]:.1f} CPI>{ez[1]:.1f} 5Y5Y>{ez[2]:.1f}"
        label_r = f"R5Y<-{rz[0]:.1f} CPI<{rz[1]:.1f}"
        full_z.append((label_e, label_r, sh, cagr, mdd, out))

full_z.sort(key=lambda x: x[2], reverse=True)
for r in full_z[:15]:
    mark = ' ✅' if r[2] > sh_sep - 0.08 else ''
    print(f"  {r[0]:>25} {r[1]:>20} {r[2]:>7.2f} {r[3]:>+6.1f}% {r[4]:>6.1f}% {r[5]:>4.1f}%{mark}")

# ═══════════════════════════════════════════════════
# PART 4: STABILITY VERDICT
# ═══════════════════════════════════════════════════
print(f"\n\n{'='*120}")
print("  PART 4: STABILITY VERDICT")
print("="*120)

# Compute Sharpe range for each sweep
print(f"\n  Parameter sensitivity summary:")
print(f"  {'Parameter':<25} {'Sweep range':<20} {'Sharpe range':<20} {'Stable?':>8}")
print(f"  {'─'*25} {'─'*20} {'─'*20} {'─'*8}")

# Recompute for summary
params = [
    ("Exit 2Y3m", [0.20, 0.25, 0.30, 0.35, 0.40], lambda th: build_signal(idx, make_exit(th,3.0,2.30), make_reentry(-0.30,3.5), 42)),
    ("Exit CPI", [2.5, 2.75, 3.0, 3.25, 3.5], lambda th: build_signal(idx, make_exit(0.30,th,2.30), make_reentry(-0.30,3.5), 42)),
    ("Exit 5Y5Y", [2.15, 2.20, 2.25, 2.30, 2.35], lambda th: build_signal(idx, make_exit(0.30,3.0,th), make_reentry(-0.30,3.5), 42)),
    ("Re-entry R5Y", [-0.20, -0.25, -0.30, -0.35, -0.40], lambda th: build_signal(idx, make_exit(0.30,3.0,2.30), make_reentry(th,3.5), 42)),
    ("Re-entry CPI", [3.0, 3.25, 3.5, 3.75, 4.0], lambda th: build_signal(idx, make_exit(0.30,3.0,2.30), make_reentry(-0.30,th), 42)),
]

for name, thresholds, fn in params:
    sharpes = []
    for th in thresholds:
        sig = fn(th)
        sh, _, _, _ = run_bt(sig)
        sharpes.append(sh)
    rng = max(sharpes) - min(sharpes)
    stable = '✅ YES' if rng < 0.10 else '⚠️ NO'
    print(f"  {name:<25} {str(thresholds):<20} {min(sharpes):.2f}–{max(sharpes):.2f} (Δ{rng:.2f})  {stable}")

print(f"\n  SEP baseline: Sharpe = {sh_sep:.2f}")
print(f"\n  ROBUSTNESS v5 COMPLETE.")
