#!/usr/bin/env python3
"""
Agent Model — In-Sample / Out-of-Sample Validation.
Train agent coefficients on one period, test on another.
Does the model actually have real explanatory power, or just overfitting?
"""
import os, sys, warnings, json
import numpy as np, pandas as pd
import yfinance as yf
from fredapi import Fred
from numpy.linalg import lstsq

warnings.filterwarnings('ignore')

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))
from strategy_engine import get_fred_api_key

FRED_API_KEY = get_fred_api_key()
fred = Fred(api_key=FRED_API_KEY)
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data', 'ml_cache')

def load_fred(sid):
    path = os.path.join(DATA_DIR, f'fred_{sid}.csv')
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        if len(s) > 100: return s
    s = fred.get_series(sid, observation_start='2005-01-01').dropna()
    s.to_csv(path); return s

def load_yahoo(ticker):
    path = os.path.join(DATA_DIR, f'yahoo_{ticker}.csv')
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        if len(s) > 100: return s
    df = yf.download(ticker, start='2005-01-01', progress=False, auto_adjust=False)
    adj = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj, pd.DataFrame): adj = adj.iloc[:, 0]
    adj.to_csv(path); return adj

# ════════════════════════════════════
# 1. LOAD & BUILD (same as before)
# ════════════════════════════════════
print("Loading data...")
qqq = load_yahoo('QQQ'); spy = load_yahoo('SPY')
hyg = load_yahoo('HYG'); ief = load_yahoo('IEF')
vix = load_fred('VIXCLS'); hy_oas = load_fred('BAMLH0A0HYM2')
nfci = load_fred('NFCI'); t10y = load_fred('DGS10')
t2y = load_fred('DGS2'); t10y2y = load_fred('T10Y2Y')

idx = qqq.dropna().index
qqq = qqq.reindex(idx); spy = spy.reindex(idx).ffill()
hyg = hyg.reindex(idx).ffill(); ief = ief.reindex(idx).ffill()
vix = vix.reindex(idx, method='ffill').ffill()
hy_oas = hy_oas.reindex(idx, method='ffill').ffill()
nfci = nfci.resample('D').ffill().reindex(idx, method='ffill').ffill()
t10y = t10y.reindex(idx, method='ffill').ffill()
t10y2y = t10y2y.reindex(idx, method='ffill').ffill()

mask = idx >= '2007-01-01'
idx = idx[mask]
qqq=qqq[mask]; spy=spy[mask]; hyg=hyg[mask]; ief=ief[mask]
vix=vix[mask]; hy_oas=hy_oas[mask]; nfci=nfci[mask]
t10y=t10y[mask]; t10y2y=t10y2y[mask]

qqq_ret = qqq.pct_change()

# ════════════════════════════════════
# 2. AGENT SIGNALS
# ════════════════════════════════════
print("Building agent signals...")
signals = pd.DataFrame(index=idx)

# Passive
signals['passive'] = 1.0
signals.loc[signals.index.day <= 5, 'passive'] = 1.3

# Value
qqq_200w = qqq.rolling(252*4).mean()
val_ratio = qqq / qqq_200w
yield_chg = t10y - t10y.shift(63)
signals['value'] = (-(val_ratio - 1.0) - yield_chg.fillna(0) * 0.3).clip(-2, 2)

# Momentum
mom_12m = qqq.pct_change(252)
sma50 = qqq.rolling(50).mean()
sma200 = qqq.rolling(200).mean()
sma_signal = (sma50 / sma200 - 1) * 10
signals['momentum'] = ((mom_12m.fillna(0) * 3 + sma_signal.fillna(0)) / 2).clip(-3, 3)

# Market Maker
ret_1d = qqq_ret.fillna(0)
ret_5d = qqq.pct_change(5).fillna(0)
signals['mm'] = (-(ret_1d * 5 + ret_5d * 2)).clip(-2, 2)

