#!/usr/bin/env python3
"""
ML Validation: Address all concerns about the initial results.
1. Purged walk-forward with embargo (no label overlap)
2. Always-up baseline
3. Confusion matrix / down-market precision
4. Remove 2021-2022 sensitivity test
5. Real-time CPI lag (use t-1 month)
6. Balanced accuracy, MCC, AUC
7. Return-weighted accuracy
"""
import os, sys, warnings
import numpy as np, pandas as pd
import yfinance as yf
from fredapi import Fred
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LassoCV, LogisticRegressionCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, 
                             precision_score, recall_score, f1_score,
                             matthews_corrcoef, confusion_matrix, roc_auc_score)
import xgboost as xgb

warnings.filterwarnings('ignore')

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))
from strategy_engine import get_fred_api_key, compute_credit_z, compute_vol_z, compute_inflation_z

FRED_API_KEY = get_fred_api_key()
fred = Fred(api_key=FRED_API_KEY)
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data', 'ml_cache')

# ═══════════════════════════════════════
# LOAD CACHED DATA (from previous run)
# ═══════════════════════════════════════
def load_fred(sid):
    path = os.path.join(DATA_DIR, f'fred_{sid}.csv')
    if os.path.exists(path):
        return pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
    return fred.get_series(sid, observation_start='2003-01-01').dropna()

def load_yahoo(ticker):
    path = os.path.join(DATA_DIR, f'yahoo_{ticker}.csv')
    if os.path.exists(path):
        return pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
    df = yf.download(ticker, start='2003-01-01', progress=False)
    adj = df['Close'] if 'Close' in df.columns else df.iloc[:, 0]
    if isinstance(adj, pd.DataFrame): adj = adj.iloc[:, 0]
    return adj

print("Loading data...")
qqq_daily = load_yahoo('QQQ')
spy_daily = load_yahoo('SPY')
hyg_daily = load_yahoo('HYG')
ief_daily = load_yahoo('IEF')
tip_daily = load_yahoo('TIP')
tlt_daily = load_yahoo('TLT')
gld_daily = load_yahoo('GLD')
uup_daily = load_yahoo('UUP')

fred_data = {}
for sid in ['DFF','DGS10','DGS2','T10Y2Y','T10Y3M','T10YIE',
            'BAMLH0A0HYM2','BAMLC0A0CM','VIXCLS','M2SL','UMCSENT',
            'UNRATE','IC4WSA','CPIAUCSL','PCEPILFE','NFCI','INDPRO']:
    try:
        fred_data[sid] = load_fred(sid)
    except:
        pass

# ═══════════════════════════════════════
# BUILD FEATURES (with real-time CPI lag)
# ═══════════════════════════════════════
print("Building features...")
qqq = qqq_daily.resample('ME').last().dropna()
features = pd.DataFrame(index=qqq.index)

def add_fred(name, sid, transform='level', lag=0):
    """lag=1 means use previous month's value (real-time safe)"""
    if sid not in fred_data: return
    s = fred_data[sid].resample('ME').last().ffill().reindex(qqq.index, method='ffill')
    if lag > 0:
        s = s.shift(lag)  # ← CRITICAL: simulate real-time availability
    if transform == 'level': features[name] = s
    elif transform == 'change_3m': features[name] = s - s.shift(3)
    elif transform == 'change_12m': features[name] = s - s.shift(12)
    elif transform == 'yoy': features[name] = s.pct_change(12) * 100

# Rates (available same day → lag=0)
add_fred('fed_rate', 'DFF')
add_fred('fed_rate_chg12m', 'DFF', 'change_12m')
add_fred('yield_10y', 'DGS10')
add_fred('yield_10y_chg3m', 'DGS10', 'change_3m')
add_fred('yield_2y', 'DGS2')
add_fred('spread_10y2y', 'T10Y2Y')
add_fred('spread_10y2y_chg3m', 'T10Y2Y', 'change_3m')
add_fred('spread_10y3m', 'T10Y3M')
add_fred('breakeven_inf', 'T10YIE')

# Credit (available same day)
add_fred('hy_oas', 'BAMLH0A0HYM2')
add_fred('hy_oas_chg3m', 'BAMLH0A0HYM2', 'change_3m')
add_fred('ig_oas', 'BAMLC0A0CM')

