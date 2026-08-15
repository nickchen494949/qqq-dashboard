#!/usr/bin/env python3
"""
Enhanced SEP replacement: add policy path pricing + credit confirmation.
Priority 1: Fed funds futures proxy (2Y-FFR spread = market-implied cuts/hikes)
Priority 2: FOMC-day 2Y reaction (captures forward guidance shock)
Priority 3: Credit spread filter (separates soft landing from recession)
Priority 4: Real yield signal (5Y TIPS)
Priority 5: Labor filter (initial claims)
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
qqq = gy('QQQ'); hyg = gy('HYG'); ief = gy('IEF')
tip = gy('TIP'); tlt = gy('TLT')

effr_raw = gf('EFFR')
dgs2 = gf('DGS2')          # 2Y Treasury
dgs5 = gf('DGS5')          # 5Y Treasury  
t5yifr = gf('T5YIFR')      # 5Y5Y breakeven
ffr_upper = gf('DFEDTARU')  # Fed funds target upper
cpilfe = gf('CPILFESL')     # Core CPI
walcl = gf('WALCL'); rrp = gf('RRPONTSYD'); tga = gf('WTREGEN')

# Additional data
dfii5 = gf('DFII5')         # 5Y TIPS real yield
dfii10 = gf('DFII10')       # 10Y TIPS real yield
icsa = gf('ICSA')           # Initial claims
baa10y = gf('BAA10Y')       # BAA-10Y spread (credit)
t10y2y = gf('T10Y2Y')       # 10Y-2Y curve

# FOMC meeting dates (for reaction signal)
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

idx = qqq.dropna().index; idx = idx[idx >= '2012-01-01']
qqq_a = qqq.reindex(idx)
hyg_a = hyg.reindex(idx).ffill(); ief_a = ief.reindex(idx).ffill()
tip_a = tip.reindex(idx).ffill(); tlt_a = tlt.reindex(idx).ffill()
effr_a = effr_raw.reindex(idx, method='ffill').ffill()/36500
dgs2_a = dgs2.reindex(idx, method='ffill').ffill()
dgs5_a = dgs5.reindex(idx, method='ffill').ffill()
t5yifr_a = t5yifr.reindex(idx, method='ffill').ffill()
ffr_a = ffr_upper.reindex(idx, method='ffill').ffill()
dfii5_a = dfii5.reindex(idx, method='ffill').ffill()
dfii10_a = dfii10.reindex(idx, method='ffill').ffill()
icsa_a = icsa.resample('D').ffill().reindex(idx, method='ffill').ffill()
baa10y_a = baa10y.reindex(idx, method='ffill').ffill()
t10y2y_a = t10y2y.reindex(idx, method='ffill').ffill()
walcl_a = walcl.resample('D').ffill().reindex(idx, method='ffill').ffill()
rrp_a = rrp.resample('D').ffill().reindex(idx, method='ffill').ffill()
tga_a = tga.resample('D').ffill().reindex(idx, method='ffill').ffill()

# Core CPI with 45-day lag
cpilfe_m = cpilfe.resample('ME').last().dropna()
core_cpi_3m = ((cpilfe_m / cpilfe_m.shift(3)).pow(4) - 1) * 100
core_cpi_3m_lagged = core_cpi_3m.copy()
core_cpi_3m_lagged.index += pd.Timedelta(days=45)
core_cpi_3m_d = core_cpi_3m_lagged.reindex(idx, method='ffill').ffill()

dr_qqq = qqq_a.pct_change()
z_credit = se.compute_credit_z(hyg_a, ief_a)
vol_z = se.compute_vol_z(dr_qqq)
inf_z = se.compute_inflation_z(tip_a, tlt_a)
nl_z = se.compute_nl_z(walcl_a, rrp_a, tga_a)

sep_raw = se.parse_sep_pdfs(os.path.join(PROJECT_DIR, 'fomc_sep'))
sep_signals = se.build_sep_signals(sep_raw)
sep_state, _ = se.build_sep_state(sep_signals, idx)

# ═══════════════════════════════════
# DERIVED SIGNALS
# ═══════════════════════════════════

# 1. Policy path proxy: 2Y - FFR spread
# Positive = market expects hikes, Negative = market expects cuts
policy_spread = dgs2_a - ffr_a
policy_spread_3m_chg = policy_spread - policy_spread.shift(63)

# 2. FOMC-day 2Y reaction
# After each FOMC, compute 2Y yield change (FOMC day to next day)
fomc_reaction = pd.Series(0.0, index=idx)
fomc_dates_ts = [pd.Timestamp(d) for d in FOMC_DATES]
for fd in fomc_dates_ts:
    # Find the FOMC day and next trading day in our index
    mask_before = idx[idx <= fd]
    mask_after = idx[idx > fd]
    if len(mask_before) < 2 or len(mask_after) < 1:
        continue
    day_of = mask_before[-1]
    day_before = mask_before[-2]
    # 2Y change on FOMC day (captures immediate reaction)
    if day_of in dgs2_a.index and day_before in dgs2_a.index:
        chg = dgs2_a.loc[day_of] - dgs2_a.loc[day_before]
        # Forward fill this reaction until next FOMC
        next_fomc = [f for f in fomc_dates_ts if f > fd]
        end = pd.Timestamp(next_fomc[0]) if next_fomc else idx[-1]
        fomc_reaction.loc[(idx >= day_of) & (idx < end)] = chg

# Cumulative FOMC reaction (rolling sum of last 3 FOMC reactions)
fomc_cum = pd.Series(0.0, index=idx)
recent_reactions = []
for fd in fomc_dates_ts:
    mask_before = idx[idx <= fd]
    if len(mask_before) < 2: continue
    day_of = mask_before[-1]
    day_before = mask_before[-2]
    if day_of in dgs2_a.index and day_before in dgs2_a.index:
        chg = dgs2_a.loc[day_of] - dgs2_a.loc[day_before]
        recent_reactions.append(chg)
        if len(recent_reactions) > 3:
            recent_reactions = recent_reactions[-3:]
        cum = sum(recent_reactions)
        next_fomc = [f for f in fomc_dates_ts if f > fd]
        end = pd.Timestamp(next_fomc[0]) if next_fomc else idx[-1]
        fomc_cum.loc[(idx >= day_of) & (idx < end)] = cum

# 3. Real yield momentum
real5y_3m_chg = dfii5_a - dfii5_a.shift(63)

# 4. Credit spread momentum  
baa_3m_chg = baa10y_a - baa10y_a.shift(63)

# 5. Initial claims Z-score
icsa_z = (icsa_a - icsa_a.rolling(252).mean()) / icsa_a.rolling(252).std()

print(f"  Data ready. {len(idx)} days.")

# ═══════════════════════════════════
# SIGNAL BUILDERS
# ═══════════════════════════════════

def build_F_base(idx):
    """Original F: 2Y mom + CPI + breakeven."""
    dgs2_chg = dgs2_a - dgs2_a.shift(63)
    state = 1; hold = 0; states = []
    for d in idx:
        chg = dgs2_chg.loc[d] if d in dgs2_chg.index and not np.isnan(dgs2_chg.loc[d]) else 0
        cpi = core_cpi_3m_d.loc[d] if d in core_cpi_3m_d.index and not np.isnan(core_cpi_3m_d.loc[d]) else 2.0
        be = t5yifr_a.loc[d] if d in t5yifr_a.index and not np.isnan(t5yifr_a.loc[d]) else 2.0
        if state == 1:
            if chg > 0.3 and cpi > 3.0 and be > 2.3:
                state = 0; hold = 0
        else:
            hold += 1
            if hold >= 42 and chg < -0.1 and cpi < 2.5:
                state = 1
        states.append(state)
    return pd.Series(states, index=idx)

def build_G(idx, use_policy=True, use_fomc=True, use_credit=True, 
            use_real=False, use_labor=False,
            # Exit params
            rate_enter=0.3, cpi_enter=3.0, be_enter=2.3,
            policy_enter=0.1, fomc_enter=0.1, credit_enter=0.3,
            real_enter=0.5,
            # Re-entry params  
            rate_exit=-0.1, cpi_exit=2.5,
            policy_exit=-0.2, fomc_exit=-0.1, credit_exit=0.0,
            real_exit=0.0, labor_exit=1.0,
            min_hold=42):
    """Enhanced F with policy path + credit + FOMC reaction + real yield + labor."""
    dgs2_chg = dgs2_a - dgs2_a.shift(63)
    state = 1; hold = 0; states = []
    for d in idx:
        chg = dgs2_chg.loc[d] if d in dgs2_chg.index and not np.isnan(dgs2_chg.loc[d]) else 0
        cpi = core_cpi_3m_d.loc[d] if d in core_cpi_3m_d.index and not np.isnan(core_cpi_3m_d.loc[d]) else 2.0
        be = t5yifr_a.loc[d] if d in t5yifr_a.index and not np.isnan(t5yifr_a.loc[d]) else 2.0
        ps = policy_spread.loc[d] if d in policy_spread.index and not np.isnan(policy_spread.loc[d]) else 0
        fc = fomc_cum.loc[d] if d in fomc_cum.index else 0
        cr = baa_3m_chg.loc[d] if d in baa_3m_chg.index and not np.isnan(baa_3m_chg.loc[d]) else 0
        ry = real5y_3m_chg.loc[d] if d in real5y_3m_chg.index and not np.isnan(real5y_3m_chg.loc[d]) else 0
        lb = icsa_z.loc[d] if d in icsa_z.index and not np.isnan(icsa_z.loc[d]) else 0
        
        if state == 1:
            # EXIT: base conditions + additional filters
            exit_cond = chg > rate_enter and cpi > cpi_enter and be > be_enter
            if use_policy: exit_cond = exit_cond and ps > policy_enter
            if use_fomc: exit_cond = exit_cond and fc > fomc_enter
            if use_credit: exit_cond = exit_cond or (cr > credit_enter and cpi > cpi_enter)
            if use_real: exit_cond = exit_cond or (ry > real_enter and cpi > cpi_enter)
            if exit_cond:
                state = 0; hold = 0
        else:
            hold += 1
            # RE-ENTRY: base + additional must confirm safe
            reentry_cond = hold >= min_hold and chg < rate_exit and cpi < cpi_exit
            if use_policy: reentry_cond = reentry_cond and ps < policy_exit
            if use_fomc: reentry_cond = reentry_cond and fc < fomc_exit
            if use_credit: reentry_cond = reentry_cond and cr < credit_exit
            if use_real: reentry_cond = reentry_cond and ry < real_exit
            if use_labor: reentry_cond = reentry_cond and lb < labor_exit
            if reentry_cond:
                state = 1
        states.append(state)
    return pd.Series(states, index=idx)

# ═══════════════════════════════════
# BACKTEST
# ═══════════════════════════════════
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
    out_pct = (signal==0).mean()*100
    return {'label':label,'cagr':cagr,'mdd':mdd,'sharpe':sh,'sortino':so,
            'out_pct':out_pct,'equity':eq}

# ═══════════════════════════════════
# RUN TESTS
# ═══════════════════════════════════
print("\nRunning backtests...\n")

results = []
results.append(run_bt(sep_state, '★ Real SEP'))
results.append(run_bt(build_F_base(idx), 'F: base (2Y+CPI+BE)'))

# G1: F + policy path (2Y-FFR spread)
print("  Testing G1: + policy path...")
for pe in [0.0, 0.1, 0.2]:
    for px in [-0.3, -0.2, -0.1]:
        sig = build_G(idx, use_policy=True, use_fomc=False, use_credit=False,
                       policy_enter=pe, policy_exit=px)
        results.append(run_bt(sig, f'G1: +policy pe={pe} px={px}'))

# G2: F + FOMC reaction
print("  Testing G2: + FOMC reaction...")
for fe in [0.05, 0.10, 0.15]:
    for fx in [-0.15, -0.10, -0.05]:
        sig = build_G(idx, use_policy=False, use_fomc=True, use_credit=False,
                       fomc_enter=fe, fomc_exit=fx)
        results.append(run_bt(sig, f'G2: +FOMC fe={fe} fx={fx}'))

# G3: F + credit spread filter
print("  Testing G3: + credit filter...")
for ce in [0.2, 0.3, 0.5]:
    for cx in [-0.1, 0.0, 0.1]:
        sig = build_G(idx, use_policy=False, use_fomc=False, use_credit=True,
                       credit_enter=ce, credit_exit=cx)
        results.append(run_bt(sig, f'G3: +credit ce={ce} cx={cx}'))

# G4: F + real yield
print("  Testing G4: + real yield...")
for re_val in [0.3, 0.5, 0.7]:
    for rx in [-0.2, 0.0]:
        sig = build_G(idx, use_policy=False, use_fomc=False, use_credit=False,
                       use_real=True, real_enter=re_val, real_exit=rx)
        results.append(run_bt(sig, f'G4: +real re={re_val} rx={rx}'))

# G5: F + labor filter (re-entry only)
print("  Testing G5: + labor filter...")
for lx in [0.5, 1.0, 1.5]:
    sig = build_G(idx, use_policy=False, use_fomc=False, use_credit=False,
                   use_labor=True, labor_exit=lx)
    results.append(run_bt(sig, f'G5: +labor lx={lx}'))

# G6: policy + credit combined
print("  Testing G6: policy + credit...")
for pe in [0.0, 0.1]:
    for px in [-0.2, -0.1]:
        for ce in [0.2, 0.3]:
            for cx in [-0.1, 0.0]:
                sig = build_G(idx, use_policy=True, use_fomc=False, use_credit=True,
                               policy_enter=pe, policy_exit=px,
                               credit_enter=ce, credit_exit=cx)
                results.append(run_bt(sig, f'G6: pol={pe}/{px} cr={ce}/{cx}'))

# G7: policy + FOMC + credit (full enhanced)
print("  Testing G7: full enhanced...")
for pe in [0.0, 0.1]:
    for fe in [0.05, 0.10]:
        for ce in [0.2, 0.3]:
            sig = build_G(idx, use_policy=True, use_fomc=True, use_credit=True,
                           policy_enter=pe, fomc_enter=fe, credit_enter=ce,
                           policy_exit=-0.2, fomc_exit=-0.1, credit_exit=0.0)
            results.append(run_bt(sig, f'G7: pol={pe} fc={fe} cr={ce}'))

# G8: full enhanced + real yield
print("  Testing G8: full + real yield...")
for re_val in [0.3, 0.5]:
    sig = build_G(idx, use_policy=True, use_fomc=True, use_credit=True,
                   use_real=True, real_enter=re_val, real_exit=0.0,
                   policy_enter=0.1, fomc_enter=0.1, credit_enter=0.3,
                   policy_exit=-0.2, fomc_exit=-0.1, credit_exit=0.0)
    results.append(run_bt(sig, f'G8: full+real re={re_val}'))

# ═══════════════════════════════════
# RESULTS
# ═══════════════════════════════════
print(f"\n{'='*110}")
print("  ENHANCED SEP REPLACEMENT — sorted by Sharpe")
print("="*110)

valid = [r for r in results if r['out_pct'] > 3]
valid.sort(key=lambda x: x['sharpe'], reverse=True)

sep_sh = [r for r in results if r['label'].startswith('★')][0]['sharpe']

print(f"\n  {'Rank':<5} {'Strategy':<45} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sort':>6} {'%OUT':>6}")
print(f"  {'─'*5} {'─'*45} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*6}")

for i, r in enumerate(valid[:30]):
    marker = ''
    if r['label'].startswith('★'): marker = ' ◄ SEP'
    elif r['label'].startswith('F:'): marker = ' ◄ base F'
    elif r['sharpe'] > sep_sh: marker = ' ✅ BEATS SEP'
    print(f"  {i+1:<5} {r['label']:<45} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>5.2f} {r['out_pct']:>5.1f}%{marker}")

# Best per enhancement
print(f"\n  ENHANCEMENT VALUE (best of each):")
f_sh = [r for r in results if r['label'].startswith('F:')][0]['sharpe']
for prefix, name in [('G1:', '+ policy path'), ('G2:', '+ FOMC reaction'),
                      ('G3:', '+ credit filter'), ('G4:', '+ real yield'),
                      ('G5:', '+ labor filter'), ('G6:', '+ policy+credit'),
                      ('G7:', '+ full enhanced'), ('G8:', '+ full+real')]:
    cat = [r for r in results if r['label'].startswith(prefix)]
    if cat:
        best = max(cat, key=lambda x: x['sharpe'])
        vs_f = best['sharpe'] - f_sh
        vs_sep = best['sharpe'] - sep_sh
        icon_f = '✅' if vs_f > 0 else '❌'
        icon_s = '✅' if vs_sep > 0 else '❌'
        print(f"    {name:<25} Sharpe={best['sharpe']:.2f}  vs F: {vs_f:+.2f}{icon_f}  vs SEP: {vs_sep:+.2f}{icon_s}")

# Year by year for SEP vs best enhanced vs base F
best_all = max([r for r in results if not r['label'].startswith('★')], key=lambda x: x['sharpe'])
sep_r = [r for r in results if r['label'].startswith('★')][0]
f_r = [r for r in results if r['label'].startswith('F:')][0]

print(f"\n  YEAR-BY-YEAR: SEP vs best enhanced vs base F")
print(f"  {'Year':>6} {'SEP':>9} {'Best':>9} {'F base':>9}   Best name: {best_all['label']}")
print(f"  {'─'*6} {'─'*9} {'─'*9} {'─'*9}")
for y in sorted(set(idx.year)):
    m = idx.year == y
    if m.sum() < 50: continue
    cs = (sep_r['equity'].loc[idx[m]].iloc[-1]/sep_r['equity'].loc[idx[m]].iloc[0]-1)*100
    cb = (best_all['equity'].loc[idx[m]].iloc[-1]/best_all['equity'].loc[idx[m]].iloc[0]-1)*100
    cf = (f_r['equity'].loc[idx[m]].iloc[-1]/f_r['equity'].loc[idx[m]].iloc[0]-1)*100
    d = cb - cs
    icon = '✅' if d > 3 else ('❌' if d < -3 else '  ')
    print(f"  {y:>6} {cs:>+8.1f}% {cb:>+8.1f}% {cf:>+8.1f}%  {d:>+5.1f}% {icon}")

# Final
print(f"\n{'='*110}")
print("  FINAL VERDICT")
print("="*110)
print(f"\n  Real SEP:       Sharpe {sep_r['sharpe']:.2f}")
print(f"  Base F:         Sharpe {f_r['sharpe']:.2f}  (gap to SEP: {f_r['sharpe']-sep_r['sharpe']:+.2f})")
print(f"  Best enhanced:  Sharpe {best_all['sharpe']:.2f}  (gap to SEP: {best_all['sharpe']-sep_r['sharpe']:+.2f})")
print(f"  Enhancement:    {best_all['label']}")

gap_closed = (best_all['sharpe'] - f_r['sharpe']) / (sep_r['sharpe'] - f_r['sharpe']) * 100 if sep_r['sharpe'] != f_r['sharpe'] else 0
print(f"\n  SEP gap closed: {gap_closed:.0f}%")
if gap_closed > 80:
    print(f"  → Enhanced signal closes >80% of SEP gap. Viable replacement.")
elif gap_closed > 50:
    print(f"  → Enhanced signal closes {gap_closed:.0f}% of gap. Better than F but still below SEP.")
else:
    print(f"  → Enhancement doesn't close much gap. SEP info remains unique.")
