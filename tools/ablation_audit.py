#!/usr/bin/env python3
import os
import numpy as np
import pandas as pd
import yfinance as yf
from fredapi import Fred

from strategy_engine import (
    compute_credit_z, compute_vol_z, compute_inflation_z,
    parse_sep_pdfs, build_sep_signals, build_sep_state,
    run_backtest as engine_run_backtest,
    get_fred_api_key
)

PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP_DIR      = os.path.join(PROJECT_DIR, 'fomc_sep')
START_DATE   = '2012-01-25'

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

def load_data():
    fred = Fred(api_key=get_fred_api_key())
    effr_raw = fred.get_series('DFF', observation_start='2005-01-01').dropna()
    qqq_raw, qqq_open_raw = fetch_yahoo_ohlc('QQQ')
    hyg_raw, _ = fetch_yahoo_ohlc('HYG')
    ief_raw, _ = fetch_yahoo_ohlc('IEF')
    tip_raw, _ = fetch_yahoo_ohlc('TIP')
    tlt_raw, _ = fetch_yahoo_ohlc('TLT')

    idx = qqq_raw.index[qqq_raw.index >= pd.Timestamp(START_DATE)]
    qqq_d    = qqq_raw.reindex(idx)
    qqq_open = qqq_open_raw.reindex(idx)
    dr_qqq   = qqq_d.pct_change()
    dr_qqq_gap   = qqq_open / qqq_d.shift(1) - 1
    dr_qqq_intra = qqq_d / qqq_open - 1
    effr     = effr_raw.reindex(idx).ffill() / 100 / 252

    full_idx = qqq_raw.dropna().index
    hyg_full = hyg_raw.reindex(full_idx).ffill()
    ief_full = ief_raw.reindex(full_idx).ffill()
    tip_full = tip_raw.reindex(full_idx).ffill()
    tlt_full = tlt_raw.reindex(full_idx).ffill()
    dr_full  = qqq_raw.reindex(full_idx).pct_change()

    z_full     = compute_credit_z(hyg_full, ief_full)
    vol_z_full = compute_vol_z(dr_full)
    inf_z_full = compute_inflation_z(tip_full, tlt_full)

    z_series = z_full.reindex(idx)
    vol_z    = vol_z_full.reindex(idx)
    inf_z    = inf_z_full.reindex(idx)

    sep_raw = parse_sep_pdfs(SEP_DIR)
    sep_signals = build_sep_signals(sep_raw)
    sep_state, _ = build_sep_state(sep_signals, idx)

    return idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, effr, z_series, vol_z, inf_z, sep_state, qqq_d

def calc_cvar(returns, alpha=0.05):
    if len(returns) == 0: return 0
    var = np.percentile(returns, alpha * 100)
    return returns[returns <= var].mean()

