"""
Test current TQQQ 4-layer strategy on SOXL (3x Semiconductor ETF)
=================================================================
Same signals (Credit Z, Vol Z, TIP/TLT, SEP), same parameters.
SOXX = 1x underlying for semiconductors (like QQQ is for TQQQ).
We simulate 3x leveraged exposure on SOXX returns.
"""
import os, sys
import numpy as np
import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'tools'))
from strategy_engine import (
    compute_credit_z, compute_vol_z, compute_inflation_z,
    parse_sep_pdfs, build_sep_signals, build_sep_state,
    run_backtest, EXPENSE_RATIO
)

DATA_DIR = os.path.join(project_root, 'market_data')

def load_csv(name):
    path = os.path.join(DATA_DIR, f'yahoo_{name}.csv')
    s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
    return s[~s.index.duplicated(keep='last')]

# ---- Load all data from pre-saved CSV ----
print("Loading data...")
qqq = load_csv('QQQ')
soxx = load_csv('SOXX')
hyg = load_csv('HYG')
ief = load_csv('IEF')
tip = load_csv('TIP')
tlt = load_csv('TLT')

soxx_open = pd.read_csv(os.path.join(DATA_DIR, 'yahoo_SOXX_open.csv'),
                         index_col=0, parse_dates=True).squeeze()
soxx_open = soxx_open[~soxx_open.index.duplicated(keep='last')]

effr_raw = pd.read_csv(os.path.join(DATA_DIR, 'fred_DFF.csv'),
                        parse_dates=[0], index_col=0).squeeze()

print(f"SOXX: {soxx.dropna().index[0].date()} → {soxx.dropna().index[-1].date()} ({soxx.dropna().shape[0]} pts)")
print(f"QQQ:  {qqq.dropna().index[0].date()} → {qqq.dropna().index[-1].date()}")

# ---- Compute signals on FULL history ----
print("Computing signals...")
full_idx = qqq.dropna().index
hyg_full = hyg.reindex(full_idx).ffill()
ief_full = ief.reindex(full_idx).ffill()
tip_full = tip.reindex(full_idx).ffill()
tlt_full = tlt.reindex(full_idx).ffill()
dr_qqq_full = qqq.reindex(full_idx).pct_change()

z_full = compute_credit_z(hyg_full, ief_full)
vol_z_full = compute_vol_z(dr_qqq_full)
inf_z_full = compute_inflation_z(tip_full, tlt_full)

# SOXX-based vol z
soxx_aligned = soxx.reindex(full_idx).ffill()
dr_soxx_for_vol = soxx_aligned.pct_change()
vol_z_soxx_full = compute_vol_z(dr_soxx_for_vol)

# ---- SEP signals ----
print("Parsing SEP PDFs...")
SEP_DIR = os.path.join(project_root, 'fomc_sep')
sep_raw = parse_sep_pdfs(SEP_DIR)
sep_signals = build_sep_signals(sep_raw)

# ---- Slice to backtest window ----
idx = qqq.index[qqq.index >= pd.Timestamp('2012-01-25')]
sep_state, _ = build_sep_state(sep_signals, idx)

# QQQ returns (for TQQQ comparison)
qqq_d = qqq.reindex(idx)
dr_qqq = qqq_d.pct_change()
ef = effr_raw.reindex(idx).ffill() / 100 / 252

# QQQ gap/intra — use csv-based data (skip yfinance)
# For QQQ we can approximate: no gap/intra split (use None), engine handles it
dr_qqq_gap = None
dr_qqq_intra = None

# SOXX returns (to simulate 3x = SOXL)
soxx_d = soxx.reindex(idx).ffill()
dr_soxx = soxx_d.pct_change()

# SOXX gap/intra from pre-saved open prices
soxx_open_d = soxx_open.reindex(idx).ffill()
dr_soxx_gap = (soxx_open_d / soxx_d.shift(1) - 1).fillna(0)
dr_soxx_intra = (soxx_d / soxx_open_d - 1).fillna(0)