# VIX (available same day)
add_fred('vix', 'VIXCLS')

# ★ CPI/PCE: lag=1 (published ~2 weeks after month end → use previous month)
add_fred('cpi_yoy', 'CPIAUCSL', 'yoy', lag=1)
add_fred('core_pce_yoy', 'PCEPILFE', 'yoy', lag=1)

# M2 (lag=1, published with delay)
add_fred('m2_yoy', 'M2SL', 'yoy', lag=1)

# Consumer sentiment (lag=0, preliminary available mid-month)
add_fred('consumer_sent', 'UMCSENT')

# Employment (lag=0, weekly data)
add_fred('unemployment', 'UNRATE', lag=1)
add_fred('claims_4wk', 'IC4WSA')

# Financial conditions (lag=0, weekly)
add_fred('nfci', 'NFCI')

# Industrial production (lag=1)
add_fred('indpro_yoy', 'INDPRO', 'yoy', lag=1)

# Price features (no lag issue)
features['qqq_ret_1m'] = qqq.pct_change(1) * 100
features['qqq_ret_3m'] = qqq.pct_change(3) * 100
features['qqq_ret_6m'] = qqq.pct_change(6) * 100
features['qqq_ret_12m'] = qqq.pct_change(12) * 100

sma200 = qqq_daily.rolling(200).mean()
sma50 = qqq_daily.rolling(50).mean()
features['qqq_vs_sma200'] = ((qqq_daily / sma200 - 1) * 100).resample('ME').last().reindex(qqq.index)
features['qqq_vs_sma50'] = ((qqq_daily / sma50 - 1) * 100).resample('ME').last().reindex(qqq.index)

daily_ret = qqq_daily.pct_change()
features['realized_vol_20d'] = (daily_ret.rolling(20).std() * np.sqrt(252) * 100).resample('ME').last().reindex(qqq.index)

# Z-scores
full_idx = qqq_daily.dropna().index
features['credit_z'] = compute_credit_z(hyg_daily.reindex(full_idx).ffill(), ief_daily.reindex(full_idx).ffill()).resample('ME').last().reindex(qqq.index)
features['vol_z'] = compute_vol_z(daily_ret.reindex(full_idx)).resample('ME').last().reindex(qqq.index)
features['inf_z'] = compute_inflation_z(tip_daily.reindex(full_idx).ffill(), tlt_daily.reindex(full_idx).ffill()).resample('ME').last().reindex(qqq.index)

# Cross-asset
spy = spy_daily.resample('ME').last().reindex(qqq.index)
features['qqq_vs_spy_3m'] = (qqq.pct_change(3) - spy.pct_change(3)) * 100
gld = gld_daily.resample('ME').last().reindex(qqq.index)
features['gold_ret_3m'] = gld.pct_change(3) * 100
uup = uup_daily.resample('ME').last().reindex(qqq.index)
features['dollar_ret_3m'] = uup.pct_change(3) * 100

# VIX percentile
if 'VIXCLS' in fred_data:
    vix_m = fred_data['VIXCLS'].resample('ME').last().ffill().reindex(qqq.index, method='ffill')
    features['vix_pctl_12m'] = vix_m.rolling(12).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)

# Targets
targets = pd.DataFrame(index=qqq.index)
targets['fwd_3m'] = qqq.pct_change(3).shift(-3) * 100
targets['fwd_6m'] = qqq.pct_change(6).shift(-6) * 100

# Clean
features = features.ffill().bfill()
good_cols = features.columns[features.isnull().mean() < 0.5]
features = features[good_cols].dropna()
valid = features.index.intersection(targets.dropna(subset=['fwd_3m']).index)
valid = valid[valid >= '2007-01-01']
X_all = features.loc[valid].copy()
y_all = targets.loc[valid].copy()

print(f"  Features: {X_all.shape[1]}, Samples: {len(X_all)} months")
print(f"  Period: {X_all.index[0].strftime('%Y-%m')} to {X_all.index[-1].strftime('%Y-%m')}")

# ═══════════════════════════════════════
# VALIDATION 1: Always-up baseline
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  VALIDATION 1: BASELINE — ALWAYS PREDICT UP")
print("=" * 90)

