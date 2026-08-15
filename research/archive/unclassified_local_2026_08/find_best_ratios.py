#!/usr/bin/env python3
"""
Robust search: find best params by Sortino, Calmar, Omega
Same methodology: IS selection → OOS/FWD validation → audit filters
"""
import os, sys, time
import numpy as np
import pandas as pd
import yfinance as yf
from fredapi import Fred
from itertools import product

from strategy_engine import (
    Z_TRIGGER, Z_RECOVER, VZ_TRIGGER, VZ_RECOVER, VZ_LEV,
    INF_TRIGGER, INF_RECOVER, INF_LEV,
    Z_WINDOW, EXPENSE_RATIO, TC_BPS,
    compute_credit_z, compute_vol_z, compute_inflation_z,
    parse_sep_pdfs, build_sep_signals, build_sep_state,
    get_fred_api_key,
)

FRED_API_KEY = get_fred_api_key()
PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP_DIR      = os.path.join(PROJECT_DIR, 'fomc_sep')
START_DATE   = '2012-01-25'

print("=" * 80)
print("  ROBUST SEARCH: SORTINO / CALMAR / OMEGA")
print("=" * 80)
sys.stdout.flush()

# ── Data Loading ──
print("\n[1] Loading data...")
sys.stdout.flush()
fred = Fred(api_key=FRED_API_KEY)

def fetch_yahoo_ohlc(ticker):
    df = yf.download(ticker, start='2005-01-01', progress=False, auto_adjust=False)
    close_raw = df['Close']
    adj_close = df['Adj Close'] if 'Adj Close' in df.columns else close_raw
    open_raw  = df['Open']
    if isinstance(close_raw, pd.DataFrame): close_raw = close_raw.iloc[:, 0]
    if isinstance(adj_close, pd.DataFrame): adj_close = adj_close.iloc[:, 0]
    if isinstance(open_raw, pd.DataFrame): open_raw = open_raw.iloc[:, 0]
    adj_factor = adj_close / close_raw
    adj_open = open_raw * adj_factor
    return adj_close, adj_open

def fetch_yahoo(ticker):
    adj, _ = fetch_yahoo_ohlc(ticker)
    return adj

effr_raw = fred.get_series('DFF', observation_start='2005-01-01').dropna()
qqq_raw, qqq_open_raw = fetch_yahoo_ohlc('QQQ')
hyg_raw  = fetch_yahoo('HYG')
ief_raw  = fetch_yahoo('IEF')
tip_raw  = fetch_yahoo('TIP')
tlt_raw  = fetch_yahoo('TLT')

idx = qqq_raw.index[qqq_raw.index >= pd.Timestamp(START_DATE)]
qqq_d    = qqq_raw.reindex(idx)
qqq_open = qqq_open_raw.reindex(idx)
dr_qqq   = qqq_d.pct_change()
effr     = effr_raw.reindex(idx).ffill() / 100 / 252

dr_qqq_gap_np   = (qqq_open / qqq_d.shift(1) - 1).values.astype(np.float64)
dr_qqq_intra_np = (qqq_d / qqq_open - 1).values.astype(np.float64)

full_idx = qqq_raw.dropna().index
hyg_full = hyg_raw.reindex(full_idx).ffill()
ief_full = ief_raw.reindex(full_idx).ffill()
tip_full = tip_raw.reindex(full_idx).ffill()
tlt_full = tlt_raw.reindex(full_idx).ffill()
dr_full  = qqq_raw.reindex(full_idx).pct_change()

z_series = compute_credit_z(hyg_full, ief_full).reindex(idx)
vol_z    = compute_vol_z(dr_full).reindex(idx)
inf_z    = compute_inflation_z(tip_full, tlt_full).reindex(idx)

sep_raw = parse_sep_pdfs(SEP_DIR)
sep_signals = build_sep_signals(sep_raw)
sep_state, _ = build_sep_state(sep_signals, idx)

