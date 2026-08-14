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

def bootstrap_sharpe_diff(ret_full, ret_reduced, block_size=63, num_boot=1000):
    n = len(ret_full)
    diffs = []
    np.random.seed(42)
    blocks_full = [ret_full[i:i+block_size] for i in range(n - block_size + 1)]
    blocks_red = [ret_reduced[i:i+block_size] for i in range(n - block_size + 1)]
    num_blocks = len(blocks_full)
    for _ in range(num_boot):
        idx = np.random.randint(0, num_blocks, size=n // block_size + 1)
        boot_full = np.concatenate([blocks_full[i] for i in idx])[:n]
        boot_red = np.concatenate([blocks_red[i] for i in idx])[:n]
        shp_f = (boot_full.mean() / boot_full.std()) * np.sqrt(252) if boot_full.std() > 0 else 0
        shp_r = (boot_red.mean() / boot_red.std()) * np.sqrt(252) if boot_red.std() > 0 else 0
        diffs.append(shp_f - shp_r)
    diffs = np.array(diffs)
    return (diffs > 0).mean(), np.percentile(diffs, 2.5), np.percentile(diffs, 97.5)

def bootstrap_crash_lift(fwd_series, sep_in_mask, danger_mask, thresh, block_size=12, num_boot=1000):
    df = pd.DataFrame({'fwd': fwd_series, 'sep_in': sep_in_mask, 'danger': danger_mask}).dropna()
    n = len(df)
    if n < block_size: return np.nan, np.nan, np.nan
    blocks = [df.iloc[i:i+block_size] for i in range(n - block_size + 1)]
    num_blocks = len(blocks)
    lifts = []
    np.random.seed(42)
    for _ in range(num_boot):
        idx = np.random.randint(0, num_blocks, size=n // block_size + 1)
        boot_df = pd.concat([blocks[i] for i in idx]).iloc[:n]
        boot_sep_in = boot_df[boot_df['sep_in']]
        if len(boot_sep_in) == 0: continue
        base_prob = (boot_sep_in['fwd'] <= thresh).mean()
        boot_danger = boot_sep_in[boot_sep_in['danger']]
        danger_prob = (boot_danger['fwd'] <= thresh).mean() if len(boot_danger) > 0 else 0
        lifts.append(danger_prob - base_prob)
    if not lifts: return np.nan, np.nan, np.nan
    lifts = np.array(lifts)
    return (lifts > 0).mean(), np.percentile(lifts, 2.5), np.percentile(lifts, 97.5)

def run_ablation():
    idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, effr, z_series, vol_z, inf_z, sep_state, qqq_d = load_data()

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
        results[name] = res

    print("\n--- BLOCK BOOTSTRAP SHARPE REMOVAL TEST ---")
    perf_full = results['H_Full']
    ret_full = perf_full['equity'].pct_change().dropna().values
    
    def print_bootstrap_sharpe(layer, full_minus_name):
        ret_reduced = results[full_minus_name]['equity'].pct_change().dropna().values
        p_gt_0, ci_l, ci_u = bootstrap_sharpe_diff(ret_full, ret_reduced)
        print(f"{layer:<10s} P(Sharpe_Full > Sharpe_Reduced) = {p_gt_0*100:5.1f}% | 95% CI: [{ci_l:6.2f}, {ci_u:6.2f}]")

    print_bootstrap_sharpe("Credit", 'G_SEP_TIP_Vol')
    print_bootstrap_sharpe("TIP/TLT", 'F_SEP_Credit_Vol')
    print_bootstrap_sharpe("Vol", 'E_SEP_Credit_TIP')

    print("\n--- CONDITIONAL CRASH CAPTURE (SEP=IN) ---")
    weekly_idx = idx[::5]
    
    def get_forward_mdd(date, horizon_days):
        loc = qqq_d.index.get_loc(date)
        if loc + horizon_days >= len(qqq_d): return np.nan
        fut_slice = qqq_d.iloc[loc:loc+horizon_days]
        return ((fut_slice / fut_slice.expanding().max()) - 1).min()

    fwd_63 = pd.Series([get_forward_mdd(d, 63) for d in weekly_idx], index=weekly_idx)
    fwd_126 = pd.Series([get_forward_mdd(d, 126) for d in weekly_idx], index=weekly_idx)

    sep_in_mask = sep_state.reindex(weekly_idx) == 1
    danger_cr = pd.Series(perf_full['danger'], index=idx).reindex(weekly_idx) == True
    danger_tip = pd.Series(perf_full['inf_danger'], index=idx).reindex(weekly_idx) == True
    danger_vol = pd.Series(perf_full['vol_danger'], index=idx).reindex(weekly_idx) == True

    def get_prob(fwd_series, mask, thresh):
        valid = fwd_series[mask].dropna()
        if len(valid) == 0: return np.nan, 0
        return (valid <= thresh).mean(), len(valid)

    p63_base, n63_base = get_prob(fwd_63, sep_in_mask, -0.15)
    p126_base, n126_base = get_prob(fwd_126, sep_in_mask, -0.20)
    print(f"Baseline P(Crash|SEP=IN): 63d(-15%) = {p63_base*100:.1f}%, 126d(-20%) = {p126_base*100:.1f}%")

    def print_conditional(layer, danger_mask):
        cond_mask = sep_in_mask & danger_mask
        p63, n63 = get_prob(fwd_63, cond_mask, -0.15)
        p126, n126 = get_prob(fwd_126, cond_mask, -0.20)
        
        pg_63, ci_l_63, ci_u_63 = bootstrap_crash_lift(fwd_63, sep_in_mask, danger_mask, -0.15)
        pg_126, ci_l_126, ci_u_126 = bootstrap_crash_lift(fwd_126, sep_in_mask, danger_mask, -0.20)
        
        print(f"\n{layer:<10s} 63d: {p63*100:4.1f}% (Lift: {(p63-p63_base)*100:5.1f}%) | P(Lift>0)={pg_63*100:5.1f}%, 95% CI: [{ci_l_63*100:5.1f}%, {ci_u_63*100:5.1f}%]")
        print(f"{'':<10s} 126d: {p126*100:4.1f}% (Lift: {(p126-p126_base)*100:5.1f}%) | P(Lift>0)={pg_126*100:5.1f}%, 95% CI: [{ci_l_126*100:5.1f}%, {ci_u_126*100:5.1f}%]")

    print_conditional("Credit", danger_cr)
    print_conditional("TIP/TLT", danger_tip)
    print_conditional("Vol", danger_vol)

    print("\n--- RAW RESULTS DUMP ---")
    for name, res in results.items():
        print(f"{name:<20s} CAGR: {res['cagr']*100:>7.1f}% | Sharpe: {res['sharpe']:>8.2f} | MDD: {res['mdd']*100:>7.1f}%")

if __name__ == "__main__":
    run_ablation()
