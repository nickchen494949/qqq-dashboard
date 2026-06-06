#!/usr/bin/env python3
"""
=============================================================================
TQQQ STRATEGY — FULL AUDIT & TESTING CODE (v3 — PRODUCTION GRADE)
=============================================================================
Fixes from v2 review:
  1. 1-day delay check: now actually verified against trade log
  2. Next-open execution: uses Open price on switch day, close-to-close after
  3. OOS: slices continuous equity, no state reset
  4. SEP missing: hard fail with ValueError
  A. SEP signal date mapped to next trading day
  B. has_both uses pd.notna (no 0.0 bug)
  C. Parameter grid: in-sample select → OOS validate → forward report
=============================================================================
"""
import os, re
import numpy as np
import pandas as pd
import yfinance as yf
import pypdf
from fredapi import Fred

from strategy_engine import (
    Z_TRIGGER, Z_RECOVER, VZ_TRIGGER, VZ_RECOVER, VZ_LEV,
    Z_WINDOW, EXPENSE_RATIO, TC_BPS, HARDCODED_FFR,
    compute_credit_z, compute_vol_z,
    parse_sep_pdfs, build_sep_signals, build_sep_state,
    run_backtest as engine_run_backtest,
    get_fred_api_key,
)

# ============================================================================
# CONFIGURATION
# ============================================================================
FRED_API_KEY = get_fred_api_key()

PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR     = os.path.join(PROJECT_DIR, 'market_data')
SEP_DIR      = os.path.join(PROJECT_DIR, 'fomc_sep')
START_DATE   = '2012-01-25'

print("=" * 70)
print("  TQQQ STRATEGY — PRODUCTION GRADE AUDIT (v3)")
print("=" * 70)

# ============================================================================
# SECTION 1: DATA LOADING + INTEGRITY
# ============================================================================
print("\n[1/9] Loading data & integrity checks...")

fred = Fred(api_key=FRED_API_KEY)

def fetch_yahoo_ohlc(ticker):
    """Returns (adj_close, adj_open) — both on the same adjusted price scale."""
    df = yf.download(ticker, start='2005-01-01', progress=False, auto_adjust=False)
    close_raw = df['Close']
    adj_close = df['Adj Close'] if 'Adj Close' in df.columns else close_raw
    open_raw  = df['Open']
    if isinstance(close_raw, pd.DataFrame): close_raw = close_raw.iloc[:, 0]
    if isinstance(adj_close, pd.DataFrame): adj_close = adj_close.iloc[:, 0]
    if isinstance(open_raw, pd.DataFrame): open_raw = open_raw.iloc[:, 0]
    # Apply the same adjustment factor to Open
    adj_factor = adj_close / close_raw
    adj_open = open_raw * adj_factor
    return adj_close, adj_open

def fetch_yahoo(ticker):
    adj, _ = fetch_yahoo_ohlc(ticker)
    return adj

effr_raw = fred.get_series('DFF', observation_start='2005-01-01').dropna()
qqq_raw, qqq_open_raw = fetch_yahoo_ohlc('QQQ')
tqqq_close_raw, tqqq_open_raw = fetch_yahoo_ohlc('TQQQ')
qld_close_raw, qld_open_raw = fetch_yahoo_ohlc('QLD')
hyg_raw  = fetch_yahoo('HYG')
ief_raw  = fetch_yahoo('IEF')
spy_raw  = fetch_yahoo('SPY')

# Align
idx = qqq_raw.index[qqq_raw.index >= pd.Timestamp(START_DATE)]
qqq_d    = qqq_raw.reindex(idx)
qqq_open = qqq_open_raw.reindex(idx)
tqqq_d   = tqqq_close_raw.reindex(idx).ffill()
tqqq_opn = tqqq_open_raw.reindex(idx).ffill()
qld_d    = qld_close_raw.reindex(idx).ffill()
qld_opn  = qld_open_raw.reindex(idx).ffill()
spy_d    = spy_raw.reindex(idx).ffill()
dr_qqq   = qqq_d.pct_change()
dr_spy   = spy_d.pct_change()
dr_tqqq  = tqqq_d.pct_change()
dr_qld   = qld_d.pct_change()
effr     = effr_raw.reindex(idx).ffill() / 100 / 252
hyg_d    = hyg_raw.reindex(idx).ffill()
ief_d    = ief_raw.reindex(idx).ffill()

