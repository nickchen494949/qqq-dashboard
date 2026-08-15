#!/usr/bin/env python3
"""
MDD analysis + Sortino / Calmar / Omega ratios
"""
import os, numpy as np, pandas as pd, yfinance as yf
from fredapi import Fred
from strategy_engine import *

FRED_API_KEY = get_fred_api_key()
PROJECT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP_DIR      = os.path.join(PROJECT_DIR, 'fomc_sep')
START_DATE   = '2012-01-25'

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

print("Loading data...")
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

# Also get TQQQ B&H for comparison
tqqq_raw, _ = fetch_yahoo_ohlc('TQQQ')
tqqq_d = tqqq_raw.reindex(idx).ffill()

print("Running backtests...\n")

# Run sealed backtest
r = run_backtest(
    idx=idx, dr_qqq=dr_qqq,
    dr_qqq_gap=dr_qqq_gap, dr_qqq_intra=dr_qqq_intra,
    effr=effr, z_series=z_series, vol_z=vol_z, sep_state=sep_state,
    inf_z=inf_z, use_sep=True, use_overlay=True,
)

eq = r['equity']
daily_ret = eq.pct_change().dropna()

# TQQQ B&H
tqqq_eq = tqqq_d / tqqq_d.iloc[0]
tqqq_ret = tqqq_eq.pct_change().dropna()

# ════════════════════════════════════════════════════════════
# RATIO CALCULATIONS
# ════════════════════════════════════════════════════════════

def calc_all_ratios(returns, equity, label):
    """Calculate Sharpe, Sortino, Calmar, Omega for a return series."""
    ret = returns.dropna().values
    ny = len(equity) / 252

    # Sharpe
    sharpe = (np.mean(ret) / np.std(ret)) * np.sqrt(252) if np.std(ret) > 0 else 0

    # Sortino (downside deviation only, threshold = 0)
    downside = ret[ret < 0]
    downside_std = np.sqrt(np.mean(downside**2)) if len(downside) > 0 else 1e-10
    sortino = (np.mean(ret) / downside_std) * np.sqrt(252)

    # Calmar (CAGR / |MDD|)
    eq_arr = equity.values
    cagr = eq_arr[-1] ** (1/ny) - 1 if eq_arr[0] == 1.0 else (eq_arr[-1]/eq_arr[0]) ** (1/ny) - 1
    running_max = np.maximum.accumulate(eq_arr)
    mdd = (eq_arr / running_max - 1).min()
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Omega (threshold = 0, ratio of gains to losses)
    gains = ret[ret > 0].sum()
    losses = abs(ret[ret < 0].sum())
    omega = (gains / losses) if losses > 0 else float('inf')

    # Additional stats
    skew = pd.Series(ret).skew()
    kurt = pd.Series(ret).kurtosis()  # excess kurtosis
    pct_positive = (ret > 0).mean() * 100
    worst_day = ret.min()
    best_day = ret.max()

    return {
        'label': label, 'cagr': cagr, 'mdd': mdd,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar, 'omega': omega,
        'skew': skew, 'kurtosis': kurt,
        'pct_positive': pct_positive,
        'worst_day': worst_day, 'best_day': best_day,
    }

strat = calc_all_ratios(daily_ret, eq, "Strategy (Sealed)")
bh = calc_all_ratios(tqqq_ret, tqqq_eq, "TQQQ Buy & Hold")

print("=" * 75)
print("  RISK-ADJUSTED PERFORMANCE RATIOS")
print("=" * 75)
print(f"\n  {'Metric':<25} {'Strategy':>15} {'TQQQ B&H':>15} {'Δ':>10}")
print(f"  {'-'*25} {'-'*15} {'-'*15} {'-'*10}")