# Hedge Fund
vix_z = (vix - vix.rolling(252).mean()) / vix.rolling(252).std().replace(0, 1)
hy_z = (hy_oas - hy_oas.rolling(252).mean()) / hy_oas.rolling(252).std().replace(0, 1)
nfci_z = (nfci - nfci.rolling(252).mean()) / nfci.rolling(252).std().replace(0, 1)
signals['hedge'] = (-(vix_z.fillna(0)*0.4 + hy_z.fillna(0)*0.3 + nfci_z.fillna(0)*0.2) + t10y2y.fillna(0)*0.1).clip(-3, 3)

# Retail
vix_inv = 1 / (vix / 20).clip(0.5, 3)
ret_20d = qqq.pct_change(20).fillna(0)
signals['retail'] = (mom_12m.fillna(0) * vix_inv.fillna(1) * 2).clip(-3, 3)
signals.loc[ret_20d < -0.1, 'retail'] = (signals.loc[ret_20d < -0.1, 'retail'] - 1.5).clip(-3, 3)

# GEX
realized_vol = ret_1d.rolling(20).std() * np.sqrt(252) * 100
implied_vol = vix.fillna(20)
vol_spread = implied_vol - realized_vol.fillna(implied_vol)
gex_raw = (-vol_spread.fillna(0) / 10 + (20 - vix.clip(10, 40).fillna(20)) / 20).clip(-3, 3)
signals['gex'] = (gex_raw * -(ret_5d.fillna(0) * 3)).clip(-3, 3)

# Clean
signals = signals.dropna()
common_idx = signals.index.intersection(qqq_ret.dropna().index)
signals = signals.loc[common_idx]
returns = qqq_ret.loc[common_idx]

agent_names = ['passive', 'value', 'momentum', 'mm', 'hedge', 'retail', 'gex']
print(f"  {len(signals)} days, {len(agent_names)} agents")

# ════════════════════════════════════
# 3. IS/OOS TESTING FRAMEWORK
# ════════════════════════════════════
print("\n" + "=" * 100)
print("  IN-SAMPLE / OUT-OF-SAMPLE VALIDATION")
print("=" * 100)

def fit_model(X, y):
    """Fit OLS: y = X @ betas. Return betas."""
    X_aug = np.column_stack([np.ones(len(X)), X])
    betas, _, _, _ = lstsq(X_aug, y, rcond=None)
    return betas