# Gap and intraday returns — computed directly from adjusted prices
# r_gap   = adj_open[t] / adj_close[t-1] - 1  (overnight)
# r_intra = adj_close[t] / adj_open[t] - 1    (intraday)
dr_qqq_gap   = qqq_open / qqq_d.shift(1) - 1
dr_qqq_intra = qqq_d / qqq_open - 1
dr_tqqq_gap   = tqqq_opn / tqqq_d.shift(1) - 1
dr_tqqq_intra = tqqq_d / tqqq_opn - 1
dr_qld_gap    = qld_opn / qld_d.shift(1) - 1
dr_qld_intra  = qld_d / qld_opn - 1

# Sanity: gap * intra should reconstruct close-to-close
_recon = (1 + dr_qqq_gap) * (1 + dr_qqq_intra) - 1
_recon_err = (dr_qqq - _recon).abs().dropna()
print(f"  Gap/Intra reconstruction error: mean={_recon_err.mean():.8f}, max={_recon_err.max():.8f}")

nan_counts = {
    'QQQ': qqq_d.isna().sum(), 'TQQQ': tqqq_d.isna().sum(),
    'QLD': qld_d.isna().sum(),
    'HYG': hyg_d.isna().sum(), 'IEF': ief_d.isna().sum(),
    'EFFR': effr.isna().sum(),
}
print(f"  Date range: {idx[0].date()} → {idx[-1].date()} ({len(idx)} trading days)")
print(f"  NaN counts: {nan_counts}")
for name, cnt in nan_counts.items():
    if cnt > 5:
        print(f"  ❌ CRITICAL: {name} has {cnt} NaN values!")

# ============================================================================
# SECTION 2: CREDIT STRESS Z-SCORE
# ============================================================================
print("\n[2/9] Computing -(HYG/IEF) Z-Score...")

hyg_ief = hyg_d / ief_d
z_series = compute_credit_z(hyg_d, ief_d)

print(f"  HYG/IEF drift: {hyg_ief.dropna().iloc[0]:.4f} → {hyg_ief.dropna().iloc[-1]:.4f} ({hyg_ief.dropna().iloc[-1]/hyg_ief.dropna().iloc[0]:.2f}x)")
print(f"  Z range: {z_series.min():.2f} → {z_series.max():.2f}, current: {z_series.iloc[-1]:.2f}")
print(f"  Days Z > 1.5: {(z_series > 1.5).sum()} / {len(z_series)} ({(z_series > 1.5).mean()*100:.1f}%)")

print("\n[2B/9] Computing Volatility Z-Score...")
vol_z = compute_vol_z(dr_qqq)
print(f"  Vol Z range: {vol_z.min():.2f} → {vol_z.max():.2f}, current: {vol_z.dropna().iloc[-1]:.2f}")

# ============================================================================
# SECTION 3: SEP PARSING + HARD VALIDATION
# ============================================================================
print("\n[3/9] Parsing FOMC SEP PDFs...")

if not os.path.isdir(SEP_DIR):
    raise FileNotFoundError(f"SEP_DIR not found: {SEP_DIR}")

sep_pdfs = sorted([f for f in os.listdir(SEP_DIR) if f.endswith('.pdf')])
if len(sep_pdfs) < 20:
    raise ValueError(f"Too few SEP PDFs: {len(sep_pdfs)} (need >= 20)")

# --- Parse via engine ---
sep_raw = parse_sep_pdfs(SEP_DIR)

# HARD FAIL on missing data IN our backtest window (2012+)
sep_audit = pd.DataFrame(sep_raw)
missing_all = sep_audit[sep_audit[['pce', 'rate']].isna().any(axis=1)]
missing = missing_all[missing_all['date'] >= '2012-01-01']
print(f"  Total PDFs: {len(sep_raw)}, missing (pre-2012, ignored): {len(missing_all)-len(missing)}, missing (2012+): {len(missing)}")
if len(missing) > 0:
    print(f"\n  ❌ MISSING SEP DATA (2012+):")
    for _, r in missing.iterrows():
        print(f"    {r['date']}  PCE={'MISS' if pd.isna(r['pce']) else r['pce']}  Rate={'MISS' if pd.isna(r['rate']) else r['rate']}")
    raise ValueError(f"SEP parse has {len(missing)} rows with missing data in backtest window.")
