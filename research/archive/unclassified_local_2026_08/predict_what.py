#!/usr/bin/env python3
"""
WHAT CAN WE ACTUALLY PREDICT? (v2 — fixed data pipeline)
Walk-forward OOS on 3 targets: direction, volatility, hostile regime.
"""
import os, sys, warnings
import numpy as np, pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.metrics import accuracy_score, balanced_accuracy_score, matthews_corrcoef, r2_score, mean_absolute_error
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data', 'ml_cache')

def lf(s): return pd.read_csv(os.path.join(DATA_DIR, f'fred_{s}.csv'), index_col=0, parse_dates=True).squeeze()
def ly(t): return pd.read_csv(os.path.join(DATA_DIR, f'yahoo_{t}.csv'), index_col=0, parse_dates=True).squeeze()

print("Loading...")
qqq = ly('QQQ'); spy = ly('SPY')
vix = lf('VIXCLS'); hy_oas = lf('BAA10Y')
nfci = lf('NFCI'); t10y = lf('DGS10'); t2y = lf('DGS2'); t10y2y = lf('T10Y2Y')

# Daily align from 2005 (need lookback)
idx = qqq.dropna().index
idx = idx[idx >= '2005-01-01']
qqq=qqq.reindex(idx); spy=spy.reindex(idx).ffill()
vix=vix.reindex(idx,method='ffill').ffill()
hy_oas=hy_oas.reindex(idx,method='ffill').ffill()
nfci=nfci.resample('D').ffill().reindex(idx,method='ffill').ffill()
t10y=t10y.reindex(idx,method='ffill').ffill()
t2y=t2y.reindex(idx,method='ffill').ffill()
t10y2y=t10y2y.reindex(idx,method='ffill').ffill()

qqq_ret_d = qqq.pct_change()

# Weekly resample
qqq_w = qqq.resample('W-FRI').last().dropna()
spy_w = spy.resample('W-FRI').last().dropna()
widx = qqq_w.index

print(f"  Weekly data: {widx[0].strftime('%Y-%m')} to {widx[-1].strftime('%Y-%m')} ({len(widx)} weeks)")

# ═══════════════════════════════════
# FEATURES
# ═══════════════════════════════════
print("Building features...")
feat = pd.DataFrame(index=widx)

# Vol features
rv_20d = qqq_ret_d.rolling(20).std() * np.sqrt(252)
rv_60d = qqq_ret_d.rolling(60).std() * np.sqrt(252)
feat['rv_20d'] = rv_20d.resample('W-FRI').last().reindex(widx)
feat['rv_60d'] = rv_60d.resample('W-FRI').last().reindex(widx)
feat['rv_ratio'] = (feat['rv_20d'] / feat['rv_60d'].replace(0, np.nan))

# VIX
vix_w = vix.resample('W-FRI').last().reindex(widx)
feat['vix'] = vix_w
feat['vix_z'] = (vix_w - vix_w.rolling(52).mean()) / vix_w.rolling(52).std()
feat['vix_vs_rv'] = vix_w/100 - feat['rv_20d']
feat['vix_chg4w'] = vix_w - vix_w.shift(4)

# Credit
hy_w = hy_oas.resample('W-FRI').last().reindex(widx)
feat['hy_oas'] = hy_w
feat['hy_z'] = (hy_w - hy_w.rolling(52).mean()) / hy_w.rolling(52).std()
feat['hy_chg4w'] = hy_w - hy_w.shift(4)

# Rates
t10y_w = t10y.resample('W-FRI').last().reindex(widx)
t2y_w = t2y.resample('W-FRI').last().reindex(widx)
feat['t10y'] = t10y_w
feat['t2y'] = t2y_w
feat['curve'] = t10y2y.resample('W-FRI').last().reindex(widx)
feat['rate_chg4w'] = t10y_w - t10y_w.shift(4)

# Financial conditions
nfci_w = nfci.resample('W-FRI').last().reindex(widx)
feat['nfci'] = nfci_w
feat['nfci_chg4w'] = nfci_w - nfci_w.shift(4)

# Momentum
feat['mom_4w'] = qqq_w.pct_change(4)
feat['mom_13w'] = qqq_w.pct_change(13)
feat['mom_52w'] = qqq_w.pct_change(52)