def run_ablation():
    idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, effr, z_series, vol_z, inf_z, sep_state, qqq_d = load_data()

    # Disable signals array
    z_off = pd.Series(np.nan, index=z_series.index)
    v_off = pd.Series(np.nan, index=vol_z.index)
    i_off = pd.Series(np.nan, index=inf_z.index)

    variants = {
        'A_SEP_Only': (z_off, v_off, i_off),
        'B_SEP_Credit': (z_series, v_off, i_off),
        'C_SEP_TIP': (z_off, v_off, inf_z),
        'D_SEP_Vol': (z_off, vol_z, i_off),
        'E_SEP_Credit_TIP': (z_series, v_off, inf_z),
        'F_SEP_Credit_Vol': (z_series, vol_z, i_off),
        'G_SEP_TIP_Vol': (z_off, vol_z, inf_z),
        'H_Full': (z_series, vol_z, inf_z)
    }

    results = {}
    print("Running Ablation Sweep...")
    for name, (zi, vi, ii) in variants.items():
        res = engine_run_backtest(
            idx=idx, dr_qqq=dr_qqq, dr_qqq_gap=dr_qqq_gap, dr_qqq_intra=dr_qqq_intra,
            effr=effr, z_series=zi, vol_z=vi, sep_state=sep_state, inf_z=ii,
            use_sep=True, use_overlay=True
        )
        # Calculate CVaR
        ret = res['equity'].pct_change().dropna()
        cvar = calc_cvar(ret)
        res['cvar'] = cvar
        results[name] = res

    # 1. Marginal Performance (Standalone vs Removal)
    print("\n--- MARGINAL VALUE ---")
    print(f"{'Layer':<10s} {'Standalone_CAGR':>18s} {'Standalone_Sharpe':>18s} | {'Removal_CAGR':>18s} {'Removal_Sharpe':>18s}")
    
    perf_sep = results['A_SEP_Only']
    perf_full = results['H_Full']

    def print_marginal(layer, standalone_name, full_minus_name):
        st = results[standalone_name]
        fm = results[full_minus_name]
        
        # Standalone Increment = (SEP+Layer) - (SEP_Only)
        sa_cagr = st['cagr'] - perf_sep['cagr']
        sa_sharpe = st['sharpe'] - perf_sep['sharpe']
        
        # Removal Cost = (Full) - (Full_Minus_Layer)
        rm_cagr = perf_full['cagr'] - fm['cagr']
        rm_sharpe = perf_full['sharpe'] - fm['sharpe']
        
        print(f"{layer:<10s} {sa_cagr*100:>17.2f}% {sa_sharpe:>18.2f} | {rm_cagr*100:>17.2f}% {rm_sharpe:>18.2f}")
    
    print_marginal("Credit", 'B_SEP_Credit', 'G_SEP_TIP_Vol')
    print_marginal("TIP/TLT", 'C_SEP_TIP', 'F_SEP_Credit_Vol')
    print_marginal("Vol", 'D_SEP_Vol', 'E_SEP_Credit_TIP')

    # 2. Conditional Crash Capture
    print("\n--- CONDITIONAL CRASH CAPTURE (SEP=IN) ---")
    # Weekly sampling to avoid overlap
    weekly_idx = idx[::5]
    
    # Calculate forward MDD for QQQ
    def get_forward_mdd(date, horizon_days):
        loc = qqq_d.index.get_loc(date)
        if loc + horizon_days >= len(qqq_d): return 0
        fut_slice = qqq_d.iloc[loc:loc+horizon_days]
        mdd = ((fut_slice / fut_slice.expanding().max()) - 1).min()
        return mdd

    fwd_63 = pd.Series([get_forward_mdd(d, 63) for d in weekly_idx], index=weekly_idx)
    fwd_126 = pd.Series([get_forward_mdd(d, 126) for d in weekly_idx], index=weekly_idx)

    # Condition: SEP=IN
    sep_in_mask = sep_state.reindex(weekly_idx) == 1
    
    # Extract Danger logs from Full run
    # danger = Credit, inf_danger = TIP, vol_danger = Vol
    danger_cr = pd.Series(perf_full['danger'], index=idx).reindex(weekly_idx)
    danger_tip = pd.Series(perf_full['inf_danger'], index=idx).reindex(weekly_idx)
    danger_vol = pd.Series(perf_full['vol_danger'], index=idx).reindex(weekly_idx)

    # Crash counts baseline
    n_sep_in = sep_in_mask.sum()
    c63_base = (fwd_63[sep_in_mask] <= -0.15).sum()
    c126_base = (fwd_126[sep_in_mask] <= -0.20).sum()
    
    p63_base = c63_base / n_sep_in if n_sep_in > 0 else 0
    p126_base = c126_base / n_sep_in if n_sep_in > 0 else 0
    
    print(f"Baseline P(Crash|SEP=IN): 63d(-15%) = {p63_base*100:.1f}%, 126d(-20%) = {p126_base*100:.1f}% (N={n_sep_in})")

    def print_conditional(layer, mask):
        cond_mask = sep_in_mask & mask
        n_cond = cond_mask.sum()
        if n_cond == 0:
            print(f"{layer:<10s}: Never triggered while SEP=IN.")
            return
        c63 = (fwd_63[cond_mask] <= -0.15).sum()
        c126 = (fwd_126[cond_mask] <= -0.20).sum()
        p63 = c63 / n_cond
        p126 = c126 / n_cond
        print(f"{layer:<10s} P(Crash|SEP=IN & Danger): 63d = {p63*100:4.1f}% (N={n_cond:<3d}), 126d = {p126*100:4.1f}%")

    print_conditional("Credit", danger_cr)
    print_conditional("TIP/TLT", danger_tip)
    print_conditional("Vol", danger_vol)

    # 3. Path-Dependent LOO Crisis Test
    print("\n--- LOO CRISIS TEST (REMOVAL COST SHARPE) ---")
    crises = {
        'None (Full Hist)': (None, None),
        'No_2018 (Q4)': ('2018-10-01', '2018-12-31'),
        'No_2020 (COVID)': ('2020-02-19', '2020-03-31'),
        'No_2022 (Bear)': ('2022-01-01', '2022-12-31')
    }
    
    # We want to see if removing a layer hurts Sharpe (i.e. Removal Cost > 0).
    # If Removal Cost is > 0 in Full Hist, but drops to ~0 when 2020 is removed, 
    # it means that layer ONLY worked in 2020.
    
    def calc_loo_sharpe(eq_series, exc_start, exc_end):
        ret = eq_series.pct_change().dropna()
        if exc_start and exc_end:
            mask = (ret.index < exc_start) | (ret.index > exc_end)
            ret = ret[mask]
        return (ret.mean() / ret.std()) * np.sqrt(252) if ret.std() > 0 else 0

    print(f"{'Crisis_Exc':<18s} | {'Full_Shp':>8s} | {'No_Cr_Cost':>10s} | {'No_TIP_Cost':>11s} | {'No_Vol_Cost':>11s}")
    for c_name, (start, end) in crises.items():
        shp_f = calc_loo_sharpe(perf_full['equity'], start, end)
        shp_no_cr = calc_loo_sharpe(results['G_SEP_TIP_Vol']['equity'], start, end)
        shp_no_tip = calc_loo_sharpe(results['F_SEP_Credit_Vol']['equity'], start, end)
        shp_no_vol = calc_loo_sharpe(results['E_SEP_Credit_TIP']['equity'], start, end)
        
        rc_cr = shp_f - shp_no_cr
        rc_tip = shp_f - shp_no_tip
        rc_vol = shp_f - shp_no_vol
        
        print(f"{c_name:<18s} | {shp_f:>8.2f} | {rc_cr:>10.2f} | {rc_tip:>11.2f} | {rc_vol:>11.2f}")

    print("\n--- RAW RESULTS DUMP ---")
    print(f"{'Variant':<20s} {'CAGR':>8s} {'Sharpe':>8s} {'MDD':>8s} {'Trades':>6s}")
    for name, res in results.items():
        print(f"{name:<20s} {res['cagr']*100:>7.1f}% {res['sharpe']:>8.2f} {res['mdd']*100:>7.1f}% {res['trades']:>6d}")

if __name__ == "__main__":
    run_ablation()