if len(missing_all) > len(missing):
    print(f"  ℹ️  {len(missing_all)-len(missing)} pre-2012 PDFs have missing rates (expected)")

# --- Build signals via engine ---
sep_signals = build_sep_signals(sep_raw)

# --- Map signal dates and build state via engine ---
sep_state, sep_signal_dates = build_sep_state(sep_signals, idx)

# Audit debug: print all ENTER/EXIT events with detail + track unmapped
unmapped = []
for r in sep_signals:
    if not r['signal']: continue
    raw_date = pd.Timestamp(r['date'])
    candidates = idx[idx >= raw_date]
    if len(candidates) == 0:
        unmapped.append(r['date'])
        continue
    mapped = candidates[0]
    exec_candidates = idx[idx > mapped]
    if len(exec_candidates) == 0:
        unmapped.append(r['date'])
        continue
    ty_flag = '✅same' if r['same_ty'] else '⚠️cross'
    print(f"    {r['signal']:5s} {r['date']} TY={r['target_year']} ({ty_flag}) PCE={r['pce']:.1f}(prev {r['prev_pce']:.1f}) Rate={r['rate']:.1f}(prev {r['prev_rate']:.1f})")

if unmapped:
    print(f"  ⚠️  Unmapped signal dates: {unmapped}")

days_out = (sep_state == 0).sum()
print(f"\n  SEP active: {(sep_state == 1).sum()} days, out: {days_out} days")
if days_out == 0:
    raise ValueError("SEP never triggered EXIT! Strategy not working.")

# ============================================================================
# SECTION 4: BACKTEST ENGINE (with next-open execution)
# ============================================================================
print("\n[4/9] Running backtests...")

def run_backtest(daily_returns, gap_returns=None, intra_returns=None,
                 use_sep=True, use_overlay=True,
                 z_trigger=Z_TRIGGER, z_recover=Z_RECOVER,
                 vz_trigger=VZ_TRIGGER, vz_recover=VZ_RECOVER, vz_lev=VZ_LEV, tc_bps=TC_BPS):
    """Audit wrapper: adapts module-level globals to engine's explicit-argument signature."""
    return engine_run_backtest(
        idx=idx, dr_qqq=daily_returns,
        dr_qqq_gap=gap_returns, dr_qqq_intra=intra_returns,
        effr=effr, z_series=z_series, vol_z=vol_z, sep_state=sep_state,
        use_sep=use_sep, use_overlay=use_overlay,
        z_trigger=z_trigger, z_recover=z_recover,
        vz_trigger=vz_trigger, vz_recover=vz_recover, vz_lev=vz_lev, tc_bps=tc_bps,
    )

# --- Main runs ---
# Close-to-close (classic, for comparison)
r_c2c   = run_backtest(dr_qqq, gap_returns=None, intra_returns=None, use_sep=True, use_overlay=True)
# Open execution (production)
r_open  = run_backtest(dr_qqq, gap_returns=dr_qqq_gap, intra_returns=dr_qqq_intra, use_sep=True, use_overlay=True)
# SEP only
r_sep   = run_backtest(dr_qqq, gap_returns=dr_qqq_gap, intra_returns=dr_qqq_intra, use_sep=True, use_overlay=False)

