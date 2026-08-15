#!/usr/bin/env python3
"""
Quick test: Vol danger → 1x (33% TQQQ) vs current 2x (66% TQQQ).
All other params stay sealed.
"""
import os
import numpy as np
import pandas as pd
import yfinance as yf
from fredapi import Fred

from strategy_engine import (
    Z_TRIGGER, Z_RECOVER, VZ_TRIGGER, VZ_RECOVER, VZ_LEV,
    INF_TRIGGER, INF_RECOVER, INF_LEV,
    Z_WINDOW, TC_BPS,
    compute_credit_z, compute_vol_z, compute_inflation_z,
    parse_sep_pdfs, build_sep_signals, build_sep_state,
    run_backtest as engine_run_backtest,
    get_fred_api_key,
)

FRED_API_KEY = get_fred_api_key()
PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP_DIR      = os.path.join(PROJECT_DIR, 'fomc_sep')
START_DATE   = '2012-01-25'

print("=" * 70)
print("  VOL DANGER: 1x (33%) vs 2x (66%) TEST")
print("=" * 70)

# ── Data Loading ──
print("\n[1] Loading data...")
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
hyg_d    = hyg_raw.reindex(idx).ffill()
ief_d    = ief_raw.reindex(idx).ffill()

dr_qqq_gap   = qqq_open / qqq_d.shift(1) - 1
dr_qqq_intra = qqq_d / qqq_open - 1

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

print(f"  Data: {idx[0].date()} → {idx[-1].date()} ({len(idx)} days)")

# ── Run both variants ──
print("\n[2] Running backtests...\n")

years = len(idx) / 252

configs = [
    ("SEALED (Vol → 2x / 66%)", VZ_LEV),    # current: 2.0
    ("TEST   (Vol → 1x / 33%)", 1.0),        # test: 1.0
]

print(f"  {'Config':<30s} {'Sharpe':>7} {'CAGR':>8} {'MDD':>8} {'Trades':>7} {'Tr/yr':>6}")
print(f"  {'-'*30} {'-'*7} {'-'*8} {'-'*8} {'-'*7} {'-'*6}")

for label, vz_lev in configs:
    r = engine_run_backtest(
        idx=idx, dr_qqq=dr_qqq,
        dr_qqq_gap=dr_qqq_gap, dr_qqq_intra=dr_qqq_intra,
        effr=effr, z_series=z_series, vol_z=vol_z, sep_state=sep_state,
        inf_z=inf_z,
        use_sep=True, use_overlay=True,
        z_trigger=Z_TRIGGER, z_recover=Z_RECOVER,
        vz_trigger=VZ_TRIGGER, vz_recover=VZ_RECOVER, vz_lev=vz_lev,
        inf_trigger=INF_TRIGGER, inf_recover=INF_RECOVER, inf_lev=INF_LEV,
        tc_bps=TC_BPS,
    )
    tpy = r['trades'] / years
    print(f"  {label:<30s} {r['sharpe']:>7.3f} {r['cagr']*100:>+7.1f}% {r['mdd']*100:>7.1f}% {r['trades']:>7} {tpy:>5.1f}")

    # OOS breakdown
    full_eq = r['equity']
    periods = [
        ('  IS 2012-2018',  '2012-01-25', '2018-12-31'),
        ('  OOS 2019-2022', '2019-01-01', '2022-12-31'),
        ('  FWD 2023-2026', '2023-01-01', '2026-12-31'),
    ]
    for plabel, start, end in periods:
        sl = full_eq.loc[start:end]
        if len(sl) < 50: continue
        sl_norm = sl / sl.iloc[0]
        ny = len(sl) / 252
        cagr = sl_norm.iloc[-1] ** (1/ny) - 1
        mdd = ((sl_norm / sl_norm.expanding().max()) - 1).min()
        daily_ret = sl.pct_change().dropna()
        sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else 0
        print(f"    {plabel:<26s} {sharpe:>7.3f} {cagr*100:>+7.1f}% {mdd*100:>7.1f}%")
    print()

print("Done.")