# Trend
sma50_w = qqq.rolling(50).mean().resample('W-FRI').last().reindex(widx)
sma200_w = qqq.rolling(200).mean().resample('W-FRI').last().reindex(widx)
feat['vs_sma50'] = qqq_w / sma50_w - 1
feat['vs_sma200'] = qqq_w / sma200_w - 1

# Relative strength
feat['qqq_vs_spy'] = qqq_w.pct_change(4) - spy_w.pct_change(4).reindex(widx)

# Valuation proxy: earnings yield premium = inverse of price/200w-MA as rough valuation
feat['val_z'] = -(qqq_w / qqq_w.rolling(208).mean() - 1)  # 4-year MA deviation

# Drop NaN from lookback
feat = feat.dropna()
print(f"  Features ready: {len(feat)} weeks, {feat.shape[1]} features")
print(f"  Range: {feat.index[0].strftime('%Y-%m')} to {feat.index[-1].strftime('%Y-%m')}")

# ═══════════════════════════════════
# TARGETS
# ═══════════════════════════════════
print("Building targets...")

# Forward 4-week return (from weekly prices)
fwd_ret = qqq_w.shift(-4) / qqq_w - 1

# Forward realized vol + drawdown (from daily prices)
fwd_rv = pd.Series(dtype=float, index=widx)
fwd_mdd = pd.Series(dtype=float, index=widx)
for dt in widx:
    fut = qqq.loc[qqq.index > dt].head(22)
    if len(fut) < 10: continue
    fr = fut.pct_change().dropna()
    if len(fr) >= 5:
        fwd_rv[dt] = fr.std() * np.sqrt(252)
    pk = fut.cummax()
    fwd_mdd[dt] = (fut / pk - 1).min()

# Align to features
fwd_ret = fwd_ret.reindex(feat.index)
fwd_rv = fwd_rv.reindex(feat.index)
fwd_mdd = fwd_mdd.reindex(feat.index)

valid = fwd_ret.notna() & fwd_rv.notna() & fwd_mdd.notna()
feat = feat.loc[valid]; fwd_ret = fwd_ret.loc[valid]
fwd_rv = fwd_rv.loc[valid]; fwd_mdd = fwd_mdd.loc[valid]

fwd_dir = (fwd_ret > 0).astype(int)
fwd_hostile = (fwd_mdd < -0.05).astype(int)

print(f"  Final: {len(feat)} weeks")
print(f"  Up: {fwd_dir.mean():.1%} | Hostile: {fwd_hostile.mean():.1%}")

# ═══════════════════════════════════
# WALK-FORWARD
# ═══════════════════════════════════
MIN_TRAIN = 3*52  # 3 years
STEP = 26         # 6 months test
EMBARGO = 5       # 5 weeks gap

X = feat.values
feature_names = list(feat.columns)

def walk_forward(y, is_clf=True):
    results = []
    te = MIN_TRAIN
    while te + EMBARGO + STEP <= len(X):
        tr = list(range(te))
        ts = te + EMBARGO
        ti = list(range(ts, min(ts+STEP, len(X))))
        
        sc = StandardScaler()
        Xtr = sc.fit_transform(X[tr]); Xte = sc.transform(X[ti])
        
        if is_clf:
            m = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42)
        else:
            m = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42)
        
        m.fit(Xtr, y[tr])
        p = m.predict(Xte)
        
        # Feature importance from last fold
        fi = dict(zip(feature_names, m.feature_importances_))
        
        results.append({'actual': y[ti], 'pred': p, 'dates': feat.index[ti], 'n_train': len(tr), 'fi': fi})
        te += STEP
    return results

print(f"\n{'='*90}")
print(f"  WALK-FORWARD OOS — 3 PREDICTION TARGETS")
print(f"  {MIN_TRAIN} week min train, {EMBARGO} week embargo, {STEP} week test")
print(f"{'='*90}")

# ── TARGET 1: DIRECTION ──
print(f"\n{'━'*90}")
print(f"  TARGET 1: 1-MONTH RETURN DIRECTION (up/down)")
print(f"{'━'*90}")

