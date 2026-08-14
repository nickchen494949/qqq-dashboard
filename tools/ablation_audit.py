#!/usr/bin/env python3
import os
import sys
import hashlib
import argparse
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
FROZEN_DIR   = os.path.join(PROJECT_DIR, 'data', 'frozen', 'ablation_2026-08-13')

def get_checksum(s):
    return hashlib.md5(pd.util.hash_pandas_object(s).values).hexdigest()[:8]

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

def load_data(live=False, freeze=False):
    use_frozen = not live and os.path.exists(FROZEN_DIR)
    
    if use_frozen:
        print(f"Loading frozen raw data from {FROZEN_DIR} ...")
        effr_raw = pd.read_csv(os.path.join(FROZEN_DIR, 'effr.csv'), index_col=0, parse_dates=True).squeeze("columns")
        qqq_c = pd.read_csv(os.path.join(FROZEN_DIR, 'qqq_c.csv'), index_col=0, parse_dates=True).squeeze("columns")
        qqq_o = pd.read_csv(os.path.join(FROZEN_DIR, 'qqq_o.csv'), index_col=0, parse_dates=True).squeeze("columns")
        hyg_c = pd.read_csv(os.path.join(FROZEN_DIR, 'hyg_c.csv'), index_col=0, parse_dates=True).squeeze("columns")
        ief_c = pd.read_csv(os.path.join(FROZEN_DIR, 'ief_c.csv'), index_col=0, parse_dates=True).squeeze("columns")
        tip_c = pd.read_csv(os.path.join(FROZEN_DIR, 'tip_c.csv'), index_col=0, parse_dates=True).squeeze("columns")
        tlt_c = pd.read_csv(os.path.join(FROZEN_DIR, 'tlt_c.csv'), index_col=0, parse_dates=True).squeeze("columns")
    else:
        print("Fetching LIVE data from Yahoo/FRED...")
        fred = Fred(api_key=get_fred_api_key())
        effr_raw = fred.get_series('DFF', observation_start='2005-01-01').dropna()
        qqq_c, qqq_o = fetch_yahoo_ohlc('QQQ')
        hyg_c, _ = fetch_yahoo_ohlc('HYG')
        ief_c, _ = fetch_yahoo_ohlc('IEF')
        tip_c, _ = fetch_yahoo_ohlc('TIP')
        tlt_c, _ = fetch_yahoo_ohlc('TLT')

    # Common Processing
    idx = qqq_c.index[qqq_c.index >= pd.Timestamp(START_DATE)]
    qqq_d    = qqq_c.reindex(idx)
    qqq_open = qqq_o.reindex(idx)
    dr_qqq   = qqq_d.pct_change()
    dr_qqq_gap   = qqq_open / qqq_d.shift(1) - 1
    dr_qqq_intra = qqq_d / qqq_open - 1
    effr     = effr_raw.reindex(idx).ffill() / 100 / 252

    full_idx = qqq_c.dropna().index
    hyg_full = hyg_c.reindex(full_idx).ffill()
    ief_full = ief_c.reindex(full_idx).ffill()
    tip_full = tip_c.reindex(full_idx).ffill()
    tlt_full = tlt_c.reindex(full_idx).ffill()
    dr_full  = qqq_c.reindex(full_idx).pct_change()

    z_full     = compute_credit_z(hyg_full, ief_full)
    vol_z_full = compute_vol_z(dr_full)
    inf_z_full = compute_inflation_z(tip_full, tlt_full)

    z_series = z_full.reindex(idx)
    vol_z    = vol_z_full.reindex(idx)
    inf_z    = inf_z_full.reindex(idx)

    # SEP State
    if use_frozen:
        sep_state = pd.read_csv(os.path.join(FROZEN_DIR, 'sep_state.csv'), index_col=0, parse_dates=True).squeeze("columns")
    else:
        sep_raw = parse_sep_pdfs(SEP_DIR)
        sep_signals = build_sep_signals(sep_raw)
        sep_state, _ = build_sep_state(sep_signals, idx)

    checksums = {
        'qqq_d': get_checksum(qqq_d),
        'effr': get_checksum(effr),
        'z_series': get_checksum(z_series),
        'vol_z': get_checksum(vol_z),
        'inf_z': get_checksum(inf_z),
        'sep_state': get_checksum(sep_state),
        'end_date': idx[-1].strftime('%Y-%m-%d')
    }

    if freeze and not use_frozen:
        print(f"Freezing data to {FROZEN_DIR} ...")
        os.makedirs(FROZEN_DIR, exist_ok=True)
        effr_raw.to_csv(os.path.join(FROZEN_DIR, 'effr.csv'))
        qqq_c.to_csv(os.path.join(FROZEN_DIR, 'qqq_c.csv'))
        qqq_o.to_csv(os.path.join(FROZEN_DIR, 'qqq_o.csv'))
        hyg_c.to_csv(os.path.join(FROZEN_DIR, 'hyg_c.csv'))
        ief_c.to_csv(os.path.join(FROZEN_DIR, 'ief_c.csv'))
        tip_c.to_csv(os.path.join(FROZEN_DIR, 'tip_c.csv'))
        tlt_c.to_csv(os.path.join(FROZEN_DIR, 'tlt_c.csv'))
        sep_state.to_csv(os.path.join(FROZEN_DIR, 'sep_state.csv'))
        
        with open(os.path.join(FROZEN_DIR, 'metadata.txt'), 'w') as f:
            f.write(f"Snapshot End Date: {checksums['end_date']}\n")
            f.write(f"Commit: 9da31883c783220fd55f3a3e57698857ba0efac6\n") # Preserved from latest
            f.write("Checksums:\n")
            for k, v in checksums.items():
                if k != 'end_date': f.write(f"{k}: {v}\n")
        print("Freeze complete.")

    return idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, effr, z_series, vol_z, inf_z, sep_state, qqq_d, checksums