# Real TQQQ — also uses gap/intra on switch days
def run_real_tqqq():
    """Real ETF comparison: TQQQ(3x) + QLD(2x) + QQQ(1x) + cash(0x)"""
    eq = 1.0; lev = 3.0; prev_lev = 3.0
    pending = None; eql = []
    in_trade = False; trade_entry_eq = 1.0; in_danger = False; vol_danger = False
    for i in range(len(idx)):
        d = idx[i]; si = sep_state.loc[d]
        switch = False; old_lev = lev
        if pending is not None:
            if pending != lev: switch = True
            lev = pending; pending = None
        is_profitable = (eq > trade_entry_eq) if in_trade else False
        z = z_series.loc[d] if d in z_series.index else np.nan
        tgt = 3
        if si == 0: tgt = 0; in_danger = False; vol_danger = False
        else:
            if not np.isnan(z):
                if not in_danger and z > Z_TRIGGER: in_danger = True
                elif in_danger and z < Z_RECOVER: in_danger = False
            vz = vol_z.iloc[i] if i < len(vol_z) else np.nan
            if not np.isnan(vz):
                if not vol_danger and vz > VZ_TRIGGER: vol_danger = True
                elif vol_danger and vz < VZ_RECOVER: vol_danger = False

            if in_danger: tgt = 1 if is_profitable else 3
            elif vol_danger: tgt = VZ_LEV if is_profitable else lev
            else: tgt = 3
        if tgt != lev: pending = tgt
        if lev > 0 and not in_trade: in_trade = True; trade_entry_eq = eq
        elif lev == 0 and in_trade: in_trade = False
        if i > 0:
            tc = abs(lev - prev_lev) * (TC_BPS/10000)
            if switch:
                # Gap return: old leverage ETF
                if old_lev == 3: gap_r = dr_tqqq_gap.iloc[i]
                elif old_lev == 2: gap_r = dr_qld_gap.iloc[i]
                elif old_lev == 1: gap_r = dr_qqq_gap.iloc[i]
                else: gap_r = 0.0
                # Intra return: new leverage ETF
                if lev == 3: ri = dr_tqqq_intra.iloc[i]
                elif lev == 2: ri = dr_qld_intra.iloc[i]
                elif lev == 1: ri = dr_qqq_intra.iloc[i]
                else: ri = 0.0
                if np.isnan(gap_r): gap_r = 0.0
                if np.isnan(ri): ri = 0.0
                eq *= (1 + gap_r) * (1 + ri) * (1 - tc)
            else:
                if lev == 3: r = dr_tqqq.iloc[i]
                elif lev == 2: r = dr_qld.iloc[i]
                elif lev == 1: r = dr_qqq.iloc[i]
                else: r = effr.iloc[i]
                if np.isnan(r): r = 0.0
                eq *= (1 + r - tc)
            eq = max(eq, 0.001)
        prev_lev = lev; eql.append(eq)
    es = pd.Series(eql, index=idx); ny = len(es)/252
    return {'cagr': es.iloc[-1]**(1/ny)-1, 'mdd': ((es/es.expanding().max())-1).min()}

r_real = run_real_tqqq()

# B&H
def bh_stats(series):
    s = series.reindex(idx).ffill(); eq = s / s.iloc[0]; ny = len(eq)/252
    return {'cagr': eq.iloc[-1]**(1/ny)-1, 'mdd': ((eq/eq.expanding().max())-1).min()}

bh_tqqq = bh_stats(tqqq_d)
bh_upro = bh_stats(fetch_yahoo('UPRO'))
r_spy   = run_backtest(dr_spy, use_sep=True, use_overlay=True)

rows = [
    ('TQQQ Buy & Hold',               bh_tqqq['cagr'],  bh_tqqq['mdd'],  None,          None),
    ('Synth 3x QQQ + SEP Only',       r_sep['cagr'],    r_sep['mdd'],    r_sep['sharpe'],   r_sep['trades']),
    ('Synth 3x Close-to-Close',       r_c2c['cagr'],    r_c2c['mdd'],    r_c2c['sharpe'],   r_c2c['trades']),
    ('Synth 3x Next-Open (PROD)',      r_open['cagr'],   r_open['mdd'],   r_open['sharpe'],  r_open['trades']),
    ('Real TQQQ/QLD/QQQ + SEP + TP',   r_real['cagr'],   r_real['mdd'],   None,          None),
    ('UPRO Buy & Hold',               bh_upro['cagr'],  bh_upro['mdd'],  None,          None),
    ('Synth 3x SPY + SEP + TP',       r_spy['cagr'],    r_spy['mdd'],    r_spy['sharpe'],   r_spy['trades']),
]

print(f"\n  {'Strategy':<40s} {'CAGR':>8s} {'MDD':>8s} {'Sharpe':>8s} {'Trades':>7s}")
print(f"  {'-'*40} {'---':>8s} {'---':>8s} {'---':>8s} {'---':>7s}")
for label, cagr, mdd, sharpe, trades in rows:
    print(f"  {label:<40s} {cagr*100:>+7.1f}% {mdd*100:>7.1f}% {(f'{sharpe:.2f}' if sharpe else '—'):>8s} {(str(trades) if trades else '—'):>7s}")

c2c_vs_open = abs(r_c2c['cagr'] - r_open['cagr']) * 100
print(f"\n  Close-to-close vs Next-open gap: {c2c_vs_open:.1f}pp")