res1 = walk_forward(fwd_dir.values, is_clf=True)
a1 = np.concatenate([r['actual'] for r in res1])
p1 = np.concatenate([r['pred'] for r in res1])
bl1 = a1.mean()
acc1 = accuracy_score(a1, p1)
mcc1 = matthews_corrcoef(a1, p1)
bacc1 = balanced_accuracy_score(a1, p1)
print(f"  Baseline (always up):  {bl1:.1%}")
print(f"  Model accuracy:        {acc1:.1%}  (edge: {(acc1-bl1)*100:+.1f}pp)")
print(f"  Balanced accuracy:     {bacc1:.1%}")
print(f"  MCC:                   {mcc1:+.3f}")
print(f"  {'→ ✅ Direction edge' if acc1 > bl1+0.03 else '→ ❌ No direction edge'}")

# Top features
avg_fi = {}
for a in feature_names: avg_fi[a] = np.mean([r['fi'].get(a,0) for r in res1])
top5 = sorted(avg_fi, key=avg_fi.get, reverse=True)[:5]
print(f"  Top features: {', '.join(f'{f}({avg_fi[f]:.2f})' for f in top5)}")

# ── TARGET 2: VOLATILITY ──
print(f"\n{'━'*90}")
print(f"  TARGET 2: 1-MONTH FORWARD REALIZED VOLATILITY")
print(f"{'━'*90}")

res2 = walk_forward(fwd_rv.values, is_clf=False)
a2 = np.concatenate([r['actual'] for r in res2])
p2 = np.concatenate([r['pred'] for r in res2])

r2_ml = r2_score(a2, p2)
corr_ml = np.corrcoef(a2, p2)[0,1]
mae_ml = mean_absolute_error(a2, p2)

# Naive: use current vol
naive2 = []
te = MIN_TRAIN
while te + EMBARGO + STEP <= len(X):
    ts = te + EMBARGO
    ti = list(range(ts, min(ts+STEP, len(X))))
    naive2.extend(feat['rv_20d'].values[ti])
    te += STEP
naive2 = np.array(naive2[:len(a2)])
r2_naive = r2_score(a2, naive2)
corr_naive = np.corrcoef(a2, naive2)[0,1]

print(f"  Naive (current vol):   R²={r2_naive:.3f}  Corr={corr_naive:.3f}")
print(f"  ML model:              R²={r2_ml:.3f}  Corr={corr_ml:.3f}  MAE={mae_ml:.3f}")
print(f"  Improvement vs naive:  R² {r2_ml-r2_naive:+.3f}")
if r2_ml > 0.3:
    print(f"  → ✅ Vol is HIGHLY predictable")
elif r2_ml > 0.1:
    print(f"  → ✅ Vol has real predictability")
else:
    print(f"  → ⚠️  Vol prediction weak")

avg_fi2 = {}
for a in feature_names: avg_fi2[a] = np.mean([r['fi'].get(a,0) for r in res2])
top5v = sorted(avg_fi2, key=avg_fi2.get, reverse=True)[:5]
print(f"  Top features: {', '.join(f'{f}({avg_fi2[f]:.2f})' for f in top5v)}")

# ── TARGET 3: HOSTILE ──
print(f"\n{'━'*90}")
print(f"  TARGET 3: HOSTILE REGIME (>5% drawdown in next month)")
print(f"{'━'*90}")

res3 = walk_forward(fwd_hostile.values, is_clf=True)
a3 = np.concatenate([r['actual'] for r in res3])
p3 = np.concatenate([r['pred'] for r in res3])
bl3 = 1 - a3.mean()
acc3 = accuracy_score(a3, p3)
mcc3 = matthews_corrcoef(a3, p3)
bacc3 = balanced_accuracy_score(a3, p3)

from sklearn.metrics import precision_score, recall_score
prec3 = precision_score(a3, p3, zero_division=0)
rec3 = recall_score(a3, p3, zero_division=0)

print(f"  Hostile rate:          {a3.mean():.1%} ({int(a3.sum())}/{len(a3)})")
print(f"  Baseline (never):      {bl3:.1%}")
print(f"  Model accuracy:        {acc3:.1%}")
print(f"  Balanced accuracy:     {bacc3:.1%}")
print(f"  MCC:                   {mcc3:+.3f}")
print(f"  Precision(hostile):    {prec3:.1%}")
print(f"  Recall(hostile):       {rec3:.1%}")
print(f"  Predicted hostile:     {int(p3.sum())} times")
if mcc3 > 0.2:
    print(f"  → ✅ Hostile regime IS predictable")