metrics = [
    ('CAGR',           'cagr',         lambda x: f"{x*100:+.1f}%",  lambda x: f"{x*100:+.1f}pp"),
    ('MDD',            'mdd',          lambda x: f"{x*100:.1f}%",   lambda x: f"{x*100:+.1f}pp"),
    ('Sharpe',         'sharpe',       lambda x: f"{x:.3f}",        lambda x: f"{x:+.3f}"),
    ('Sortino',        'sortino',      lambda x: f"{x:.3f}",        lambda x: f"{x:+.3f}"),
    ('Calmar',         'calmar',       lambda x: f"{x:.3f}",        lambda x: f"{x:+.3f}"),
    ('Omega',          'omega',        lambda x: f"{x:.3f}",        lambda x: f"{x:+.3f}"),
    ('Skewness',       'skew',         lambda x: f"{x:.3f}",        lambda x: f"{x:+.3f}"),
    ('Excess Kurtosis','kurtosis',     lambda x: f"{x:.2f}",        lambda x: f"{x:+.2f}"),
    ('% Positive Days','pct_positive', lambda x: f"{x:.1f}%",       lambda x: f"{x:+.1f}pp"),
    ('Worst Day',      'worst_day',    lambda x: f"{x*100:.1f}%",   lambda x: f"{x*100:+.1f}pp"),
    ('Best Day',       'best_day',     lambda x: f"{x*100:.1f}%",   lambda x: f"{x*100:+.1f}pp"),
]

for name, key, fmt, dfmt in metrics:
    v1 = strat[key]
    v2 = bh[key]
    delta = v1 - v2
    print(f"  {name:<25} {fmt(v1):>15} {fmt(v2):>15} {dfmt(delta):>10}")

print(f"\n  Interpretation:")
print(f"    Sharpe:  risk-adjusted return (上下波动都算)")
print(f"    Sortino: 只看下行风险 → 越高越好")
print(f"    Calmar:  CAGR/|MDD| → 每承受1%最大回撤赚多少")
print(f"    Omega:   总收益/总亏损 → >1就是赚的比亏的多")

# Sub-period ratios
print(f"\n{'='*75}")
print(f"  SUB-PERIOD RATIOS (Strategy)")
print(f"{'='*75}")

periods = [
    ('IS 2012-2018',  '2012-01-25', '2018-12-31'),
    ('OOS 2019-2022', '2019-01-01', '2022-12-31'),
    ('FWD 2023-2026', '2023-01-01', '2026-12-31'),
]