# Reindex signals
z_series = z_full.reindex(idx)
vol_z_qqq = vol_z_full.reindex(idx)
vol_z_soxx = vol_z_soxx_full.reindex(idx)
inf_z = inf_z_full.reindex(idx)

years = len(idx) / 252

print(f"\nBacktest: {idx[0].date()} → {idx[-1].date()} ({len(idx)} days, {years:.1f} yrs)")
print(f"SOXX valid days in window: {soxx_d.dropna().shape[0]}")
print()

# ============================================================================
# RUN BACKTESTS
# ============================================================================
print("=" * 80)
print("RUNNING BACKTESTS")
print("=" * 80)

# 1. TQQQ strategy (original)
res_tqqq = run_backtest(idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, ef,
                         z_series, vol_z_qqq, sep_state, inf_z=inf_z)

# 2. TQQQ Buy & Hold
res_tqqq_bh = run_backtest(idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, ef,
                            z_series, vol_z_qqq, sep_state, inf_z=inf_z,
                            use_sep=False, use_overlay=False)

# 3. SOXL strategy (same signals, SOXX returns, QQQ vol z)
res_soxl = run_backtest(idx, dr_soxx, dr_soxx_gap, dr_soxx_intra, ef,
                         z_series, vol_z_qqq, sep_state, inf_z=inf_z)

# 4. SOXL strategy (SOXX vol z)
res_soxl_sv = run_backtest(idx, dr_soxx, dr_soxx_gap, dr_soxx_intra, ef,
                            z_series, vol_z_soxx, sep_state, inf_z=inf_z)

# 5. SOXL Buy & Hold
res_soxl_bh = run_backtest(idx, dr_soxx, dr_soxx_gap, dr_soxx_intra, ef,
                            z_series, vol_z_soxx, sep_state, inf_z=inf_z,
                            use_sep=False, use_overlay=False)

# 6. SOXL with only SEP (no overlay)
res_soxl_sep_only = run_backtest(idx, dr_soxx, dr_soxx_gap, dr_soxx_intra, ef,
                                  z_series, vol_z_qqq, sep_state, inf_z=inf_z,
                                  use_sep=True, use_overlay=False)

# ============================================================================
# RESULTS
# ============================================================================
def calc_sharpe(eq):
    dr = eq.pct_change().dropna()
    return dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0

print("\n")
print("=" * 80)
print("PERFORMANCE COMPARISON")
print("=" * 80)

results = [
    ("TQQQ Buy & Hold (3x QQQ)", res_tqqq_bh),
    ("TQQQ + Full Strategy", res_tqqq),
    ("─" * 35, None),
    ("SOXL Buy & Hold (3x SOXX)", res_soxl_bh),
    ("SOXL + SEP only", res_soxl_sep_only),
    ("SOXL + Full Strategy (QQQ vol)", res_soxl),
    ("SOXL + Full Strategy (SOXX vol)", res_soxl_sv),
]

print(f"\n{'Strategy':<40s} {'CAGR':>8s} {'MDD':>8s} {'Sharpe':>8s} {'Trades':>7s} {'Tr/yr':>6s}")
print("-" * 80)
for name, res in results:
    if res is None:
        print(name)
        continue
    sharpe = calc_sharpe(res['equity'])
    print(f"{name:<40s} {res['cagr']*100:>+7.1f}% {res['mdd']*100:>+7.1f}% "
          f"{sharpe:>7.2f} {res['trades']:>6d} {res['trades']/years:>5.1f}")

# ============================================================================
# IS / OOS / FORWARD
# ============================================================================
print("\n")
print("=" * 80)
print("IS / HOLDOUT / FORWARD BREAKDOWN")
print("=" * 80)

periods = [
    ("IS (2012-2018)", '2012-01-25', '2018-12-31'),
    ("Holdout (2019-2022)", '2019-01-01', '2022-12-31'),
    ("Forward (2023+)", '2023-01-01', str(idx[-1].date())),
]