N = len(idx)
dr_qqq_np = dr_qqq.values.astype(np.float64)
effr_np = effr.values.astype(np.float64)
z_np = z_series.values.astype(np.float64)
vol_z_np = vol_z.values.astype(np.float64)
inf_z_np = inf_z.values.astype(np.float64)
sep_np = sep_state.values.astype(np.float64)
EXPENSE_RATIO_DAILY = EXPENSE_RATIO / 252

# Period boundaries
IS_END   = '2018-12-31'
OOS_END  = '2022-12-31'
is_mask  = idx <= pd.Timestamp(IS_END)
oos_mask = (idx > pd.Timestamp(IS_END)) & (idx <= pd.Timestamp(OOS_END))
fwd_mask = idx > pd.Timestamp(OOS_END)

is_end_idx    = int(np.where(is_mask)[0][-1]) + 1
oos_start_idx = int(np.where(oos_mask)[0][0])
oos_end_idx   = int(np.where(oos_mask)[0][-1]) + 1
fwd_start_idx = int(np.where(fwd_mask)[0][0])

print(f"  Data: {idx[0].date()} → {idx[-1].date()} ({N} days)")
sys.stdout.flush()


def fast_backtest(zt, zr, vzt, vzr, vz_lev, inft, infr, inf_lev, tc_bps):
    eq = 1.0; lev = 3.0; prev_lev = 3.0
    pending = -1.0
    in_trade = False; trade_entry_eq = 1.0
    in_danger = False; vol_danger = False; inf_danger = False
    trades = 0
    eql = np.empty(N)

    for i in range(N):
        si = sep_np[i]
        switch_today = False
        prev_lev_for_gap = lev
        if pending >= 0:
            if pending != lev: switch_today = True
            lev = pending; pending = -1.0

        is_profitable = (eq > trade_entry_eq) if in_trade else False
        z = z_np[i]
        tgt = 3.0
        if si == 0:
            tgt = 0.0; in_danger = False; vol_danger = False; inf_danger = False
        else:
            if not np.isnan(z):
                if not in_danger and z > zt: in_danger = True
                elif in_danger and z < zr: in_danger = False
            iz = inf_z_np[i]
            if not np.isnan(iz):
                if not inf_danger and iz > inft: inf_danger = True
                elif inf_danger and iz < infr: inf_danger = False
            vz = vol_z_np[i]
            if not np.isnan(vz):
                if not vol_danger and vz > vzt: vol_danger = True
                elif vol_danger and vz < vzr: vol_danger = False
            if in_danger: tgt = 1.0 if is_profitable else 3.0
            elif inf_danger: tgt = inf_lev if is_profitable else lev
            elif vol_danger: tgt = vz_lev if is_profitable else lev
            else: tgt = 3.0

        if tgt != lev: pending = tgt
        if lev > 0 and not in_trade: in_trade = True; trade_entry_eq = eq
        elif lev == 0 and in_trade: in_trade = False
        if lev != prev_lev and lev > 0 and prev_lev > 0:
            if lev > prev_lev:
                trade_entry_eq = (trade_entry_eq * prev_lev + eq * (lev - prev_lev)) / lev
        if lev != prev_lev: trades += 1

        if i > 0:
            r_total = dr_qqq_np[i]
            if np.isnan(r_total): r_total = 0.0
            if switch_today:
                rg = dr_qqq_gap_np[i]; ri = dr_qqq_intra_np[i]
                if np.isnan(rg): rg = 0.0
                if np.isnan(ri): ri = 0.0
                r_applied = (1 + prev_lev_for_gap * rg) * (1 + lev * ri) - 1
            else:
                r_applied = lev * r_total
            borrow = max(0, lev - 1) * effr_np[i] if lev > 1 else 0
            fee = EXPENSE_RATIO_DAILY * min(lev / 3, 1) if lev > 1 else 0
            cy = effr_np[i] if lev == 0 else 0
            tc = abs(lev - prev_lev) * (tc_bps / 10000)
            eq *= (1 + r_applied - borrow - fee + cy - tc)
            if eq < 0.001: eq = 0.001
        prev_lev = lev; eql[i] = eq

    return eql, trades