elif mcc3 > 0.1:
    print(f"  → ⚠️  Weak hostile signal")
else:
    print(f"  → ❌ Cannot predict hostile")

avg_fi3 = {}
for a in feature_names: avg_fi3[a] = np.mean([r['fi'].get(a,0) for r in res3])
top5h = sorted(avg_fi3, key=avg_fi3.get, reverse=True)[:5]
print(f"  Top features: {', '.join(f'{f}({avg_fi3[f]:.2f})' for f in top5h)}")

# ═══════════════════════════════════
# STRATEGY PNL
# ═══════════════════════════════════
print(f"\n{'━'*90}")
print(f"  STRATEGY BACKTEST — USE PREDICTIONS FOR LEVERAGE")
print(f"{'━'*90}")

# Collect OOS predictions
preds = {}
for label, res in [('dir', res1), ('vol', res2), ('hostile', res3)]:
    dates = np.concatenate([r['dates'] for r in res])
    vals = np.concatenate([r['pred'] for r in res])
    preds[label] = pd.Series(vals, index=dates).sort_index()

preds_df = pd.DataFrame(preds)
daily_ret = qqq.pct_change().dropna()
preds_daily = preds_df.reindex(daily_ret.index, method='ffill').dropna()
dr = daily_ret.loc[preds_daily.index].values

# S1: hostile → 1x, else 3x
lev1 = np.where(preds_daily['hostile']==1, 1, 3)
# S2: vol-scaled (target 20% vol)
lev2 = np.clip(0.20 / preds_daily['vol'].clip(0.05,1).values, 0.5, 3)
# S3: combined
lev3 = np.where(preds_daily['hostile']==1, 1, lev2)
# S4: direction + hostile
lev4 = np.where(preds_daily['hostile']==1, 1, np.where(preds_daily['dir']==1, 3, 1))

def stats(r, name):
    eq = np.cumprod(1+r)
    ny = len(r)/252
    cagr = (eq[-1]**(1/ny)-1)*100 if eq[-1]>0 else -99
    mdd = (eq/np.maximum.accumulate(eq)-1).min()*100
    sh = np.mean(r)/np.std(r)*np.sqrt(252) if np.std(r)>0 else 0
    dn = r[r<0]; ds = np.sqrt(np.mean(dn**2)) if len(dn)>0 else 1e-10
    so = np.mean(r)/ds*np.sqrt(252)
    return f"  {name:<35} {cagr:>+6.1f}% {mdd:>6.1f}% {sh:>6.2f} {so:>7.2f}"

print(f"\n  {'Strategy':<35} {'CAGR':>7} {'MDD':>7} {'Sharpe':>6} {'Sortino':>7}")
print(f"  {'─'*35} {'─'*7} {'─'*7} {'─'*6} {'─'*7}")
print(stats(lev1*dr, 'Hostile filter (hostile→1x)'))
print(stats(lev2*dr, 'Vol-scaled leverage'))
print(stats(lev3*dr, 'Combined (hostile+vol)'))
print(stats(lev4*dr, 'Direction+hostile filter'))
print(stats(3*dr, 'Buy & Hold 3x'))
print(stats(dr, 'Buy & Hold 1x'))

# ═══════════════════════════════════
# FINAL
# ═══════════════════════════════════
print(f"\n{'='*90}")
print(f"  WHAT CAN YOU PREDICT?")
print(f"{'='*90}")
print(f"""
  ┌─────────────────────┬──────────────┬───────────────────────────────────┐
  │ Target              │ Predictable? │ Evidence                          │
  ├─────────────────────┼──────────────┼───────────────────────────────────┤
  │ Return direction    │ {'✅ Yes' if acc1>bl1+0.03 else '❌ No':>12} │ Acc={acc1:.0%} vs {bl1:.0%} base, MCC={mcc1:+.2f}{' '*4}│
  │ Forward volatility  │ {'✅ Yes' if r2_ml>0.1 else '❌ No':>12} │ R²={r2_ml:.3f} vs {r2_naive:.3f} naive{' '*7}│
  │ Hostile regime      │ {'✅ Yes' if mcc3>0.15 else '❌ No':>12} │ MCC={mcc3:+.2f}, P={prec3:.0%}, R={rec3:.0%}{' '*9}│
  └─────────────────────┴──────────────┴───────────────────────────────────┘
""")
