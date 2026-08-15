#!/usr/bin/env python3
"""
SEP deep dive: Exit vs Re-entry, exposure diff, hybrid strategy.
Addresses: publication lag, look-ahead check, regime decomposition.
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
print("Loading...")
qqq = gy('QQQ'); hyg = gy('HYG'); ief = gy('IEF')
tip = gy('TIP'); tlt = gy('TLT')
effr_raw = gf('EFFR'); dgs2 = gf('DGS2')
t5yifr = gf('T5YIFR'); cpilfe = gf('CPILFESL')
walcl = gf('WALCL'); rrp = gf('RRPONTSYD'); tga = gf('WTREGEN')

idx = qqq.dropna().index; idx = idx[idx >= '2012-01-01']
qqq_a = qqq.reindex(idx)
hyg_a = hyg.reindex(idx).ffill(); ief_a = ief.reindex(idx).ffill()
tip_a = tip.reindex(idx).ffill(); tlt_a = tlt.reindex(idx).ffill()
effr_a = effr_raw.reindex(idx, method='ffill').ffill()/36500
dgs2_a = dgs2.reindex(idx, method='ffill').ffill()
t5yifr_a = t5yifr.reindex(idx, method='ffill').ffill()
walcl_a = walcl.resample('D').ffill().reindex(idx, method='ffill').ffill()
rrp_a = rrp.resample('D').ffill().reindex(idx, method='ffill').ffill()
tga_a = tga.resample('D').ffill().reindex(idx, method='ffill').ffill()

# Core CPI: shift by 1 month to simulate publication lag (~15th of next month)
cpilfe_m = cpilfe.resample('ME').last().dropna()
core_cpi_3m = ((cpilfe_m / cpilfe_m.shift(3)).pow(4) - 1) * 100
# Lag by 45 days: Jan data available ~Feb 15
core_cpi_3m_lagged = core_cpi_3m.copy()
core_cpi_3m_lagged.index = core_cpi_3m_lagged.index + pd.Timedelta(days=45)
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
# BUILD F SIGNAL (best replacement, with CPI lag fix)
# ═══════════════════════════════════
def build_F(idx, rate_chg_enter=0.3, cpi_enter=3.0, be_enter=2.3,
            rate_chg_exit=-0.1, cpi_exit=2.5, min_hold=42):
    dgs2_chg = dgs2_a - dgs2_a.shift(63)
    state = 1; hold = 0; states = []
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

f_state = build_F(idx)

print(f"  SEP OUT: {(sep_state==0).sum()} days ({(sep_state==0).mean()*100:.1f}%)")
print(f"  F   OUT: {(f_state==0).sum()} days ({(f_state==0).mean()*100:.1f}%)")

# ═══════════════════════════════════
# TEST 1: EXIT vs RE-ENTRY decomposition
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  TEST 1: EXIT vs RE-ENTRY — who is better at what?")
print("="*100)

def find_transitions(signal):
    """Find exit and re-entry dates."""
    exits = []; entries = []
    arr = signal.values
    for i in range(1, len(arr)):
        if arr[i] == 0 and arr[i-1] == 1:  # exit
            exits.append(signal.index[i])
        elif arr[i] == 1 and arr[i-1] == 0:  # entry
            entries.append(signal.index[i])
    return exits, entries

sep_exits, sep_entries = find_transitions(sep_state)
f_exits, f_entries = find_transitions(f_state)

print(f"\n  A. EXIT TIMING (going defensive)")
print(f"  {'Signal':<8} {'Date':<14} {'TQQQ next 1m':>14} {'TQQQ next 3m':>14} {'MDD next 3m':>14}")
print(f"  {'─'*8} {'─'*14} {'─'*14} {'─'*14} {'─'*14}")

for label, exits in [('SEP', sep_exits), ('F', f_exits)]:
    for dt in exits:
        # forward returns
        fut_1m = qqq_a.loc[qqq_a.index > dt].head(21)
        fut_3m = qqq_a.loc[qqq_a.index > dt].head(63)
        if len(fut_1m) < 10: continue
        ret_1m = (fut_1m.iloc[-1] / qqq_a.loc[dt] - 1) * 100 if dt in qqq_a.index else 0
        ret_3m = (fut_3m.iloc[-1] / qqq_a.loc[dt] - 1) * 100 if len(fut_3m) > 10 and dt in qqq_a.index else 0
        mdd_3m = ((fut_3m / fut_3m.cummax()) - 1).min() * 100 if len(fut_3m) > 10 else 0
        good = '✅' if mdd_3m < -5 else '❌ false'
        print(f"  {label:<8} {dt.strftime('%Y-%m-%d'):<14} {ret_1m:>+13.1f}% {ret_3m:>+13.1f}% {mdd_3m:>13.1f}% {good}")

# Aggregate exit quality
print(f"\n  EXIT QUALITY SUMMARY:")
for label, exits in [('SEP', sep_exits), ('F', f_exits)]:
    good = 0; total = 0
    avg_mdd = []
    for dt in exits:
        fut_3m = qqq_a.loc[qqq_a.index > dt].head(63)
        if len(fut_3m) < 10: continue
        total += 1
        mdd = ((fut_3m / fut_3m.cummax()) - 1).min() * 100
        avg_mdd.append(mdd)
        if mdd < -5: good += 1
    print(f"    {label}: {good}/{total} correct exits ({good/total*100:.0f}%), avg 3m MDD = {np.mean(avg_mdd):.1f}%")

print(f"\n  B. RE-ENTRY TIMING (going back to 3x)")
print(f"  {'Signal':<8} {'Date':<14} {'TQQQ next 1m':>14} {'TQQQ next 3m':>14} {'MDD next 3m':>14}")
print(f"  {'─'*8} {'─'*14} {'─'*14} {'─'*14} {'─'*14}")

for label, entries in [('SEP', sep_entries), ('F', f_entries)]:
    for dt in entries:
        fut_1m = qqq_a.loc[qqq_a.index > dt].head(21)
        fut_3m = qqq_a.loc[qqq_a.index > dt].head(63)
        if len(fut_1m) < 10: continue
        ret_1m = (fut_1m.iloc[-1] / qqq_a.loc[dt] - 1) * 100 if dt in qqq_a.index else 0
        ret_3m = (fut_3m.iloc[-1] / qqq_a.loc[dt] - 1) * 100 if len(fut_3m) > 10 and dt in qqq_a.index else 0
        mdd_3m = ((fut_3m / fut_3m.cummax()) - 1).min() * 100 if len(fut_3m) > 10 else 0
        good = '✅' if ret_3m > 0 else '❌ bad'
        print(f"  {label:<8} {dt.strftime('%Y-%m-%d'):<14} {ret_1m:>+13.1f}% {ret_3m:>+13.1f}% {mdd_3m:>13.1f}% {good}")

print(f"\n  RE-ENTRY QUALITY SUMMARY:")
for label, entries in [('SEP', sep_entries), ('F', f_entries)]:
    good = 0; total = 0; avg_ret = []; bad_dd = 0
    for dt in entries:
        fut_3m = qqq_a.loc[qqq_a.index > dt].head(63)
        if len(fut_3m) < 10: continue
        total += 1
        ret = (fut_3m.iloc[-1] / qqq_a.loc[dt] - 1) * 100
        mdd = ((fut_3m / fut_3m.cummax()) - 1).min() * 100
        avg_ret.append(ret)
        if ret > 0: good += 1
        if mdd < -10: bad_dd += 1
    print(f"    {label}: {good}/{total} profitable re-entries ({good/total*100:.0f}%), avg 3m ret = {np.mean(avg_ret):+.1f}%, bad DD = {bad_dd}/{total}")

# ═══════════════════════════════════
# TEST 2: EXPOSURE DIFFERENCE
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  TEST 2: EXPOSURE DIFFERENCE (SEP - F)")
print("="*100)

# Where they disagree
sep_in_f_out = (sep_state == 1) & (f_state == 0)  # SEP risk-on, F risk-off
sep_out_f_in = (sep_state == 0) & (f_state == 1)  # SEP risk-off, F risk-on
agree = (sep_state == f_state)

print(f"\n  Agreement: {agree.mean()*100:.1f}% of days")
print(f"  SEP=IN, F=OUT: {sep_in_f_out.sum()} days ({sep_in_f_out.mean()*100:.1f}%)")
print(f"  SEP=OUT, F=IN: {sep_out_f_in.sum()} days ({sep_out_f_in.mean()*100:.1f}%)")

# When they disagree, what happened?
print(f"\n  DISAGREEMENT PERIODS:")
print(f"  {'Period':<26} {'State':<16} {'Days':>5} {'QQQ ret':>8}  Verdict")
print(f"  {'─'*26} {'─'*16} {'─'*5} {'─'*8}  {'─'*20}")

# Find contiguous disagreement blocks
diff = (sep_state != f_state).astype(int)
blocks = []
in_block = False
for i in range(len(diff)):
    if diff.iloc[i] == 1 and not in_block:
        block_start = i; in_block = True
    elif diff.iloc[i] == 0 and in_block:
        blocks.append((block_start, i-1)); in_block = False
if in_block: blocks.append((block_start, len(diff)-1))

for bs, be in blocks:
    dt_s = idx[bs]; dt_e = idx[be]; days = be - bs + 1
    sep_v = 'SEP=IN' if sep_state.iloc[bs] == 1 else 'SEP=OUT'
    f_v = 'F=IN' if f_state.iloc[bs] == 1 else 'F=OUT'
    state_str = f"{sep_v}, {f_v}"
    qqq_ret = (qqq_a.iloc[be] / qqq_a.iloc[bs] - 1) * 100
    
    # Who was right?
    if sep_state.iloc[bs] == 1 and f_state.iloc[bs] == 0:
        verdict = '✅ SEP right' if qqq_ret > 0 else '✅ F right'
    else:
        verdict = '✅ F right' if qqq_ret > 0 else '✅ SEP right'
    
    print(f"  {dt_s.strftime('%Y-%m-%d')} → {dt_e.strftime('%Y-%m-%d'):<12} {state_str:<16} {days:>5} {qqq_ret:>+7.1f}%  {verdict}")

# ═══════════════════════════════════
# TEST 3: HYBRID STRATEGY
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  TEST 3: HYBRID STRATEGIES")
print("="*100)

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

# Hybrid 1: SEP exit + F re-entry filter
# Use SEP for exit, but need both SEP=IN and F=IN to re-enter
hybrid1 = pd.Series(1, index=idx)
state = 1
for i in range(len(idx)):
    sep_v = sep_state.iloc[i]
    f_v = f_state.iloc[i]
    if state == 1:
        if sep_v == 0:  # SEP says exit → exit
            state = 0
    else:
        if sep_v == 1 and f_v == 1:  # both must agree to re-enter
            state = 1
    hybrid1.iloc[i] = state

# Hybrid 2: Either triggers exit, both must clear for re-entry
hybrid2 = pd.Series(1, index=idx)
state = 1
for i in range(len(idx)):
    sep_v = sep_state.iloc[i]; f_v = f_state.iloc[i]
    if state == 1:
        if sep_v == 0 or f_v == 0:  # either triggers exit
            state = 0
    else:
        if sep_v == 1 and f_v == 1:  # both must clear
            state = 1
    hybrid2.iloc[i] = state

# Hybrid 3: SEP primary, F only delays re-entry by requiring confirmation
# After SEP says ENTER, wait until F also says IN
hybrid3 = pd.Series(1, index=idx)
state = 1; sep_wants_in = True
for i in range(len(idx)):
    sep_v = sep_state.iloc[i]; f_v = f_state.iloc[i]
    if state == 1:
        if sep_v == 0:
            state = 0; sep_wants_in = False
    else:
        if sep_v == 1:
            sep_wants_in = True
        if sep_wants_in and f_v == 1:
            state = 1
    hybrid3.iloc[i] = state

# Hybrid 4: F primary (fallback mode — no SEP available)
# This is just F alone
hybrid4 = f_state.copy()

results = []
results.append(run_bt(sep_state, '★ SEP only'))
results.append(run_bt(f_state, 'F only (fallback)'))
results.append(run_bt(hybrid1, 'H1: SEP exit, both re-enter'))
results.append(run_bt(hybrid2, 'H2: either exit, both re-enter'))
results.append(run_bt(hybrid3, 'H3: SEP primary, F delays re-entry'))
results.append(run_bt(hybrid4, 'H4: F only (no SEP)'))

# Always in
always_in = pd.Series(1, index=idx)
results.append(run_bt(always_in, 'No filter (always IN)'))

print(f"\n  {'Strategy':<40} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Sort':>6} {'%OUT':>6}")
print(f"  {'─'*40} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*6}")
for r in sorted(results, key=lambda x: x['sharpe'], reverse=True):
    marker = ' ◄' if r['label'].startswith('★') else ''
    print(f"  {r['label']:<40} {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>5.2f} {r['out_pct']:>5.1f}%{marker}")

# Year by year for top strategies
print(f"\n  YEAR-BY-YEAR:")
top = sorted(results, key=lambda x: x['sharpe'], reverse=True)[:5]
print(f"  {'Year':>6}", end='')
for t in top: print(f"  {t['label'][:18]:>18}", end='')
print()
print(f"  {'─'*6}", end='')
for _ in top: print(f"  {'─'*18}", end='')
print()

for y in sorted(set(idx.year)):
    m = idx.year == y
    if m.sum() < 50: continue
    print(f"  {y:>6}", end='')
    for t in top:
        e = t['equity'].loc[idx[m]]
        c = (e.iloc[-1]/e.iloc[0]-1)*100
        print(f"  {c:>+17.1f}%", end='')
    print()

# ═══════════════════════════════════
# FINAL VERDICT
# ═══════════════════════════════════
print(f"\n{'='*100}")
print("  FINAL VERDICT")
print("="*100)

sep_r = [r for r in results if r['label'].startswith('★')][0]
best_hybrid = max([r for r in results if r['label'].startswith('H')], key=lambda x: x['sharpe'])
f_r = [r for r in results if r['label'] == 'F only (fallback)'][0]

print(f"""
  SEP only:     Sharpe {sep_r['sharpe']:.2f}, CAGR {sep_r['cagr']:+.1f}%, MDD {sep_r['mdd']:.1f}%
  Best hybrid:  Sharpe {best_hybrid['sharpe']:.2f}, CAGR {best_hybrid['cagr']:+.1f}%, MDD {best_hybrid['mdd']:.1f}%  ({best_hybrid['label']})
  F fallback:   Sharpe {f_r['sharpe']:.2f}, CAGR {f_r['cagr']:+.1f}%, MDD {f_r['mdd']:.1f}%

  SEP advantage over F:     Sharpe {sep_r['sharpe']-f_r['sharpe']:+.2f}
  Hybrid advantage over F:  Sharpe {best_hybrid['sharpe']-f_r['sharpe']:+.2f}
""")

if best_hybrid['sharpe'] > sep_r['sharpe']:
    print(f"  → HYBRID beats pure SEP. Use {best_hybrid['label']}.")
elif best_hybrid['sharpe'] > f_r['sharpe']:
    print(f"  → HYBRID is between SEP and F. Useful as insurance if SEP quality degrades.")
else:
    print(f"  → SEP alone is still best. Hybrids add no value.")