for horizon in ['fwd_3m', 'fwd_6m']:
    y_h = y_all[horizon].dropna()
    pct_up = (y_h > 0).mean()
    print(f"  {horizon}: {pct_up:.1%} of months have positive forward return")
    print(f"  → A monkey that always says 'up' gets {pct_up:.1%} accuracy")

# ═══════════════════════════════════════
# VALIDATION 2: Purged Walk-Forward + Embargo
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  VALIDATION 2: PURGED WALK-FORWARD + EMBARGO")
print("=" * 90)
print("  For fwd_Nm, embargo = N months between train end and test start")

MIN_TRAIN = 60
STEP = 12

def run_purged_wf(X_all, y_all, horizon, embargo_months):
    """Walk-forward with embargo gap between train and test."""
    y_h = y_all[horizon].dropna()
    valid_h = X_all.index.intersection(y_h.index)
    X = X_all.loc[valid_h]
    y = y_h.loc[valid_h]
    y_bin = (y > 0).astype(int)
    
    folds = []
    start = MIN_TRAIN
    while start + embargo_months + STEP <= len(X):
        train_idx = list(range(start))
        # skip embargo_months after train end
        test_start = start + embargo_months
        test_end = min(test_start + STEP, len(X))
        test_idx = list(range(test_start, test_end))
        folds.append((train_idx, test_idx))
        start += STEP
    
    if len(folds) == 0:
        return None
    
    all_actual = []; all_pred_rf = []; all_pred_lasso = []; all_pred_xgb = []
    all_pred_lr = []
    all_actual_cont = []; all_pred_rf_cont = []; all_pred_xgb_cont = []; all_pred_lasso_cont = []
    
    for train_idx, test_idx in folds:
        X_tr, X_te = X.iloc[train_idx], X.iloc[test_idx]
        y_tr, y_te = y.iloc[train_idx], y.iloc[test_idx]
        yb_tr, yb_te = y_bin.iloc[train_idx], y_bin.iloc[test_idx]
        
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        
        # Regression
        rf = RandomForestRegressor(n_estimators=200, max_depth=5, min_samples_leaf=5, random_state=42, n_jobs=-1)
        rf.fit(X_tr_s, y_tr)
        
        xgb_m = xgb.XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8, 
                                   colsample_bytree=0.8, random_state=42, verbosity=0)
        xgb_m.fit(X_tr_s, y_tr)
        
        lasso = LassoCV(cv=5, random_state=42, max_iter=5000)
        lasso.fit(X_tr_s, y_tr)
        
        # Classification
        lr = LogisticRegressionCV(cv=5, random_state=42, max_iter=5000)
        lr.fit(X_tr_s, yb_tr)
        
        all_actual.extend(yb_te.values)
        all_pred_rf.extend((rf.predict(X_te_s) > 0).astype(int))
        all_pred_xgb.extend((xgb_m.predict(X_te_s) > 0).astype(int))
        all_pred_lasso.extend((lasso.predict(X_te_s) > 0).astype(int))
        all_pred_lr.extend(lr.predict(X_te_s))
        
        all_actual_cont.extend(y_te.values)
        all_pred_rf_cont.extend(rf.predict(X_te_s))
        all_pred_xgb_cont.extend(xgb_m.predict(X_te_s))
        all_pred_lasso_cont.extend(lasso.predict(X_te_s))
    
    actual = np.array(all_actual)
    actual_cont = np.array(all_actual_cont)
    
    results = {}
    for name, preds in [('RF', all_pred_rf), ('XGB', all_pred_xgb), 
                         ('Lasso', all_pred_lasso), ('Logistic', all_pred_lr)]:
        preds = np.array(preds)
        cm = confusion_matrix(actual, preds, labels=[0, 1])
        tn, fp, fn, tp = cm.ravel()
        
        results[name] = {
            'accuracy': accuracy_score(actual, preds),
            'balanced_acc': balanced_accuracy_score(actual, preds),
            'mcc': matthews_corrcoef(actual, preds),
            'precision_down': precision_score(actual, preds, pos_label=0, zero_division=0),
            'recall_down': recall_score(actual, preds, pos_label=0, zero_division=0),
            'precision_up': precision_score(actual, preds, pos_label=1, zero_division=0),
            'recall_up': recall_score(actual, preds, pos_label=1, zero_division=0),
            'cm': cm,
            'n_predict_down': (preds == 0).sum(),
            'n_predict_up': (preds == 1).sum(),
        }
    
    # Return-weighted accuracy
    for name, preds_cont in [('RF', all_pred_rf_cont), ('XGB', all_pred_xgb_cont), 
                              ('Lasso', all_pred_lasso_cont)]:
        preds_cont = np.array(preds_cont)
        # How much would you earn if you went 3x when pred>0, 1x when pred<0?
        rets = actual_cont / 100  # convert back to decimal
        signal = np.where(preds_cont > 0, 3, 1)
        strat_ret = signal * rets
        bh_ret = 3 * rets
        results[name]['strat_mean_monthly'] = np.mean(strat_ret) * 100
        results[name]['bh_mean_monthly'] = np.mean(bh_ret) * 100
    
    return results, len(folds), actual