for period_name, start, end in periods:
    mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
    print(f"\n  {period_name}:")
    for strat_name, res in [("TQQQ Strategy", res_tqqq),
                              ("SOXL Strategy", res_soxl),
                              ("SOXL B&H", res_soxl_bh)]:
        eq = res['equity'][mask]
        if len(eq) < 2: continue
        eq_n = eq / eq.iloc[0]
        ny = len(eq_n) / 252
        cagr = eq_n.iloc[-1] ** (1/ny) - 1
        mdd = (eq_n / eq_n.expanding().max() - 1).min()
        sharpe = calc_sharpe(eq_n)
        print(f"    {strat_name:<20s}: CAGR={cagr*100:>+6.1f}%  MDD={mdd*100:>+6.1f}%  Sharpe={sharpe:>6.2f}")

# ============================================================================
# TRADE LOG
# ============================================================================
print("\n")
print("=" * 80)
print("SOXL TRADE LOG (Full Strategy, QQQ Vol Z)")
print("=" * 80)

print(f"\n{'Signal Date':<14s} {'Exec Date':<14s} {'From':>5s} {'To':>5s} {'Equity':>9s} {'Reason':<12s}")
print("-" * 65)
for t in res_soxl['trade_log']:
    print(f"{t['signal_date']:<14s} {t['exec_date']:<14s} {t['from_lev']:>5.0f} {t['to_lev']:>5.0f} "
          f"{t['equity']:>8.4f} {t['reason']:<12s}")

# ============================================================================
# CORRELATION
# ============================================================================
print("\n")
print("=" * 80)
print("QQQ vs SOXX — CORRELATION & VOLATILITY")
print("=" * 80)

# Use only overlapping non-NaN data
common = pd.DataFrame({'qqq': dr_qqq, 'soxx': dr_soxx}).dropna()
if len(common) > 0:
    corr = common['qqq'].corr(common['soxx'])
    soxx_vol = common['soxx'].std() * np.sqrt(252)
    qqq_vol = common['qqq'].std() * np.sqrt(252)
    
    print(f"\n  Daily return correlation:  {corr:.4f}")
    print(f"  QQQ annualized vol:       {qqq_vol*100:.1f}%")
    print(f"  SOXX annualized vol:      {soxx_vol*100:.1f}%")
    print(f"  SOXX/QQQ vol ratio:       {soxx_vol/qqq_vol:.2f}x")
    
    # Rolling correlation
    roll_corr = common['qqq'].rolling(63).corr(common['soxx']).dropna()
    print(f"  63d rolling corr range:   {roll_corr.min():.3f} to {roll_corr.max():.3f}")
    print(f"  63d rolling corr mean:    {roll_corr.mean():.3f}")
    low = (roll_corr < 0.80).sum()
    print(f"  Days with corr < 0.80:    {low} ({low/len(roll_corr)*100:.1f}%)")

# ============================================================================
# KEY DRAWDOWN EPISODES
# ============================================================================
print("\n")
print("=" * 80)
print("KEY DRAWDOWN EPISODES — SOXX vs QQQ")
print("=" * 80)

key_periods = [
    ("2018 Q4 Selloff", '2018-09-01', '2019-01-31'),
    ("COVID Crash", '2020-02-01', '2020-04-30'),
    ("2022 Bear Market", '2022-01-01', '2022-12-31'),
    ("2025 Tariff", '2025-02-01', '2025-05-31'),
]

for label, start, end in key_periods:
    mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
    
    for name, res in [("TQQQ Strat", res_tqqq), ("SOXL Strat", res_soxl), ("SOXL B&H", res_soxl_bh)]:
        eq = res['equity'][mask]
        if len(eq) < 2: continue
        eq_n = eq / eq.iloc[0]
        mdd = (eq_n / eq_n.expanding().max() - 1).min()
        total_ret = eq_n.iloc[-1] - 1
        if name == "TQQQ Strat":
            print(f"\n  {label}:")
        print(f"    {name:<15s}: return={total_ret*100:>+6.1f}%, MDD={mdd*100:>+6.1f}%")

print("\n")
print("=" * 80)
print("CONCLUSION")
print("=" * 80)