def calc_metrics(eql, start, end):
    sl = eql[start:end]
    if len(sl) < 50:
        return {'sharpe': np.nan, 'sortino': np.nan, 'calmar': np.nan, 'omega': np.nan,
                'cagr': np.nan, 'mdd': np.nan}
    sl_norm = sl / sl[0]
    ny = len(sl) / 252
    cagr = sl_norm[-1] ** (1/ny) - 1
    running_max = np.maximum.accumulate(sl_norm)
    mdd = (sl_norm / running_max - 1).min()
    rets = np.diff(sl) / sl[:-1]
    
    mean_r = np.mean(rets)
    std_r = np.std(rets)
    sharpe = (mean_r / std_r) * np.sqrt(252) if std_r > 0 else 0

    downside = rets[rets < 0]
    down_std = np.sqrt(np.mean(downside**2)) if len(downside) > 0 else 1e-10
    sortino = (mean_r / down_std) * np.sqrt(252)

    calmar = cagr / abs(mdd) if mdd != 0 else 0

    gains = rets[rets > 0].sum()
    losses = abs(rets[rets < 0].sum())
    omega = gains / losses if losses > 0 else float('inf')

    return {'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar, 'omega': omega,
            'cagr': cagr, 'mdd': mdd}


# ── Grid Search ──
print("\n[2] Running grid search with all 4 ratios...")
sys.stdout.flush()

cr_triggers  = [0.8, 1.0, 1.2, 1.5, 1.8, 2.0]
cr_recovers  = [-0.5, 0.0, 0.2, 0.5, 0.7]
vol_triggers = [0.5, 1.0, 1.5, 1.8, 2.0]
vol_recovers = [-0.5, 0.0, 0.3, 0.5, 0.8]
inf_triggers = [1.5, 2.0, 2.5, 3.0, 3.5]
inf_recovers = [-0.5, 0.0, 0.3, 0.5, 1.0]

results = []
count = 0
t0 = time.time()

for zt, zr, vt, vr, it, ir in product(
    cr_triggers, cr_recovers, vol_triggers, vol_recovers, inf_triggers, inf_recovers
):
    if zt <= zr or vt <= vr or it <= ir:
        continue

    eql, trades = fast_backtest(zt, zr, vt, vr, VZ_LEV, it, ir, INF_LEV, TC_BPS)
    years = N / 252

    m_full = calc_metrics(eql, 0, N)
    m_is   = calc_metrics(eql, 0, is_end_idx)
    m_oos  = calc_metrics(eql, oos_start_idx, oos_end_idx)
    m_fwd  = calc_metrics(eql, fwd_start_idx, N)

    results.append({
        'zt': zt, 'zr': zr, 'vt': vt, 'vr': vr, 'it': it, 'ir': ir,
        'trades_yr': trades / years,
        # Full period
        **{f'full_{k}': v for k, v in m_full.items()},
        # IS
        **{f'is_{k}': v for k, v in m_is.items()},
        # OOS
        **{f'oos_{k}': v for k, v in m_oos.items()},
        # FWD
        **{f'fwd_{k}': v for k, v in m_fwd.items()},
    })

    count += 1
    if count % 2000 == 0:
        elapsed = time.time() - t0
        print(f"    {count} tested ({elapsed:.0f}s)")
        sys.stdout.flush()

elapsed = time.time() - t0
print(f"  Total: {count} combos in {elapsed:.1f}s")
sys.stdout.flush()

df = pd.DataFrame(results)