for horizon, embargo in [('fwd_3m', 3), ('fwd_6m', 6)]:
    print(f"\n{'─'*70}")
    print(f"  {horizon} (embargo = {embargo} months)")
    print(f"{'─'*70}")
    
    ret = run_purged_wf(X_all, y_all, horizon, embargo)
    if ret is None:
        print("  ⚠️ Not enough data")
        continue
    
    results, n_folds, actual = ret
    n_up = actual.sum()
    n_down = len(actual) - n_up
    baseline = n_up / len(actual)
    
    print(f"  Folds: {n_folds} | Total samples: {len(actual)} | Up: {n_up} ({baseline:.1%}) | Down: {n_down} ({1-baseline:.1%})")
    print(f"  Always-up baseline: {baseline:.1%}")
    
    print(f"\n  {'Model':<10} {'Acc':>6} {'BalAcc':>7} {'MCC':>6} | {'P↓':>5} {'R↓':>5} {'P↑':>5} {'R↑':>5} | {'#↓':>4} {'#↑':>4}")
    print(f"  {'─'*10} {'─'*6} {'─'*7} {'─'*6}   {'─'*5} {'─'*5} {'─'*5} {'─'*5}   {'─'*4} {'─'*4}")
    for name in ['RF', 'XGB', 'Lasso', 'Logistic']:
        r = results[name]
        print(f"  {name:<10} {r['accuracy']:.1%} {r['balanced_acc']:>6.1%} {r['mcc']:>+5.2f} | "
              f"{r['precision_down']:>4.1%} {r['recall_down']:>4.1%} {r['precision_up']:>4.1%} {r['recall_up']:>4.1%} | "
              f"{r['n_predict_down']:>4} {r['n_predict_up']:>4}")
    
    print(f"\n  {'BASELINE':<10} {baseline:.1%}   {'—':>7} {'—':>6} |   {'—':>5} {'—':>5} {'—':>5} {'—':>5} | {'0':>4} {len(actual):>4}")
    
    # Confusion matrices
    print(f"\n  Confusion Matrices (Lasso):")
    cm = results['Lasso']['cm']
    print(f"                  Predicted")
    print(f"                  Down   Up")
    print(f"    Actual Down  [{cm[0,0]:>4}  {cm[0,1]:>4}]")
    print(f"    Actual Up    [{cm[1,0]:>4}  {cm[1,1]:>4}]")
    
    # Return-weighted
    print(f"\n  Return-weighted (mean monthly % with 3x/1x switching):")
    for name in ['RF', 'XGB', 'Lasso']:
        r = results[name]
        edge = r['strat_mean_monthly'] - r['bh_mean_monthly']
        print(f"    {name:<10}: ML strategy {r['strat_mean_monthly']:>+5.2f}%/mo vs B&H 3x {r['bh_mean_monthly']:>+5.2f}%/mo → edge {edge:>+5.2f}%/mo")

# ═══════════════════════════════════════
# VALIDATION 3: Remove 2021-2022 sensitivity
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  VALIDATION 3: REMOVE 2021-2022 SENSITIVITY TEST")
print("=" * 90)
print("  Re-running with 2021-01 to 2022-12 excluded from TRAINING data")
print("  to see if CPI importance drops (was it just memorizing inflation shock?)")

horizon = 'fwd_3m'
embargo = 3
y_h = y_all[horizon].dropna()
valid_h = X_all.index.intersection(y_h.index)
X = X_all.loc[valid_h]
y = y_h.loc[valid_h]
y_bin = (y > 0).astype(int)