def eval_model(X, y, betas):
    """Evaluate model with fixed betas. Return R², contributions, predictions."""
    X_aug = np.column_stack([np.ones(len(X)), X])
    y_pred = X_aug @ betas
    
    ss_res = np.sum((y - y_pred)**2)
    ss_tot = np.sum((y - y.mean())**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    
    # Per-agent contributions
    contribs = {}
    for j, a in enumerate(agent_names):
        contribs[a] = betas[j+1] * X[:, j]
    contribs['intercept'] = np.full(len(X), betas[0])
    contribs['residual'] = y - y_pred
    
    # Variance share
    var_share = {}
    total_v = 0
    for a in agent_names:
        v = np.var(contribs[a])
        var_share[a] = v
        total_v += v
    for a in agent_names:
        var_share[a] = var_share[a] / total_v * 100 if total_v > 0 else 0
    
    return r2, contribs, var_share, y_pred

def standardize(X_train, X_test=None):
    """Standardize using training set statistics."""
    mu = X_train.mean(axis=0)
    std = X_train.std(axis=0)
    std[std == 0] = 1
    X_tr_s = (X_train - mu) / std
    if X_test is not None:
        X_te_s = (X_test - mu) / std  # use TRAIN stats
        return X_tr_s, X_te_s, mu, std
    return X_tr_s, mu, std

# ── Test configurations ──
splits = [
    ('2008-2015 → 2016-2019', '2008-01-01', '2015-12-31', '2016-01-01', '2019-12-31'),
    ('2008-2019 → 2020-2022', '2008-01-01', '2019-12-31', '2020-01-01', '2022-12-31'),
    ('2008-2019 → 2020-2025', '2008-01-01', '2019-12-31', '2020-01-01', '2025-12-31'),
    ('2008-2022 → 2023-2025', '2008-01-01', '2022-12-31', '2023-01-01', '2025-12-31'),
    ('2012-2019 → 2020-2025', '2012-01-01', '2019-12-31', '2020-01-01', '2025-12-31'),
]

all_results = []

for name, tr_s, tr_e, te_s, te_e in splits:
    tr_mask = (signals.index >= tr_s) & (signals.index <= tr_e)
    te_mask = (signals.index >= te_s) & (signals.index <= te_e)
    
    X_tr = signals.loc[tr_mask][agent_names].values
    y_tr = returns.loc[tr_mask].values
    X_te = signals.loc[te_mask][agent_names].values
    y_te = returns.loc[te_mask].values
    
    if len(X_tr) < 100 or len(X_te) < 50:
        print(f"\n  {name}: Not enough data (train={len(X_tr)}, test={len(X_te)})")
        continue
    
    # Standardize using train stats
    X_tr_s, X_te_s, mu, std = standardize(X_tr, X_te)
    
    # Fit on train
    betas = fit_model(X_tr_s, y_tr)
    
    # Evaluate on train (IS) and test (OOS)
    r2_is, contribs_is, var_is, pred_is = eval_model(X_tr_s, y_tr, betas)
    r2_oos, contribs_oos, var_oos, pred_oos = eval_model(X_te_s, y_te, betas)
    
    # Direction accuracy
    dir_is = np.mean((pred_is > 0) == (y_tr > 0))
    dir_oos = np.mean((pred_oos > 0) == (y_te > 0))
    
    # Correlation
    corr_is = np.corrcoef(pred_is, y_tr)[0, 1]
    corr_oos = np.corrcoef(pred_oos, y_te)[0, 1]
    
    all_results.append({
        'name': name, 'n_train': len(X_tr), 'n_test': len(X_te),
        'r2_is': r2_is, 'r2_oos': r2_oos,
        'dir_is': dir_is, 'dir_oos': dir_oos,
        'corr_is': corr_is, 'corr_oos': corr_oos,
        'var_is': var_is, 'var_oos': var_oos,
        'betas': betas,
    })
    
    print(f"\n{'━'*100}")
    print(f"  SPLIT: {name}")
    print(f"  Train: {tr_s} to {tr_e} ({len(X_tr)} days) | Test: {te_s} to {te_e} ({len(X_te)} days)")
    print(f"{'━'*100}")
    
    print(f"\n  {'Metric':<25} {'In-Sample':>12} {'Out-of-Sample':>15} {'Δ':>8} {'Verdict':>10}")
    print(f"  {'─'*25} {'─'*12} {'─'*15} {'─'*8} {'─'*10}")
    
    r2_drop = r2_oos - r2_is
    dir_drop = dir_oos - dir_is
    corr_drop = corr_oos - corr_is
    
    def verdict(drop, threshold):
        if drop > -threshold: return '✅ Stable'
        elif drop > -threshold*3: return '⚠️ Weaker'
        else: return '❌ Failed'
    
    print(f"  {'R²':<25} {r2_is:>11.3f} {r2_oos:>14.3f} {r2_drop:>+7.3f} {verdict(r2_drop, 0.05):>10}")
    print(f"  {'Direction Accuracy':<25} {dir_is:>10.1%} {dir_oos:>13.1%} {dir_drop*100:>+6.1f}pp {verdict(dir_drop, 0.03):>10}")
    print(f"  {'Correlation':<25} {corr_is:>11.3f} {corr_oos:>14.3f} {corr_drop:>+7.3f} {verdict(corr_drop, 0.05):>10}")
    
    # Variance decomposition IS vs OOS
    print(f"\n  {'Agent':<20} {'IS Var%':>8} {'OOS Var%':>9} {'Δ':>7} {'Stable?':>8}")
    print(f"  {'─'*20} {'─'*8} {'─'*9} {'─'*7} {'─'*8}")
    for a in sorted(agent_names, key=lambda x: var_is[x], reverse=True):
        delta = var_oos[a] - var_is[a]
        stable = '✓' if abs(delta) < 10 else ('⬆' if delta > 0 else '⬇')
        print(f"  {a:<20} {var_is[a]:>7.1f}% {var_oos[a]:>8.1f}% {delta:>+6.1f}% {stable:>8}")
    
    # Beta stability
    print(f"\n  Agent Betas (trained on IS, applied to OOS):")
    print(f"  {'Agent':<20} {'Beta':>8} {'Direction':>10}")
    print(f"  {'─'*20} {'─'*8} {'─'*10}")
    for j, a in enumerate(agent_names):
        b = betas[j+1]
        d = '→ bullish' if b > 0 else '→ bearish'
        bar = '█' * int(abs(b) * 500)
        print(f"  {a:<20} {b:>+7.4f} {d:<10} {bar}")

# ════════════════════════════════════
# 4. EXPANDING WINDOW WALK-FORWARD
# ════════════════════════════════════
print(f"\n\n{'='*100}")
print("  EXPANDING WINDOW WALK-FORWARD (most rigorous)")
print("=" * 100)
print("  Train on expanding window, test on next year. Never look ahead.")

MIN_TRAIN_YEARS = 5
STEP_DAYS = 252  # 1 year steps

wf_results = []
start_idx = 0
train_end = MIN_TRAIN_YEARS * 252

while train_end + STEP_DAYS <= len(signals):
    X_tr = signals.iloc[:train_end][agent_names].values
    y_tr = returns.iloc[:train_end].values
    X_te = signals.iloc[train_end:train_end+STEP_DAYS][agent_names].values
    y_te = returns.iloc[train_end:train_end+STEP_DAYS].values
    
    test_start = signals.index[train_end]
    test_end = signals.index[min(train_end+STEP_DAYS-1, len(signals)-1)]
    
    X_tr_s, X_te_s, mu, std = standardize(X_tr, X_te)
    betas = fit_model(X_tr_s, y_tr)
    r2_is, _, var_is, _ = eval_model(X_tr_s, y_tr, betas)
    r2_oos, contribs_oos, var_oos, pred_oos = eval_model(X_te_s, y_te, betas)
    
    dir_oos = np.mean((pred_oos > 0) == (y_te > 0))
    corr_oos = np.corrcoef(pred_oos, y_te)[0, 1] if np.std(pred_oos) > 0 else 0
    
    wf_results.append({
        'year': test_start.strftime('%Y'),
        'period': f"{test_start.strftime('%Y-%m')} → {test_end.strftime('%Y-%m')}",
        'n_train': len(X_tr), 'n_test': len(X_te),
        'r2_is': r2_is, 'r2_oos': r2_oos,
        'dir_oos': dir_oos, 'corr_oos': corr_oos,
        'var_oos': var_oos,
    })
    
    train_end += STEP_DAYS

# Print walk-forward results
print(f"\n  {'Test Period':<20} {'Train':>6} {'R²(IS)':>7} {'R²(OOS)':>8} {'Dir%':>6} {'Corr':>6} │ Top Agent OOS")
print(f"  {'─'*20} {'─'*6} {'─'*7} {'─'*8} {'─'*6} {'─'*6} │ {'─'*30}")

for r in wf_results:
    top_agent = max(r['var_oos'], key=r['var_oos'].get)
    r2_color = '✅' if r['r2_oos'] > 0 else '❌'
    print(f"  {r['period']:<20} {r['n_train']:>5}d {r['r2_is']:>6.3f} {r2_color}{r['r2_oos']:>6.3f} {r['dir_oos']:>5.1%} {r['corr_oos']:>+5.3f} │ {top_agent} ({r['var_oos'][top_agent]:.0f}%)")

# Summary stats
avg_r2_oos = np.mean([r['r2_oos'] for r in wf_results])
avg_dir_oos = np.mean([r['dir_oos'] for r in wf_results])
avg_corr_oos = np.mean([r['corr_oos'] for r in wf_results])
pct_positive_r2 = np.mean([r['r2_oos'] > 0 for r in wf_results])

print(f"\n  Walk-Forward Summary ({len(wf_results)} folds):")
print(f"    Avg OOS R²:           {avg_r2_oos:>+.4f}")
print(f"    Avg OOS Direction:    {avg_dir_oos:>.1%}")
print(f"    Avg OOS Correlation:  {avg_corr_oos:>+.4f}")
print(f"    Folds with R² > 0:   {pct_positive_r2:.0%} ({sum(r['r2_oos']>0 for r in wf_results)}/{len(wf_results)})")

# ════════════════════════════════════
# 5. AGENT STABILITY ACROSS PERIODS
# ════════════════════════════════════
print(f"\n\n{'='*100}")
print("  AGENT IMPORTANCE STABILITY ACROSS OOS PERIODS")
print("=" * 100)

print(f"\n  {'Agent':<15}", end='')
for r in wf_results:
    print(f" {r['year']:>6}", end='')
print(f" {'Avg':>6} {'Std':>5} {'Stable':>7}")

print(f"  {'─'*15}", end='')
for _ in wf_results:
    print(f" {'─'*6}", end='')
print(f" {'─'*6} {'─'*5} {'─'*7}")

for a in agent_names:
    vals = [r['var_oos'][a] for r in wf_results]
    avg = np.mean(vals)
    std = np.std(vals)
    stable = '✅' if std < 15 else '⚠️'
    print(f"  {a:<15}", end='')
    for v in vals:
        print(f" {v:>5.1f}%", end='')
    print(f" {avg:>5.1f}% {std:>4.1f} {stable}")

# ════════════════════════════════════
# 6. FINAL VERDICT
# ════════════════════════════════════
print(f"\n\n{'='*100}")
print("  FINAL VERDICT")
print("=" * 100)

if avg_r2_oos > 0.02:
    print(f"\n  ✅ Model has REAL out-of-sample explanatory power (avg R²={avg_r2_oos:.3f})")
elif avg_r2_oos > 0:
    print(f"\n  ⚠️  Model has WEAK out-of-sample power (avg R²={avg_r2_oos:.4f})")
else:
    print(f"\n  ❌ Model has NO out-of-sample power (avg R²={avg_r2_oos:.4f})")

if pct_positive_r2 >= 0.7:
    print(f"  ✅ R² is positive in {pct_positive_r2:.0%} of OOS periods — consistent")
else:
    print(f"  ⚠️  R² is positive in only {pct_positive_r2:.0%} of OOS periods — inconsistent")

if avg_dir_oos > 0.52:
    print(f"  ✅ OOS direction accuracy {avg_dir_oos:.1%} beats 50% coin flip")
else:
    print(f"  ⚠️  OOS direction accuracy {avg_dir_oos:.1%} — no better than coin flip")

# Agent stability
stable_agents = []
unstable_agents = []
for a in agent_names:
    vals = [r['var_oos'][a] for r in wf_results]
    if np.std(vals) < 15:
        stable_agents.append(a)
    else:
        unstable_agents.append(a)

print(f"\n  Stable agents (consistent across periods): {', '.join(stable_agents) if stable_agents else 'None'}")
print(f"  Unstable agents (varies by period): {', '.join(unstable_agents) if unstable_agents else 'None'}")

print(f"""
  Interpretation:
  • R² in-sample is always high (~0.8+) because the model has 7 agents fitting daily noise.
  • The KEY question is: does R² stay positive out-of-sample?
  • If OOS R² ≈ 0, the agent decomposition is descriptive but not predictive.
  • If OOS R² > 0 consistently, the agent framework captures real market dynamics.
  • Even small OOS R² (0.01-0.05) on DAILY returns is meaningful for strategy design.
""")