# Audit filters (applied on full period)
audit = df[
    (df['full_sharpe'] > 1.33) &
    (df['full_mdd'] >= -0.45) &
    (df['trades_yr'] <= 5.0) &
    (df['oos_sharpe'] > 0.5) &
    (df['fwd_sharpe'] > 0.5)
].copy()

print(f"\n  Audit pass: {len(audit)}/{len(df)}")

# ── Find best by each metric (IS selection) ──
metrics_to_optimize = ['sharpe', 'sortino', 'calmar', 'omega']

sealed_mask = (
    (df['zt'] == Z_TRIGGER) & (df['zr'] == Z_RECOVER) &
    (df['vt'] == VZ_TRIGGER) & (df['vr'] == VZ_RECOVER) &
    (df['it'] == INF_TRIGGER) & (df['ir'] == INF_RECOVER)
)
sealed = df[sealed_mask].iloc[0] if sealed_mask.any() else None

print(f"\n{'='*130}")
print(f"  BEST PARAMS BY EACH METRIC (IS-selected, audit-filtered)")
print(f"{'='*130}")

for metric in metrics_to_optimize:
    is_col = f'is_{metric}'
    full_col = f'full_{metric}'
    oos_col = f'oos_{metric}'
    fwd_col = f'fwd_{metric}'

    if len(audit) == 0:
        print(f"\n  ⚠️  No combos pass audit for {metric.upper()}")
        continue

    best = audit.loc[audit[is_col].idxmax()]
    
    print(f"\n  ┌─ BEST IS {metric.upper()}")
    print(f"  │  Params:  CrT={best['zt']:.1f} CrR={best['zr']:.1f} VT={best['vt']:.1f} VR={best['vr']:.1f} IT={best['it']:.1f} IR={best['ir']:.1f}")
    print(f"  │")
    print(f"  │  {'Period':<12} {metric.upper():>8} {'Sharpe':>8} {'Sortino':>8} {'Calmar':>8} {'Omega':>8} {'CAGR':>8} {'MDD':>8}")
    print(f"  │  {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    
    for period, prefix in [('IS 12-18', 'is'), ('OOS 19-22', 'oos'), ('FWD 23-26', 'fwd'), ('FULL', 'full')]:
        sh = best[f'{prefix}_sharpe']
        so = best[f'{prefix}_sortino']
        ca = best[f'{prefix}_calmar']
        om = best[f'{prefix}_omega']
        cagr = best[f'{prefix}_cagr']
        mdd = best[f'{prefix}_mdd']
        metric_val = best[f'{prefix}_{metric}']
        marker = ' ◄' if prefix == 'is' else ''
        print(f"  │  {period:<12} {metric_val:>8.3f} {sh:>8.3f} {so:>8.3f} {ca:>8.3f} {om:>8.3f} {cagr*100:>+7.1f}% {mdd*100:>7.1f}%{marker}")
    
    print(f"  │  Trades/yr: {best['trades_yr']:.1f}")
    
    # Compare with sealed
    if sealed is not None:
        delta_is = best[is_col] - sealed[is_col]
        delta_oos = best[oos_col] - sealed[oos_col]
        delta_cagr = best['full_cagr'] - sealed['full_cagr']
        print(f"  │  vs Sealed: IS {metric} {delta_is:+.3f}, OOS {metric} {delta_oos:+.3f}, Full CAGR {delta_cagr*100:+.1f}pp")
    print(f"  └─")

# ── Summary Table ──
print(f"\n{'='*130}")
print(f"  SUMMARY: BEST-BY-METRIC vs SEALED")
print(f"{'='*130}")

print(f"\n  {'Optimized For':<15} {'Params':>35} │ {'Full CAGR':>10} {'Full MDD':>10} {'Full Sh':>8} {'Full So':>8} {'Full Ca':>8} {'Full Om':>8} │ {'OOS Sh':>7} {'OOS So':>7}")
print(f"  {'-'*15} {'-'*35} │ {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8} │ {'-'*7} {'-'*7}")

# Sealed first
if sealed is not None:
    p = f"CrT={sealed['zt']:.1f} CrR={sealed['zr']:.1f} VT={sealed['vt']:.1f} VR={sealed['vr']:.1f} IT={sealed['it']:.1f} IR={sealed['ir']:.1f}"
    print(f"  {'★ SEALED':<15} {p:>35} │ {sealed['full_cagr']*100:>+9.1f}% {sealed['full_mdd']*100:>9.1f}% {sealed['full_sharpe']:>8.3f} {sealed['full_sortino']:>8.3f} {sealed['full_calmar']:>8.3f} {sealed['full_omega']:>8.3f} │ {sealed['oos_sharpe']:>7.3f} {sealed['oos_sortino']:>7.3f}")

for metric in metrics_to_optimize:
    is_col = f'is_{metric}'
    if len(audit) == 0: continue
    best = audit.loc[audit[is_col].idxmax()]
    p = f"CrT={best['zt']:.1f} CrR={best['zr']:.1f} VT={best['vt']:.1f} VR={best['vr']:.1f} IT={best['it']:.1f} IR={best['ir']:.1f}"
    label = f"Max {metric.title()}"
    print(f"  {label:<15} {p:>35} │ {best['full_cagr']*100:>+9.1f}% {best['full_mdd']*100:>9.1f}% {best['full_sharpe']:>8.3f} {best['full_sortino']:>8.3f} {best['full_calmar']:>8.3f} {best['full_omega']:>8.3f} │ {best['oos_sharpe']:>7.3f} {best['oos_sortino']:>7.3f}")

# Also find max CAGR (audit-passed)
if len(audit) > 0:
    best_cagr = audit.loc[audit['full_cagr'].idxmax()]
    p = f"CrT={best_cagr['zt']:.1f} CrR={best_cagr['zr']:.1f} VT={best_cagr['vt']:.1f} VR={best_cagr['vr']:.1f} IT={best_cagr['it']:.1f} IR={best_cagr['ir']:.1f}"
    print(f"  {'Max CAGR':<15} {p:>35} │ {best_cagr['full_cagr']*100:>+9.1f}% {best_cagr['full_mdd']*100:>9.1f}% {best_cagr['full_sharpe']:>8.3f} {best_cagr['full_sortino']:>8.3f} {best_cagr['full_calmar']:>8.3f} {best_cagr['full_omega']:>8.3f} │ {best_cagr['oos_sharpe']:>7.3f} {best_cagr['oos_sortino']:>7.3f}")

# ── Verdict ──
print(f"\n{'='*130}")
print(f"  VERDICT")
print(f"{'='*130}")

if len(audit) > 0 and sealed is not None:
    # Check if any metric's best is meaningfully different from sealed
    any_different = False
    for metric in metrics_to_optimize:
        best = audit.loc[audit[f'is_{metric}'].idxmax()]
        same_params = (best['zt'] == sealed['zt'] and best['zr'] == sealed['zr'] and
                      best['vt'] == sealed['vt'] and best['vr'] == sealed['vr'] and
                      best['it'] == sealed['it'] and best['ir'] == sealed['ir'])
        oos_better = best[f'oos_{metric}'] > sealed[f'oos_{metric}']
        print(f"  Max IS {metric.title():>8}: same_as_sealed={same_params}, OOS_better={oos_better}, "
              f"Full CAGR={best['full_cagr']*100:+.1f}% (sealed {sealed['full_cagr']*100:+.1f}%)")
        if not same_params and oos_better:
            any_different = True
    
    if not any_different:
        print(f"\n  ✅ No metric finds a combo that beats Sealed on BOTH IS and OOS.")
        print(f"     Sealed params remain optimal across all risk-adjusted metrics.")
    else:
        print(f"\n  🔶 Some metrics find OOS-validated improvements. Review above for details.")

print()