# Full model importance (for comparison)
scaler = StandardScaler()
X_full_s = scaler.fit_transform(X)

rf_full = RandomForestRegressor(n_estimators=200, max_depth=5, min_samples_leaf=5, random_state=42, n_jobs=-1)
rf_full.fit(X_full_s, y)
imp_full = pd.Series(rf_full.feature_importances_, index=X.columns).sort_values(ascending=False)

# Model WITHOUT 2021-2022 in training
mask_no_2122 = ~((X.index >= '2021-01-01') & (X.index <= '2022-12-31'))
X_no = X[mask_no_2122]
y_no = y[mask_no_2122]

scaler2 = StandardScaler()
X_no_s = scaler2.fit_transform(X_no)

rf_no = RandomForestRegressor(n_estimators=200, max_depth=5, min_samples_leaf=5, random_state=42, n_jobs=-1)
rf_no.fit(X_no_s, y_no)
imp_no = pd.Series(rf_no.feature_importances_, index=X.columns).sort_values(ascending=False)

# Also XGBoost
xgb_full = xgb.XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8, 
                              colsample_bytree=0.8, random_state=42, verbosity=0)
xgb_full.fit(X_full_s, y)
ximp_full = pd.Series(xgb_full.feature_importances_, index=X.columns)

xgb_no = xgb.XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8, 
                            colsample_bytree=0.8, random_state=42, verbosity=0)
xgb_no.fit(X_no_s, y_no)
ximp_no = pd.Series(xgb_no.feature_importances_, index=X.columns)

# Combined
full_combined = (imp_full / imp_full.sum() + ximp_full / ximp_full.sum()) / 2
no_combined = (imp_no / imp_no.sum() + ximp_no / ximp_no.sum()) / 2

comp = pd.DataFrame({
    'Full': full_combined,
    'No_2122': no_combined,
}).sort_values('Full', ascending=False)
comp['Delta'] = comp['No_2122'] - comp['Full']
comp['Stable?'] = comp.apply(lambda r: '✓' if abs(r['Delta']) < 0.02 else ('⬇' if r['Delta'] < 0 else '⬆'), axis=1)

print(f"\n  {'Feature':<25} {'Full':>8} {'No2122':>8} {'Delta':>8} {'Stable':>6}")
print(f"  {'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*6}")
for feat, row in comp.head(15).iterrows():
    print(f"  {feat:<25} {row['Full']:>7.3f} {row['No_2122']:>7.3f} {row['Delta']:>+7.3f} {row['Stable?']:>6}")

print(f"\n  Training samples: Full={len(X)}, No 2021-22={len(X_no)} (removed {len(X)-len(X_no)} months)")

# ═══════════════════════════════════════
# VALIDATION 4: CPI lag impact
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  VALIDATION 4: CPI REAL-TIME LAG IMPACT")
print("=" * 90)
print("  CPI is now lagged by 1 month (real-time safe).")
print("  Previous run used CPI without lag (potential look-ahead).")
print("  Comparing CPI importance with lag vs single-feature correlation:")

# Single feature correlation with lagged CPI
cpi_col = 'cpi_yoy'
if cpi_col in X.columns:
    for h in ['fwd_3m', 'fwd_6m']:
        yy = y_all[h].dropna()
        vv = X_all.index.intersection(yy.index)
        corr = X_all.loc[vv, cpi_col].corr(yy.loc[vv])
        print(f"  CPI YoY (lagged 1M) → {h}: Pearson = {corr:+.3f}")

# ═══════════════════════════════════════
# VALIDATION 5: Non-overlapping samples only
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  VALIDATION 5: NON-OVERLAPPING SAMPLES (every 3rd/6th month)")
print("=" * 90)