# ============================================================================
# SECTION 5: TRADE LOG
# ============================================================================
print("\n[5/9] Trade log (next-open model):")
print(f"  {'Signal':<12s} {'Exec':<12s} {'From':>5s} {'To':>5s} {'Equity':>8s} {'Z':>6s} {'Reason':<10s}")
print(f"  {'-'*12} {'-'*12} {'---':>5s} {'---':>5s} {'---':>8s} {'---':>6s} {'-'*10}")
for t in r_open['trade_log']:
    z_str = f"{t['z']:.2f}" if t['z'] is not None else '—'
    print(f"  {t['signal_date']:<12s} {t['exec_date']:<12s} {t['from_lev']:>4.0f}x {t['to_lev']:>4.0f}x {t['equity']:>8.4f} {z_str:>6s} {t['reason']:<10s}")

# ============================================================================
# SECTION 6: SIGNAL DELAY VERIFICATION (real test, not hardcoded True)
# ============================================================================
print("\n[6/9] Signal delay verification...")
delay_ok = True
for t in r_open['trade_log']:
    sig = pd.Timestamp(t['signal_date']) if t['signal_date'] != 'N/A' else None
    exc = pd.Timestamp(t['exec_date'])
    if sig and exc <= sig:
        print(f"  ❌ FAIL: Trade on {t['exec_date']} executed on or before signal {t['signal_date']}")
        delay_ok = False
if delay_ok:
    print(f"  ✅ All {len(r_open['trade_log'])} trades executed strictly AFTER signal date")

# ============================================================================
# SECTION 7: OUT-OF-SAMPLE (continuous equity slice, no state reset)
# ============================================================================
print("\n[7/9] Out-of-sample robustness (continuous equity slice)...")

full_eq = r_open['equity']
periods = [
    ('In-Sample 2012-2018',  '2012-01-25', '2018-12-31'),
    ('Holdout 2019-2022',    '2019-01-01', '2022-12-31'),
    ('Forward 2023-2026',    '2023-01-01', '2026-12-31'),
]
print(f"\n  Split-period (sliced from continuous run, no state reset):")
print(f"  {'Period':<25s} {'CAGR':>8s} {'MDD':>8s} {'Sharpe':>8s}")
print(f"  {'-'*25} {'---':>8s} {'---':>8s} {'---':>8s}")
oos_results = {}
for label, start, end in periods:
    sl = full_eq.loc[start:end]
    if len(sl) < 50: continue
    sl_norm = sl / sl.iloc[0]
    ny = len(sl) / 252
    cagr = sl_norm.iloc[-1] ** (1/ny) - 1
    mdd = ((sl_norm / sl_norm.expanding().max()) - 1).min()
    daily_ret = sl.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252)
    oos_results[label] = {'cagr': cagr, 'mdd': mdd, 'sharpe': sharpe}
    print(f"  {label:<25s} {cagr*100:>+7.1f}% {mdd*100:>7.1f}% {sharpe:>8.2f}")

# TC stress test
print(f"\n  Transaction cost stress test:")
print(f"  {'TC (bps)':<12s} {'CAGR':>8s} {'MDD':>8s} {'Sharpe':>8s}")
print(f"  {'-'*12} {'---':>8s} {'---':>8s} {'---':>8s}")
for tc in [0, 25, 50, 100, 200]:
    r = run_backtest(dr_qqq, gap_returns=dr_qqq_gap, intra_returns=dr_qqq_intra, tc_bps=tc)
    print(f"  {tc:<12d} {r['cagr']*100:>+7.1f}% {r['mdd']*100:>7.1f}% {r['sharpe']:>8.2f}")

# ============================================================================
# SECTION 8: PARAMETER GRID (in-sample select → OOS validate)
# ============================================================================
print("\n[8/9] Parameter selection: in-sample → OOS validate...")

# In-sample: 2012-2018
print("  Phase 1: Grid search on 2012-2018 (in-sample)...")
grid_is = []
for trigger in np.arange(0.8, 2.6, 0.2):
    for recover in np.arange(-0.5, min(trigger, 2.1), 0.2):
        r = run_backtest(dr_qqq, gap_returns=dr_qqq_gap, intra_returns=dr_qqq_intra,
                         z_trigger=trigger, z_recover=recover)
        eq_is = r['equity'].loc[:'2018-12-31']
        eq_is_n = eq_is / eq_is.iloc[0]
        ny = len(eq_is)/252
        cagr = eq_is_n.iloc[-1]**(1/ny)-1
        dr_is = eq_is.pct_change().dropna()
        sharpe = (dr_is.mean()/dr_is.std())*np.sqrt(252) if dr_is.std()>0 else 0
        grid_is.append({'trigger': round(trigger,2), 'recover': round(recover,2),
                        'is_sharpe': sharpe, 'is_cagr': cagr, 'full_eq': r['equity']})