def bootstrap_sharpe_diff(ret_full, ret_reduced, block_size, num_boot):
    n = len(ret_full)
    diffs = []
    np.random.seed(42)
    blocks_full = [ret_full[i:i+block_size] for i in range(n - block_size + 1)]
    blocks_red = [ret_reduced[i:i+block_size] for i in range(n - block_size + 1)]
    num_blocks = len(blocks_full)
    if num_blocks <= 0: return 0.0, 0.0, 0.0
    for _ in range(num_boot):
        idx = np.random.randint(0, num_blocks, size=n // block_size + 1)
        boot_full = np.concatenate([blocks_full[i] for i in idx])[:n]
        boot_red = np.concatenate([blocks_red[i] for i in idx])[:n]
        shp_f = (boot_full.mean() / boot_full.std()) * np.sqrt(252) if boot_full.std() > 0 else 0
        shp_r = (boot_red.mean() / boot_red.std()) * np.sqrt(252) if boot_red.std() > 0 else 0
        diffs.append(shp_f - shp_r)
    if not diffs: return 0.0, 0.0, 0.0
    diffs = np.array(diffs)
    return (diffs > 0).mean(), np.percentile(diffs, 2.5), np.percentile(diffs, 97.5)

def bootstrap_crash_lift(fwd_series, sep_in_mask, danger_mask, thresh, block_size, num_boot):
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

def run_ablation(live=False, freeze=False):
    idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, effr, z_series, vol_z, inf_z, sep_state, qqq_d, checksums = load_data(live, freeze)

    print("--- DATA SNAPSHOT ---")
    print(f"End Date: {checksums['end_date']}")
    for k, v in checksums.items():
        if k != 'end_date': print(f"  {k}: {v}")
    
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
    print("\nRunning Ablation Sweep...")
    for name, (zi, vi, ii) in variants.items():
        res = engine_run_backtest(
            idx=idx, dr_qqq=dr_qqq, dr_qqq_gap=dr_qqq_gap, dr_qqq_intra=dr_qqq_intra,
            effr=effr, z_series=zi, vol_z=vi, sep_state=sep_state, inf_z=ii,
            use_sep=True, use_overlay=True
        )
        results[name] = res

    perf_full = results['H_Full']
    ret_full = perf_full['equity'].pct_change().dropna().values
    
    print("\n--- BLOCK BOOTSTRAP SHARPE SENSITIVITY (10,000 Iters) ---")
    for b_size in [21, 63, 126]:
        print(f"\nBlock Size: {b_size} days")
        def print_bootstrap_sharpe(layer, full_minus_name):
            ret_reduced = results[full_minus_name]['equity'].pct_change().dropna().values
            p_gt_0, ci_l, ci_u = bootstrap_sharpe_diff(ret_full, ret_reduced, block_size=b_size, num_boot=10000)
            print(f"  {layer:<10s} P(ΔSharpe>0) = {p_gt_0*100:5.1f}% | 95% CI: [{ci_l:6.2f}, {ci_u:6.2f}]")
        print_bootstrap_sharpe("Credit", 'G_SEP_TIP_Vol')
        print_bootstrap_sharpe("TIP/TLT", 'F_SEP_Credit_Vol')
        print_bootstrap_sharpe("Vol", 'E_SEP_Credit_TIP')

    print("\n--- CONDITIONAL CRASH CAPTURE (SEP=IN, 10,000 Iters) ---")
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
        
        pg_63, ci_l_63, ci_u_63 = bootstrap_crash_lift(fwd_63, sep_in_mask, danger_mask, -0.15, block_size=13, num_boot=10000)
        pg_126, ci_l_126, ci_u_126 = bootstrap_crash_lift(fwd_126, sep_in_mask, danger_mask, -0.20, block_size=26, num_boot=10000)
        
        print(f"\n{layer:<10s} 63d: {p63*100:4.1f}% (Lift: {(p63-p63_base)*100:5.1f}%) | 95% CI: [{ci_l_63*100:5.1f}%, {ci_u_63*100:5.1f}%]")
        print(f"{'':<10s} 126d: {p126*100:4.1f}% (Lift: {(p126-p126_base)*100:5.1f}%) | 95% CI: [{ci_l_126*100:5.1f}%, {ci_u_126*100:5.1f}%]")

    print_conditional("Credit", danger_cr)
    print_conditional("TIP/TLT", danger_tip)
    print_conditional("Vol", danger_vol)
    
    print("\n--- IN-SAMPLE PERIOD ABLATION (SHARPE) ---")
    periods = [
        ('2012-2018', '2012-01-01', '2018-12-31'),
        ('2019-2022', '2019-01-01', '2022-12-31'),
        ('2023-2026', '2023-01-01', '2026-12-31')
    ]
    def calc_period_sharpe(eq, st, ed):
        try:
            sl = eq.loc[st:ed]
            if len(sl) < 10: return 0.0
            ret = sl.pct_change().dropna()
            return (ret.mean() / ret.std()) * np.sqrt(252) if ret.std() > 0 else 0
        except KeyError:
            return 0.0

    print(f"{'Period':<15s} | {'Full':>6s} | {'No_Cr':>6s} | {'No_TIP':>6s} | {'No_Vol':>6s}")
    for p_name, p_st, p_ed in periods:
        sf = calc_period_sharpe(perf_full['equity'], p_st, p_ed)
        scr = calc_period_sharpe(results['G_SEP_TIP_Vol']['equity'], p_st, p_ed)
        stip = calc_period_sharpe(results['F_SEP_Credit_Vol']['equity'], p_st, p_ed)
        svol = calc_period_sharpe(results['E_SEP_Credit_TIP']['equity'], p_st, p_ed)
        print(f"{p_name:<15s} | {sf:>6.2f} | {scr:>6.2f} | {stip:>6.2f} | {svol:>6.2f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Fetch live data instead of frozen")
    parser.add_argument("--freeze", action="store_true", help="Freeze fetched live data to snapshot dir")
    args = parser.parse_args()
    
    run_ablation(live=args.live, freeze=args.freeze)