for horizon, step in [('fwd_3m', 3), ('fwd_6m', 6)]:
    y_h = y_all[horizon].dropna()
    valid_h = X_all.index.intersection(y_h.index)
    X = X_all.loc[valid_h]
    y = y_h.loc[valid_h]
    
    # Take every Nth sample to avoid overlap entirely
    X_nonoverlap = X.iloc[::step]
    y_nonoverlap = y.iloc[::step]
    y_bin = (y_nonoverlap > 0).astype(int)
    
    baseline = y_bin.mean()
    n = len(X_nonoverlap)
    
    print(f"\n  {horizon} — using every {step}th month → {n} independent samples")
    print(f"  Baseline (always-up): {baseline:.1%}")
    
    if n < 30:
        print(f"  ⚠️ Only {n} samples, too few for reliable results")
        continue
    
    # Simple train/test split (first 70% train, last 30% test)
    split = int(n * 0.7)
    X_tr, X_te = X_nonoverlap.iloc[:split], X_nonoverlap.iloc[split:]
    y_tr, y_te = y_nonoverlap.iloc[:split], y_nonoverlap.iloc[split:]
    yb_tr, yb_te = (y_tr > 0).astype(int), (y_te > 0).astype(int)
    
    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_te_s = scaler.transform(X_te)
    
    # Train models
    rf = RandomForestRegressor(n_estimators=200, max_depth=5, min_samples_leaf=5, random_state=42, n_jobs=-1)
    rf.fit(X_tr_s, y_tr)
    
    lasso = LassoCV(cv=min(5, split), random_state=42, max_iter=5000)
    lasso.fit(X_tr_s, y_tr)
    
    lr = LogisticRegressionCV(cv=min(5, split), random_state=42, max_iter=5000)
    lr.fit(X_tr_s, yb_tr)
    
    test_baseline = yb_te.mean()
    
    print(f"  Train: {split} samples ({X_tr.index[0].strftime('%Y-%m')} to {X_tr.index[-1].strftime('%Y-%m')})")
    print(f"  Test:  {n-split} samples ({X_te.index[0].strftime('%Y-%m')} to {X_te.index[-1].strftime('%Y-%m')})")
    print(f"  Test baseline (always-up): {test_baseline:.1%}")
    
    # Results
    for name, preds in [('RF', (rf.predict(X_te_s) > 0).astype(int)),
                         ('Lasso', (lasso.predict(X_te_s) > 0).astype(int)),
                         ('Logistic', lr.predict(X_te_s))]:
        preds = np.array(preds)
        acc = accuracy_score(yb_te, preds)
        bacc = balanced_accuracy_score(yb_te, preds)
        mcc = matthews_corrcoef(yb_te, preds)
        n_down = (preds == 0).sum()
        n_up = (preds == 1).sum()
        print(f"    {name:<10}: Acc={acc:.1%}  BalAcc={bacc:.1%}  MCC={mcc:+.2f}  (pred ↓{n_down} ↑{n_up})")

# ═══════════════════════════════════════
# VALIDATION 6: Feature importance by category
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("  VALIDATION 6: GROUP IMPORTANCE (correlated features grouped)")
print("=" * 90)

groups = {
    'Inflation/Rates Regime': ['cpi_yoy','core_pce_yoy','breakeven_inf','yield_10y','yield_10y_chg3m',
                                'yield_2y','fed_rate','fed_rate_chg12m','spread_10y3m','spread_10y2y',
                                'spread_10y2y_chg3m','nfci'],
    'Risk/Volatility': ['vix','vix_pctl_12m','realized_vol_20d','vol_z'],
    'Trend/Momentum': ['qqq_ret_1m','qqq_ret_3m','qqq_ret_6m','qqq_ret_12m','qqq_vs_sma200','qqq_vs_sma50'],
    'Credit Stress': ['hy_oas','hy_oas_chg3m','ig_oas','credit_z'],
    'Labor/Economy': ['unemployment','claims_4wk','indpro_yoy','m2_yoy','consumer_sent'],
    'Cross-Asset': ['qqq_vs_spy_3m','gold_ret_3m','dollar_ret_3m'],
    'Strategy Z-scores': ['credit_z','vol_z','inf_z'],
}

# Use the combined importance from full model
for scenario, imp in [('Full Sample', full_combined), ('Without 2021-22', no_combined)]:
    print(f"\n  {scenario}:")
    group_imp = {}
    for gname, feats in groups.items():
        feats_avail = [f for f in feats if f in imp.index]
        group_imp[gname] = imp[feats_avail].sum()
    
    total = sum(group_imp.values())
    for gname in sorted(group_imp, key=group_imp.get, reverse=True):
        pct = group_imp[gname] / total * 100
        bar = '█' * int(pct / 2)
        print(f"    {gname:<25} {pct:>5.1f}%  {bar}")

print("\n" + "=" * 90)
print("  ALL VALIDATIONS COMPLETE")
print("=" * 90)