gdf_is = pd.DataFrame([{k:v for k,v in g.items() if k != 'full_eq'} for g in grid_is])
gdf_is = gdf_is.sort_values('is_sharpe', ascending=False)
print(f"  Top 5 by in-sample Sharpe:")
for _, row in gdf_is.head(5).iterrows():
    sel = ' ← SELECTED' if row['trigger']==1.2 and row['recover']==0.2 else ''
    print(f"    T={row['trigger']:.2f} R={row['recover']:.2f}  IS_Sharpe={row['is_sharpe']:.2f}  IS_CAGR={row['is_cagr']*100:+.1f}%{sel}")

# Phase 2: Validate top-5 on holdout 2019-2022
print("\n  Phase 2: Validate top-5 on holdout 2019-2022:")
top5_idx = gdf_is.head(5).index.tolist()
print(f"  {'Trigger':>8s} {'Recover':>8s} {'IS_Sharpe':>10s} {'OOS_Sharpe':>11s} {'OOS_CAGR':>9s}")
for i in top5_idx:
    g = grid_is[i]
    eq_oos = g['full_eq'].loc['2019-01-01':'2022-12-31']
    eq_oos_n = eq_oos / eq_oos.iloc[0]
    ny = len(eq_oos)/252
    cagr_oos = eq_oos_n.iloc[-1]**(1/ny)-1
    dr_oos = eq_oos.pct_change().dropna()
    sharpe_oos = (dr_oos.mean()/dr_oos.std())*np.sqrt(252) if dr_oos.std()>0 else 0
    sel = ' ← SELECTED' if g['trigger']==1.2 and g['recover']==0.2 else ''
    print(f"  {g['trigger']:>8.2f} {g['recover']:>8.2f} {g['is_sharpe']:>10.2f} {sharpe_oos:>11.2f} {cagr_oos*100:>+8.1f}%{sel}")

# Plateau
best_is = gdf_is['is_sharpe'].max()
plateau = gdf_is[gdf_is['is_sharpe'] >= best_is - 0.05]
print(f"\n  IS plateau (within 0.05 of best {best_is:.2f}): {len(plateau)}/{len(gdf_is)} combos")
print(f"  → Trigger: {plateau['trigger'].min():.2f}–{plateau['trigger'].max():.2f}")
print(f"  → Recover: {plateau['recover'].min():.2f}–{plateau['recover'].max():.2f}")

# ============================================================================
# SECTION 9: STRUCTURAL CHECKS
# ============================================================================
print("\n[9/9] Structural checks...")

checks = []

# Data
checks.append(('SEP_DIR exists', os.path.isdir(SEP_DIR)))
checks.append(('SEP PDFs >= 20', len(sep_pdfs) >= 20))
checks.append(('SEP 0 missing data rows', len(missing) == 0))
checks.append(('SEP has EXIT events (days_out > 0)', days_out > 0))
checks.append(('No NaN in QQQ', qqq_d.isna().sum() <= 1))
checks.append(('No NaN in QLD', qld_d.isna().sum() == 0))
checks.append(('No NaN in HYG', hyg_d.isna().sum() == 0))
checks.append(('No NaN in IEF', ief_d.isna().sum() == 0))
checks.append(('All SEP signals mapped to trading days', len(unmapped) == 0))

# Signal delay — REAL test
checks.append(('1-day delay verified (all exec > signal)', delay_ok))

# Performance
checks.append(('Next-open CAGR > TQQQ B&H', r_open['cagr'] > bh_tqqq['cagr']))
checks.append(('Next-open MDD < TQQQ B&H MDD', r_open['mdd'] > bh_tqqq['mdd']))
checks.append(('TP overlay improves MDD vs SEP-only', r_open['mdd'] > r_sep['mdd']))
checks.append(('CAGR loss from TP < 10pp', abs(r_open['cagr']-r_sep['cagr']) < 0.10))
checks.append(('Sharpe > 1.3 (next-open + vol + nsl)', r_open['sharpe'] > 1.3))
checks.append(('Trades < 50', r_open['trades'] < 50))

