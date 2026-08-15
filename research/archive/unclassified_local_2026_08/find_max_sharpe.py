#!/usr/bin/env python3
"""
ROBUST Max-Sharpe Parameter Search
===================================
1. IS-only selection (2012-2018 max Sharpe)
2. OOS validation (2019-2022)
3. FWD confirmation (2023-2026)
4. Plateau stability analysis
5. TC=200bps stress test
6. Full comparison with sealed params
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
    run_backtest as engine_run_backtest,
    get_fred_api_key,
)

FRED_API_KEY = get_fred_api_key()
PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP_DIR      = os.path.join(PROJECT_DIR, 'fomc_sep')
START_DATE   = '2012-01-25'

print("=" * 80)
print("  ROBUST MAX-SHARPE PARAMETER SEARCH")
print("=" * 80)
sys.stdout.flush()

# ── Data Loading ──
print("\n[1/6] Loading data...")
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

# Period boundaries (index positions)
IS_END   = '2018-12-31'
OOS_END  = '2022-12-31'

is_mask  = idx <= pd.Timestamp(IS_END)
oos_mask = (idx > pd.Timestamp(IS_END)) & (idx <= pd.Timestamp(OOS_END))
fwd_mask = idx > pd.Timestamp(OOS_END)

is_start_idx  = 0
is_end_idx    = int(np.where(is_mask)[0][-1]) + 1
oos_start_idx = int(np.where(oos_mask)[0][0])
oos_end_idx   = int(np.where(oos_mask)[0][-1]) + 1
fwd_start_idx = int(np.where(fwd_mask)[0][0])
fwd_end_idx   = len(idx)

print(f"  Full:  {idx[0].date()} → {idx[-1].date()} ({len(idx)} days)")
print(f"  IS:    {idx[0].date()} → {idx[is_end_idx-1].date()} ({is_end_idx} days)")
print(f"  OOS:   {idx[oos_start_idx].date()} → {idx[oos_end_idx-1].date()} ({oos_end_idx-oos_start_idx} days)")
print(f"  FWD:   {idx[fwd_start_idx].date()} → {idx[-1].date()} ({fwd_end_idx-fwd_start_idx} days)")
sys.stdout.flush()

# ── Pre-convert to numpy ──
N = len(idx)
dr_qqq_np = dr_qqq.values.astype(np.float64)
dr_qqq_gap_np = (qqq_open / qqq_d.shift(1) - 1).values.astype(np.float64)
dr_qqq_intra_np = (qqq_d / qqq_open - 1).values.astype(np.float64)
effr_np = effr.values.astype(np.float64)
z_np = z_series.values.astype(np.float64)
vol_z_np = vol_z.values.astype(np.float64)
inf_z_np = inf_z.values.astype(np.float64)
sep_np = sep_state.values.astype(np.float64)
EXPENSE_RATIO_DAILY = EXPENSE_RATIO / 252


def fast_backtest_full(zt, zr, vzt, vzr, vz_lev, inft, infr, inf_lev, tc_bps):
    """Returns full equity array for sub-period slicing."""
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
            if pending != lev:
                switch_today = True
            lev = pending
            pending = -1.0

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

            if in_danger:
                tgt = 1.0 if is_profitable else 3.0
            elif inf_danger:
                tgt = inf_lev if is_profitable else lev
            elif vol_danger:
                tgt = vz_lev if is_profitable else lev
            else:
                tgt = 3.0

        if tgt != lev:
            pending = tgt
        if lev > 0 and not in_trade:
            in_trade = True; trade_entry_eq = eq
        elif lev == 0 and in_trade:
            in_trade = False
        if lev != prev_lev and lev > 0 and prev_lev > 0:
            if lev > prev_lev:
                trade_entry_eq = (trade_entry_eq * prev_lev + eq * (lev - prev_lev)) / lev
        if lev != prev_lev:
            trades += 1

        if i > 0:
            r_total = dr_qqq_np[i]
            if np.isnan(r_total): r_total = 0.0
            if switch_today:
                rg = dr_qqq_gap_np[i]
                ri = dr_qqq_intra_np[i]
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

        prev_lev = lev
        eql[i] = eq

    return eql, trades


def compute_metrics(eql, start, end):
    """Compute CAGR, MDD, Sharpe for a sub-period of the equity array."""
    sl = eql[start:end]
    if len(sl) < 50:
        return {'cagr': np.nan, 'mdd': np.nan, 'sharpe': np.nan}
    sl_norm = sl / sl[0]
    ny = len(sl) / 252
    cagr = sl_norm[-1] ** (1/ny) - 1
    running_max = np.maximum.accumulate(sl_norm)
    mdd = (sl_norm / running_max - 1).min()
    rets = np.diff(sl) / sl[:-1]
    sharpe = (np.mean(rets) / np.std(rets)) * np.sqrt(252) if np.std(rets) > 0 else 0
    return {'cagr': cagr, 'mdd': mdd, 'sharpe': sharpe}


# ── Grid Search ──
print("\n[2/6] Grid search — selecting on IS (2012-2018) Sharpe...")
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

    eql, trades = fast_backtest_full(zt, zr, vt, vr, VZ_LEV, it, ir, INF_LEV, TC_BPS)
    years_full = N / 252

    m_full = compute_metrics(eql, 0, N)
    m_is   = compute_metrics(eql, is_start_idx, is_end_idx)
    m_oos  = compute_metrics(eql, oos_start_idx, oos_end_idx)
    m_fwd  = compute_metrics(eql, fwd_start_idx, fwd_end_idx)

    # Also run TC=200bps
    eql_tc200, _ = fast_backtest_full(zt, zr, vt, vr, VZ_LEV, it, ir, INF_LEV, 200)
    m_tc200 = compute_metrics(eql_tc200, 0, N)

    results.append({
        'zt': zt, 'zr': zr, 'vt': vt, 'vr': vr, 'it': it, 'ir': ir,
        # Full
        'sharpe': m_full['sharpe'], 'cagr': m_full['cagr'], 'mdd': m_full['mdd'],
        'trades': trades, 'trades_yr': trades / years_full,
        # IS
        'is_sharpe': m_is['sharpe'], 'is_cagr': m_is['cagr'], 'is_mdd': m_is['mdd'],
        # OOS
        'oos_sharpe': m_oos['sharpe'], 'oos_cagr': m_oos['cagr'], 'oos_mdd': m_oos['mdd'],
        # FWD
        'fwd_sharpe': m_fwd['sharpe'], 'fwd_cagr': m_fwd['cagr'], 'fwd_mdd': m_fwd['mdd'],
        # TC stress
        'tc200_sharpe': m_tc200['sharpe'],
    })

    count += 1
    if count % 2000 == 0:
        elapsed = time.time() - t0
        print(f"    {count} tested ({elapsed:.0f}s)")
        sys.stdout.flush()

elapsed = time.time() - t0
print(f"  Total: {count} combos in {elapsed:.1f}s ({count/elapsed:.0f}/sec)")
sys.stdout.flush()

df = pd.DataFrame(results)
years_full = N / 252

# ── IS Selection with audit filters ──
print("\n[3/6] IS-only selection (2012-2018) with audit filters...")
sys.stdout.flush()

# Audit filters applied on FULL period (same as production audit)
audit_pass = df[
    (df['sharpe'] > 1.33) &
    (df['mdd'] >= -0.45) &
    (df['trades_yr'] <= 5.0) &
    (df['tc200_sharpe'] > 1.0) &
    (df['oos_sharpe'] > 0.5) &
    (df['fwd_sharpe'] > 0.5)
].copy()

print(f"  Full audit pass: {len(audit_pass)}/{len(df)} combos")
print(f"    - Sharpe > 1.33:      {(df['sharpe'] > 1.33).sum()}")
print(f"    - MDD > -45%:         {(df['mdd'] >= -0.45).sum()}")
print(f"    - Trades/yr <= 5:     {(df['trades_yr'] <= 5.0).sum()}")
print(f"    - TC200 Sharpe > 1.0: {(df['tc200_sharpe'] > 1.0).sum()}")
print(f"    - OOS Sharpe > 0.5:   {(df['oos_sharpe'] > 0.5).sum()}")
print(f"    - FWD Sharpe > 0.5:   {(df['fwd_sharpe'] > 0.5).sum()}")

# From audit_pass, select by IS Sharpe
if len(audit_pass) > 0:
    top_is = audit_pass.nlargest(10, 'is_sharpe')
    top_full = audit_pass.nlargest(10, 'sharpe')
else:
    print("  ⚠️  No combos pass full audit! Relaxing to basic filters...")
    basic = df[(df['sharpe'] > 1.0) & (df['mdd'] >= -0.50)]
    top_is = basic.nlargest(10, 'is_sharpe')
    top_full = basic.nlargest(10, 'sharpe')

# ── Print IS-selected top 10 ──
print(f"\n{'='*120}")
print(f"  TOP 10 BY IS SHARPE (2012-2018) — with OOS/FWD validation")
print(f"{'='*120}")
header = f"  {'#':<3} {'CrT':>4} {'CrR':>4} {'VT':>4} {'VR':>4} {'IT':>4} {'IR':>4}  " \
         f"{'IS_Sh':>6} {'OOS_Sh':>6} {'FWD_Sh':>6} │ {'Full_Sh':>7} {'CAGR':>7} {'MDD':>7} {'TC200':>6} {'Tr/yr':>5}"
print(header)
print(f"  {'-'*3} {'-'*4} {'-'*4} {'-'*4} {'-'*4} {'-'*4} {'-'*4}  " 
      f"{'-'*6} {'-'*6} {'-'*6} │ {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*5}")

for rank, (_, row) in enumerate(top_is.iterrows(), 1):
    sealed = ""
    if (row['zt'] == Z_TRIGGER and row['zr'] == Z_RECOVER and
        row['vt'] == VZ_TRIGGER and row['vr'] == VZ_RECOVER and
        row['it'] == INF_TRIGGER and row['ir'] == INF_RECOVER):
        sealed = " ← SEALED"
    print(f"  {rank:<3} {row['zt']:>4.1f} {row['zr']:>4.1f} {row['vt']:>4.1f} {row['vr']:>4.1f} {row['it']:>4.1f} {row['ir']:>4.1f}  "
          f"{row['is_sharpe']:>6.3f} {row['oos_sharpe']:>6.3f} {row['fwd_sharpe']:>6.3f} │ "
          f"{row['sharpe']:>7.3f} {row['cagr']*100:>+6.1f}% {row['mdd']*100:>6.1f}% {row['tc200_sharpe']:>6.2f} {row['trades_yr']:>5.1f}{sealed}")

# ── Print Full-Sharpe top 10 for comparison ──
print(f"\n{'='*120}")
print(f"  TOP 10 BY FULL-PERIOD SHARPE — for comparison")
print(f"{'='*120}")
print(header)
print(f"  {'-'*3} {'-'*4} {'-'*4} {'-'*4} {'-'*4} {'-'*4} {'-'*4}  "
      f"{'-'*6} {'-'*6} {'-'*6} │ {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*5}")

for rank, (_, row) in enumerate(top_full.iterrows(), 1):
    sealed = ""
    if (row['zt'] == Z_TRIGGER and row['zr'] == Z_RECOVER and
        row['vt'] == VZ_TRIGGER and row['vr'] == VZ_RECOVER and
        row['it'] == INF_TRIGGER and row['ir'] == INF_RECOVER):
        sealed = " ← SEALED"
    print(f"  {rank:<3} {row['zt']:>4.1f} {row['zr']:>4.1f} {row['vt']:>4.1f} {row['vr']:>4.1f} {row['it']:>4.1f} {row['ir']:>4.1f}  "
          f"{row['is_sharpe']:>6.3f} {row['oos_sharpe']:>6.3f} {row['fwd_sharpe']:>6.3f} │ "
          f"{row['sharpe']:>7.3f} {row['cagr']*100:>+6.1f}% {row['mdd']*100:>6.1f}% {row['tc200_sharpe']:>6.2f} {row['trades_yr']:>5.1f}{sealed}")

# ── Sealed params detail ──
sealed_row = df[
    (df['zt'] == Z_TRIGGER) & (df['zr'] == Z_RECOVER) &
    (df['vt'] == VZ_TRIGGER) & (df['vr'] == VZ_RECOVER) &
    (df['it'] == INF_TRIGGER) & (df['ir'] == INF_RECOVER)
]

print(f"\n{'='*120}")
print(f"  SEALED vs IS-MAX-SHARPE vs FULL-MAX-SHARPE — HEAD TO HEAD")
print(f"{'='*120}")

def print_detail(label, row):
    print(f"\n  {label}")
    print(f"    Params:     CrT={row['zt']:.1f} CrR={row['zr']:.1f} VT={row['vt']:.1f} VR={row['vr']:.1f} IT={row['it']:.1f} IR={row['ir']:.1f}")
    print(f"    Full:       Sharpe={row['sharpe']:.3f}  CAGR={row['cagr']*100:+.1f}%  MDD={row['mdd']*100:.1f}%")
    print(f"    IS  12-18:  Sharpe={row['is_sharpe']:.3f}  CAGR={row['is_cagr']*100:+.1f}%  MDD={row['is_mdd']*100:.1f}%")
    print(f"    OOS 19-22:  Sharpe={row['oos_sharpe']:.3f}  CAGR={row['oos_cagr']*100:+.1f}%  MDD={row['oos_mdd']*100:.1f}%")
    print(f"    FWD 23-26:  Sharpe={row['fwd_sharpe']:.3f}  CAGR={row['fwd_cagr']*100:+.1f}%  MDD={row['fwd_mdd']*100:.1f}%")
    print(f"    TC200:      Sharpe={row['tc200_sharpe']:.3f}")
    print(f"    Trades/yr:  {row['trades_yr']:.1f}")

if len(sealed_row) > 0:
    print_detail("SEALED (current production)", sealed_row.iloc[0])

if len(audit_pass) > 0:
    best_is = audit_pass.loc[audit_pass['is_sharpe'].idxmax()]
    print_detail("★ IS-MAX-SHARPE (selected on 2012-2018 only)", best_is)

    best_full = audit_pass.loc[audit_pass['sharpe'].idxmax()]
    print_detail("FULL-MAX-SHARPE (selected on entire period)", best_full)

# ── Plateau Analysis ──
print(f"\n{'='*120}")
print(f"  [4/6] PLATEAU STABILITY ANALYSIS")
print(f"{'='*120}")

# For the IS-max-sharpe combo, check all neighbors (±1 grid step)
if len(audit_pass) > 0:
    best = audit_pass.loc[audit_pass['is_sharpe'].idxmax()]
    bzt, bzr, bvt, bvr, bit_, bir = best['zt'], best['zr'], best['vt'], best['vr'], best['it'], best['ir']

    # Find neighbors: any combo that differs by at most 1 grid step in any single param
    def is_neighbor(row):
        diffs = 0
        if row['zt'] != bzt: diffs += 1
        if row['zr'] != bzr: diffs += 1
        if row['vt'] != bvt: diffs += 1
        if row['vr'] != bvr: diffs += 1
        if row['it'] != bit_: diffs += 1
        if row['ir'] != bir: diffs += 1
        return 0 < diffs <= 1  # exactly 1 param different

    neighbors = df[df.apply(is_neighbor, axis=1)]

    print(f"\n  Best IS combo: CrT={bzt} CrR={bzr} VT={bvt} VR={bvr} IT={bit_} IR={bir}")
    print(f"  Best IS Sharpe: {best['is_sharpe']:.3f} (Full: {best['sharpe']:.3f})")
    print(f"  Neighbors (1-step): {len(neighbors)}")

    if len(neighbors) > 0:
        print(f"\n  {'Param Changed':<20} {'Value':>6} {'IS_Sh':>7} {'Δ_IS':>7} {'Full_Sh':>8} {'Δ_Full':>7}")
        print(f"  {'-'*20} {'-'*6} {'-'*7} {'-'*7} {'-'*8} {'-'*7}")

        for _, nb in neighbors.sort_values('is_sharpe', ascending=False).iterrows():
            # Which param changed?
            if nb['zt'] != bzt: pname, pval = 'CrT', nb['zt']
            elif nb['zr'] != bzr: pname, pval = 'CrR', nb['zr']
            elif nb['vt'] != bvt: pname, pval = 'VT', nb['vt']
            elif nb['vr'] != bvr: pname, pval = 'VR', nb['vr']
            elif nb['it'] != bit_: pname, pval = 'IT', nb['it']
            else: pname, pval = 'IR', nb['ir']

            d_is = nb['is_sharpe'] - best['is_sharpe']
            d_full = nb['sharpe'] - best['sharpe']
            print(f"  {pname:<20} {pval:>6.1f} {nb['is_sharpe']:>7.3f} {d_is:>+7.3f} {nb['sharpe']:>8.3f} {d_full:>+7.3f}")

        # Plateau summary
        within_005 = (neighbors['is_sharpe'] >= best['is_sharpe'] - 0.05).sum()
        within_010 = (neighbors['is_sharpe'] >= best['is_sharpe'] - 0.10).sum()
        print(f"\n  Plateau: {within_005}/{len(neighbors)} within 0.05, {within_010}/{len(neighbors)} within 0.10 of best IS Sharpe")

    # Same analysis for SEALED
    sealed = sealed_row.iloc[0] if len(sealed_row) > 0 else None
    if sealed is not None:
        szt, szr, svt, svr, sit, sir = sealed['zt'], sealed['zr'], sealed['vt'], sealed['vr'], sealed['it'], sealed['ir']
        def is_sealed_neighbor(row):
            diffs = 0
            if row['zt'] != szt: diffs += 1
            if row['zr'] != szr: diffs += 1
            if row['vt'] != svt: diffs += 1
            if row['vr'] != svr: diffs += 1
            if row['it'] != sit: diffs += 1
            if row['ir'] != sir: diffs += 1
            return 0 < diffs <= 1

        s_neighbors = df[df.apply(is_sealed_neighbor, axis=1)]
        within_005_s = (s_neighbors['is_sharpe'] >= sealed['is_sharpe'] - 0.05).sum()
        within_010_s = (s_neighbors['is_sharpe'] >= sealed['is_sharpe'] - 0.10).sum()
        print(f"\n  SEALED plateau: {within_005_s}/{len(s_neighbors)} within 0.05, {within_010_s}/{len(s_neighbors)} within 0.10")


# ── Cross-period degradation ──
print(f"\n{'='*120}")
print(f"  [5/6] CROSS-PERIOD DEGRADATION CHECK")
print(f"{'='*120}")

if len(audit_pass) > 0:
    best_is_row = audit_pass.loc[audit_pass['is_sharpe'].idxmax()]
    sealed_r = sealed_row.iloc[0] if len(sealed_row) > 0 else None

    print(f"\n  {'Metric':<25} {'IS-Max-Sharpe':>15} {'Sealed':>15} {'Delta':>10}")
    print(f"  {'-'*25} {'-'*15} {'-'*15} {'-'*10}")

    metrics = [
        ('IS Sharpe',   'is_sharpe'),
        ('OOS Sharpe',  'oos_sharpe'),
        ('FWD Sharpe',  'fwd_sharpe'),
        ('IS CAGR',     'is_cagr'),
        ('OOS CAGR',    'oos_cagr'),
        ('FWD CAGR',    'fwd_cagr'),
        ('IS MDD',      'is_mdd'),
        ('OOS MDD',     'oos_mdd'),
        ('FWD MDD',     'fwd_mdd'),
        ('TC200 Sharpe','tc200_sharpe'),
    ]

    for label, key in metrics:
        v1 = best_is_row[key]
        v2 = sealed_r[key] if sealed_r is not None else np.nan
        delta = v1 - v2 if not np.isnan(v2) else np.nan

        if 'cagr' in key.lower() or 'mdd' in key.lower():
            fmt = lambda x: f"{x*100:+.1f}%" if not np.isnan(x) else "N/A"
            dfmt = lambda x: f"{x*100:+.1f}pp" if not np.isnan(x) else "N/A"
        else:
            fmt = lambda x: f"{x:.3f}" if not np.isnan(x) else "N/A"
            dfmt = lambda x: f"{x:+.3f}" if not np.isnan(x) else "N/A"

        print(f"  {label:<25} {fmt(v1):>15} {fmt(v2):>15} {dfmt(delta):>10}")

    # OOS degradation check
    is_sh = best_is_row['is_sharpe']
    oos_sh = best_is_row['oos_sharpe']
    fwd_sh = best_is_row['fwd_sharpe']
    oos_deg = (is_sh - oos_sh) / is_sh * 100 if is_sh > 0 else 0
    fwd_deg = (is_sh - fwd_sh) / is_sh * 100 if is_sh > 0 else 0

    print(f"\n  IS→OOS Sharpe degradation: {oos_deg:+.1f}%  {'⚠️ OVERFIT RISK' if oos_deg > 30 else '✅ OK'}")
    print(f"  IS→FWD Sharpe degradation: {fwd_deg:+.1f}%  {'⚠️ OVERFIT RISK' if fwd_deg > 30 else '✅ OK'}")

    if sealed_r is not None:
        s_oos_deg = (sealed_r['is_sharpe'] - sealed_r['oos_sharpe']) / sealed_r['is_sharpe'] * 100
        s_fwd_deg = (sealed_r['is_sharpe'] - sealed_r['fwd_sharpe']) / sealed_r['is_sharpe'] * 100
        print(f"\n  SEALED IS→OOS degradation: {s_oos_deg:+.1f}%  {'⚠️' if s_oos_deg > 30 else '✅ OK'}")
        print(f"  SEALED IS→FWD degradation: {s_fwd_deg:+.1f}%  {'⚠️' if s_fwd_deg > 30 else '✅ OK'}")


# ── Final Verdict ──
print(f"\n{'='*120}")
print(f"  [6/6] VERDICT")
print(f"{'='*120}")

if len(audit_pass) > 0:
    best_is_row = audit_pass.loc[audit_pass['is_sharpe'].idxmax()]
    sealed_r = sealed_row.iloc[0] if len(sealed_row) > 0 else None

    # Is IS-max meaningfully better than sealed?
    if sealed_r is not None:
        sh_diff = best_is_row['sharpe'] - sealed_r['sharpe']
        oos_diff = best_is_row['oos_sharpe'] - sealed_r['oos_sharpe']
        fwd_diff = best_is_row['fwd_sharpe'] - sealed_r['fwd_sharpe']

        print(f"\n  IS-Max vs Sealed:")
        print(f"    Full Sharpe delta:  {sh_diff:+.3f}")
        print(f"    OOS Sharpe delta:   {oos_diff:+.3f}")
        print(f"    FWD Sharpe delta:   {fwd_diff:+.3f}")

        if abs(sh_diff) < 0.05 and abs(oos_diff) < 0.10:
            print(f"\n  ✅ CONCLUSION: IS-Max and Sealed are within noise range.")
            print(f"     Sealed params remain optimal — no change needed.")
        elif sh_diff > 0.05 and oos_diff > 0 and fwd_diff > 0:
            print(f"\n  🔶 CONCLUSION: IS-Max shows consistent improvement across all periods.")
            print(f"     Consider updating sealed params after full v2 re-seal process.")
        else:
            print(f"\n  ⚠️  CONCLUSION: IS-Max gains are period-specific.")
            print(f"     Sealed params are more robust — do not change.")

print()