print(f"\n  {'Period':<18} {'Sharpe':>8} {'Sortino':>8} {'Calmar':>8} {'Omega':>8} {'CAGR':>8} {'MDD':>8}")
print(f"  {'-'*18} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

for label, start, end in periods:
    sl = eq.loc[start:end]
    sl_norm = sl / sl.iloc[0]
    sl_ret = sl.pct_change().dropna()
    m = calc_all_ratios(sl_ret, sl_norm, label)
    print(f"  {label:<18} {m['sharpe']:>8.3f} {m['sortino']:>8.3f} {m['calmar']:>8.3f} {m['omega']:>8.3f} {m['cagr']*100:>+7.1f}% {m['mdd']*100:>7.1f}%")


# ════════════════════════════════════════════════════════════
# MDD ANALYSIS
# ════════════════════════════════════════════════════════════
print(f"\n{'='*75}")
print(f"  MDD DEEP DIVE")
print(f"{'='*75}")

running_max = eq.expanding().max()
drawdown = eq / running_max - 1

mdd_date = drawdown.idxmin()
mdd_val = drawdown.min()

peak_eq_val = running_max.loc[mdd_date]
peak_date = eq[eq == peak_eq_val].index[0]

recovery = eq.loc[mdd_date:]
recovered = recovery[recovery >= peak_eq_val]
recovery_date = recovered.index[0] if len(recovered) > 0 else "NOT RECOVERED"

print(f"\n  MAX DRAWDOWN: {mdd_val*100:.1f}%")
print(f"  Peak:     {peak_date.date()}  (equity: {eq.loc[peak_date]:.4f})")
print(f"  Trough:   {mdd_date.date()}  (equity: {eq.loc[mdd_date]:.4f})")
print(f"  Recovery: {recovery_date if isinstance(recovery_date, str) else recovery_date.date()}")
print(f"  Peak→Trough: {(mdd_date - peak_date).days} calendar days")
if not isinstance(recovery_date, str):
    print(f"  Trough→Recovery: {(recovery_date - mdd_date).days} calendar days")

# Find all distinct drawdown episodes
dd_episodes = []
in_dd = False
peak_d = None
trough_d = None
trough_val = 0

for d in idx:
    if drawdown.loc[d] == 0:
        if in_dd and peak_d is not None:
            dd_episodes.append({'peak': peak_d, 'trough': trough_d, 'dd': trough_val})
        in_dd = False
        peak_d = d
    else:
        if not in_dd:
            in_dd = True
            trough_d = d
            trough_val = drawdown.loc[d]
        if drawdown.loc[d] < trough_val:
            trough_d = d
            trough_val = drawdown.loc[d]

if in_dd and peak_d is not None:
    dd_episodes.append({'peak': peak_d, 'trough': trough_d, 'dd': trough_val})

dd_episodes.sort(key=lambda x: x['dd'])

print(f"\n  TOP 10 DRAWDOWN EVENTS:")
print(f"  {'#':<3} {'Peak':<12} {'Trough':<12} {'DD':>8} {'Days':>6}  {'Event':<25}")
print(f"  {'-'*3} {'-'*12} {'-'*12} {'-'*8} {'-'*6}  {'-'*25}")

for i, ep in enumerate(dd_episodes[:10]):
    t = ep['trough']
    days = (ep['trough'] - ep['peak']).days
    if pd.Timestamp('2020-02-01') <= t <= pd.Timestamp('2020-05-31'):
        event = "🦠 COVID Crash"
    elif pd.Timestamp('2022-01-01') <= t <= pd.Timestamp('2022-12-31'):
        event = "📈 2022 Fed Rate Hikes"
    elif pd.Timestamp('2018-10-01') <= t <= pd.Timestamp('2019-01-31'):
        event = "📉 2018 Q4 Selloff"
    elif pd.Timestamp('2025-03-01') <= t <= pd.Timestamp('2025-06-30'):
        event = "🏷️ 2025 Tariff War"
    elif pd.Timestamp('2015-08-01') <= t <= pd.Timestamp('2016-03-31'):
        event = "🇨🇳 2015-16 China/Oil"
    elif pd.Timestamp('2024-07-01') <= t <= pd.Timestamp('2024-09-30'):
        event = "🇯🇵 2024 Yen Carry Unwind"
    else:
        event = f"~{t.strftime('%Y-%m')}"

    print(f"  {i+1:<3} {ep['peak'].date()!s:<12} {ep['trough'].date()!s:<12} {ep['dd']*100:>7.1f}% {days:>6}  {event:<25}")

# Show trades during MDD period
print(f"\n  TRADES DURING MDD ({peak_date.date()} → {mdd_date.date()}):")
print(f"  {'Signal':<12} {'Exec':<12} {'From':>5} {'To':>5} {'Equity':>8} {'Reason':<10}")
print(f"  {'-'*12} {'-'*12} {'-'*5} {'-'*5} {'-'*8} {'-'*10}")
trade_count = 0
for t in r['trade_log']:
    exec_d = pd.Timestamp(t['exec_date'])
    if peak_date <= exec_d <= mdd_date:
        print(f"  {t['signal_date']:<12} {t['exec_date']:<12} {t['from_lev']:>4.0f}x {t['to_lev']:>4.0f}x {t['equity']:>8.4f} {t['reason']:<10}")
        trade_count += 1
if trade_count == 0:
    print(f"  (no trades during MDD period)")

# Leverage during MDD
levs = pd.Series(r['leverage'], index=idx)
dd_period = (idx >= peak_date) & (idx <= mdd_date)
dd_levs = levs[dd_period]
print(f"\n  Leverage during MDD: {dict(dd_levs.value_counts().sort_index())}")
print(f"  SEP state during MDD: {dict(sep_state[dd_period].value_counts())}")