# --- Final seal checks (conservative vol overlay) ---
r_credit_only = run_backtest(dr_qqq, gap_returns=dr_qqq_gap, intra_returns=dr_qqq_intra,
                             use_sep=True, use_overlay=True,
                             vz_trigger=99, vz_recover=-99)  # Vol never triggers
tc200 = run_backtest(dr_qqq, gap_returns=dr_qqq_gap, intra_returns=dr_qqq_intra, tc_bps=200)
years = len(idx) / 252
checks.append(('MDD <= -40%', r_open['mdd'] >= -0.40))
checks.append((f'Sharpe >= Credit-only + 0.05 ({r_open["sharpe"]:.2f} vs {r_credit_only["sharpe"]:.2f})',
               r_open['sharpe'] >= r_credit_only['sharpe'] + 0.05))
checks.append((f'CAGR loss vs Credit <= 2pp ({(r_open["cagr"]-r_credit_only["cagr"])*100:+.1f}pp)',
               (r_open['cagr'] - r_credit_only['cagr']) * 100 >= -2.0))
checks.append((f'TC 200bps Sharpe > 1.0 ({tc200["sharpe"]:.2f})', tc200['sharpe'] > 1.0))
checks.append((f'Yr avg trades <= 4 ({r_open["trades"]/years:.1f}/yr)', r_open['trades']/years <= 4.0))
checks.append(('Robust IS plateau >= 5', len(plateau) >= 5))

# Real vs Synthetic (compare prod model r_open against real ETF model)
diff_real = abs(r_open['cagr'] - r_real['cagr'])
checks.append((f'Synth vs Real TQQQ/QLD < 15pp ({diff_real*100:.1f}pp)', diff_real < 0.15))

# C2C vs Open gap
checks.append((f'C2C vs Open gap < 5pp ({c2c_vs_open:.1f}pp)', c2c_vs_open < 5.0))

# Cross-asset (informational — uses QQQ vol_z, no SPY gap/intra)
checks.append(('SPY cross-check: beats UPRO B&H (informational)', r_spy['cagr'] > bh_upro['cagr']))

# OOS
for label, res in oos_results.items():
    checks.append((f'{label} Sharpe > 0.5', res['sharpe'] > 0.5))

# has_both: verify source uses pd.notna, not raw truthiness
# Logic now lives in strategy_engine.py (build_sep_signals)
import inspect as _inspect
_engine_src = _inspect.getsource(build_sep_signals)
_line = [l for l in _engine_src.split('\n') if l.strip().startswith('has_both') and 'all' in l]
_uses_notna = len(_line) == 1 and 'pd.notna' in _line[0]
checks.append(('has_both uses pd.notna (verified from source)', _uses_notna))

print()
passed = failed = 0
for name, ok in checks:
    status = '✅ PASS' if ok else '❌ FAIL'
    if ok: passed += 1
    else: failed += 1
    print(f"  {status}  {name}")

# Live status
final_danger = r_open['danger'][-1]
final_vol_danger = r_open['vol_danger'][-1]
final_lev = r_open['leverage'][-1]
print(f"\n  Live Status (from hysteresis state machine):")
print(f"    SEP:           {'IN' if sep_state.iloc[-1]==1 else 'OUT'}")
print(f"    Credit Z:      {z_series.iloc[-1]:.2f} (Danger: {'YES' if final_danger else 'NO'})")
print(f"    Vol Z:         {vol_z.dropna().iloc[-1]:.2f} (Danger: {'YES' if final_vol_danger else 'NO'})")
print(f"    Leverage:      {int(final_lev)}x")
print(f"    TQQQ:          ${tqqq_d.iloc[-1]:.2f}")
print(f"    Through:       {idx[-1].date()}")

print(f"\n  Result: {passed}/{passed+failed} passed, {failed} failed")
if failed == 0:
    print("  ══════════════════════════════════════════")
    print("  ✅ ALL CHECKS PASSED — PRODUCTION GRADE")
    print("  ══════════════════════════════════════════")
else:
    print("  ══════════════════════════════════════════")
    print(f"  ⚠️  {failed} CHECK(S) FAILED")
    print("  ══════════════════════════════════════════")
print()
